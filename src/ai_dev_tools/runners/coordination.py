from __future__ import annotations

import json
import os
import time
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

from ai_dev_tools.models.report import Artifact, Report, Status
from ai_dev_tools.security.secrets import mask_text

SCHEMA_VERSION = "1.0"
STATE_PATH = Path(".ai/cache/agent-coordination.json")
_LOCK_TIMEOUT_SECONDS = 3.0
_LOCK_STALE_SECONDS = 30.0


def coordinate_agents(
    project_root: Path,
    action: str,
    *,
    task_id: str = "",
    agent_id: str = "",
    title: str = "",
    paths: list[str] | None = None,
    dependencies: list[str] | None = None,
    lease_seconds: int = 900,
) -> Report:
    root = project_root.resolve()
    report = Report(command=f"agents {action}", project_root=root)
    error = _validate_inputs(action, task_id, agent_id, title, paths or [], lease_seconds)
    if error is not None:
        report.status = "invalid_configuration"
        report.summary = error
        return report
    try:
        with _state_lock(root):
            state = _load_state(root)
            expired = _expire_claims(state)
            outcome = _apply_action(
                state,
                action,
                task_id=task_id,
                agent_id=agent_id,
                title=title,
                paths=paths or [],
                dependencies=dependencies or [],
                lease_seconds=lease_seconds,
            )
            if expired or outcome.get("write"):
                _write_state(root, state)
    except TimeoutError:
        report.status = "blocked"
        report.summary = {"reason_code": "COORDINATION_LOCK_TIMEOUT"}
        return report
    report.status = cast(Status, outcome.pop("status", "success"))
    outcome.pop("write", None)
    report.summary = {
        **outcome,
        "schema_version": SCHEMA_VERSION,
        "expired_claims_pruned": expired,
        "tasks": _task_list(state),
        "active_claims": _active_claims(state),
    }
    report.artifacts.append(
        Artifact(str(root / STATE_PATH), "coordination", "Local agent task state")
    )
    return report


def _apply_action(
    state: dict[str, object],
    action: str,
    *,
    task_id: str,
    agent_id: str,
    title: str,
    paths: list[str],
    dependencies: list[str],
    lease_seconds: int,
) -> dict[str, object]:
    tasks = _tasks(state)
    if action == "status":
        return {"status": "success", "reason_code": "COORDINATION_STATUS"}
    if action == "add":
        if task_id in tasks:
            return {"status": "blocked", "reason_code": "TASK_ALREADY_EXISTS", "task_id": task_id}
        missing = sorted(item for item in dependencies if item not in tasks)
        if missing:
            return {"status": "blocked", "reason_code": "DEPENDENCY_NOT_FOUND", "missing": missing}
        tasks[task_id] = {
            "id": task_id,
            "title": mask_text(title),
            "paths": _normalized_paths(paths),
            "dependencies": sorted(set(dependencies)),
            "state": "queued",
            "claim": None,
            "created_at": _now().isoformat(),
            "completed_at": None,
        }
        return {"status": "success", "write": True, "reason_code": "TASK_ADDED", "task_id": task_id}
    task = tasks.get(task_id)
    if not isinstance(task, dict):
        return {"status": "blocked", "reason_code": "TASK_NOT_FOUND", "task_id": task_id}
    if action == "claim":
        return _claim(tasks, task, task_id, agent_id, lease_seconds)
    claim = task.get("claim")
    if not isinstance(claim, dict) or claim.get("agent_id") != agent_id:
        return {"status": "blocked", "reason_code": "CLAIM_NOT_OWNED", "task_id": task_id}
    if action == "heartbeat":
        claim["expires_at"] = (_now() + timedelta(seconds=lease_seconds)).isoformat()
        claim["heartbeat_at"] = _now().isoformat()
        return {
            "status": "success",
            "write": True,
            "reason_code": "LEASE_RENEWED",
            "task_id": task_id,
        }
    if action == "release":
        task["claim"] = None
        task["state"] = "queued"
        return {
            "status": "success",
            "write": True,
            "reason_code": "TASK_RELEASED",
            "task_id": task_id,
        }
    task["claim"] = None
    task["state"] = "completed"
    task["completed_at"] = _now().isoformat()
    return {"status": "success", "write": True, "reason_code": "TASK_COMPLETED", "task_id": task_id}


def _claim(
    tasks: dict[str, object],
    task: dict[str, object],
    task_id: str,
    agent_id: str,
    lease_seconds: int,
) -> dict[str, object]:
    if task.get("state") == "completed":
        return {"status": "blocked", "reason_code": "TASK_ALREADY_COMPLETED", "task_id": task_id}
    dependencies = _string_list(task.get("dependencies"))
    incomplete: list[str] = []
    for item in dependencies:
        dependency = tasks.get(item)
        if not isinstance(dependency, dict) or dependency.get("state") != "completed":
            incomplete.append(item)
    if incomplete:
        return {
            "status": "blocked",
            "reason_code": "DEPENDENCIES_INCOMPLETE",
            "dependencies": incomplete,
        }
    existing = task.get("claim")
    if isinstance(existing, dict) and existing.get("agent_id") != agent_id:
        return {
            "status": "blocked",
            "reason_code": "TASK_CLAIMED",
            "owner": existing.get("agent_id"),
        }
    conflicts = _path_conflicts(tasks, task_id, _string_list(task.get("paths")))
    if conflicts:
        return {"status": "blocked", "reason_code": "PATH_CONFLICT", "conflicts": conflicts}
    now = _now()
    task["state"] = "claimed"
    task["claim"] = {
        "agent_id": agent_id,
        "claimed_at": now.isoformat(),
        "heartbeat_at": now.isoformat(),
        "expires_at": (now + timedelta(seconds=lease_seconds)).isoformat(),
    }
    return {"status": "success", "write": True, "reason_code": "TASK_CLAIMED", "task_id": task_id}


def _path_conflicts(
    tasks: dict[str, object], task_id: str, paths: list[str]
) -> list[dict[str, str]]:
    conflicts: list[dict[str, str]] = []
    for other_id, value in tasks.items():
        if other_id == task_id or not isinstance(value, dict) or value.get("state") != "claimed":
            continue
        for left in paths:
            for right in _string_list(value.get("paths")):
                if _paths_overlap(left, right):
                    claim = value.get("claim")
                    owner = claim.get("agent_id", "") if isinstance(claim, dict) else ""
                    conflicts.append({"task_id": other_id, "agent_id": str(owner), "path": right})
    return conflicts


def _paths_overlap(left: str, right: str) -> bool:
    return (
        left == right
        or left.startswith(right.rstrip("/") + "/")
        or right.startswith(left.rstrip("/") + "/")
    )


def _expire_claims(state: dict[str, object]) -> int:
    expired = 0
    now = _now()
    for task in _tasks(state).values():
        if not isinstance(task, dict) or task.get("state") != "claimed":
            continue
        claim = task.get("claim")
        if not isinstance(claim, dict):
            continue
        try:
            expiry = datetime.fromisoformat(str(claim.get("expires_at")))
        except ValueError:
            expiry = now
        if expiry <= now:
            task["claim"] = None
            task["state"] = "queued"
            expired += 1
    return expired


def _task_list(state: dict[str, object]) -> list[dict[str, object]]:
    return [value for _, value in sorted(_tasks(state).items()) if isinstance(value, dict)]


def _active_claims(state: dict[str, object]) -> list[dict[str, object]]:
    return [task for task in _task_list(state) if task.get("state") == "claimed"]


def _tasks(state: dict[str, object]) -> dict[str, object]:
    tasks = state.setdefault("tasks", {})
    if not isinstance(tasks, dict):
        tasks = {}
        state["tasks"] = tasks
    return tasks


def _load_state(root: Path) -> dict[str, object]:
    path = root / STATE_PATH
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"schema_version": SCHEMA_VERSION, "tasks": {}}
    if not isinstance(value, dict) or value.get("schema_version") != SCHEMA_VERSION:
        return {"schema_version": SCHEMA_VERSION, "tasks": {}}
    return value


def _write_state(root: Path, state: dict[str, object]) -> None:
    path = root / STATE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f".{os.getpid()}.tmp")
    temporary.write_text(
        mask_text(json.dumps(state, indent=2, sort_keys=True) + "\n"), encoding="utf-8"
    )
    os.replace(temporary, path)


@contextmanager
def _state_lock(root: Path) -> Iterator[None]:
    lock = root / STATE_PATH.with_suffix(".lock")
    lock.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + _LOCK_TIMEOUT_SECONDS
    while True:
        try:
            descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(descriptor)
            break
        except FileExistsError:
            try:
                if time.time() - lock.stat().st_mtime > _LOCK_STALE_SECONDS:
                    lock.unlink()
                    continue
            except OSError:
                pass
            if time.monotonic() >= deadline:
                raise TimeoutError from None
            time.sleep(0.02)
    try:
        yield
    finally:
        with suppress(OSError):
            lock.unlink()


def _validate_inputs(
    action: str, task_id: str, agent_id: str, title: str, paths: list[str], lease_seconds: int
) -> dict[str, object] | None:
    if action not in {"status", "add", "claim", "heartbeat", "release", "complete"}:
        return {"reason_code": "INVALID_COORDINATION_ACTION"}
    if action != "status" and (not task_id or len(task_id) > 100):
        return {"reason_code": "INVALID_TASK_ID"}
    if action == "add" and (
        not title.strip() or not paths or any(not item.strip() for item in paths)
    ):
        return {"reason_code": "TASK_TITLE_AND_PATHS_REQUIRED"}
    if action in {"claim", "heartbeat", "release", "complete"} and not agent_id:
        return {"reason_code": "AGENT_ID_REQUIRED"}
    if not 30 <= lease_seconds <= 86400:
        return {"reason_code": "INVALID_LEASE_SECONDS"}
    if any(Path(item).is_absolute() or ".." in Path(item).parts for item in paths):
        return {"reason_code": "INVALID_TASK_PATH"}
    return None


def _normalized_paths(paths: list[str]) -> list[str]:
    return sorted({Path(item).as_posix().strip("/") for item in paths if item.strip()})


def _string_list(value: object) -> list[str]:
    return [str(item) for item in value] if isinstance(value, list) else []


def _now() -> datetime:
    return datetime.now(UTC)
