from __future__ import annotations

import json
import os
import secrets
import subprocess
import sys
import time
from contextlib import suppress
from dataclasses import asdict, dataclass
from pathlib import Path

from ai_dev_tools.config import Settings, load_settings
from ai_dev_tools.models.report import Artifact, Issue, Report
from ai_dev_tools.reporters.writer import write_json, write_markdown
from ai_dev_tools.utils.subprocess import run_command, split_command


@dataclass(frozen=True, slots=True)
class RunOptions:
    explain: bool = False
    dry_run: bool = False
    foreground: bool = False
    timeout_seconds: int = 300


@dataclass(frozen=True, slots=True)
class RunPlan:
    command: list[str]
    source: str
    cwd: str = ""

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def run_application(project_root: Path, options: RunOptions) -> Report:
    settings = load_settings(project_root)
    report = Report(command="run", project_root=settings.project_root)
    plan = resolve_run_plan(settings)
    paths = _runtime_paths(settings.project_root)
    current = _read_json(paths["metadata"])
    if current.get("status") in {"running", "stopping"} and _heartbeat_is_fresh(current):
        report.status = "blocked"
        report.issues.append(
            Issue("error", "A managed project process is already running.", code="ALREADY_RUNNING")
        )
    elif plan is None:
        report.status = "blocked"
        report.issues.append(
            Issue(
                "error",
                "No safe run command detected. Configure [commands].run.",
                code="NO_RUN_COMMAND",
            )
        )
    elif options.explain or options.dry_run:
        report.summary = {
            "plan": plan.to_dict(),
            "explain": options.explain,
            "dry_run": options.dry_run,
            "modifications": "NONE",
        }
    elif options.foreground:
        result = run_command(
            plan.command,
            settings.project_root / plan.cwd,
            timeout_seconds=options.timeout_seconds,
        )
        report.status = "success" if result.exit_code == 0 else "failed"
        report.exit_code = result.exit_code
        paths["log"].parent.mkdir(parents=True, exist_ok=True)
        paths["log"].write_text(result.combined_output + "\n", encoding="utf-8")
        report.artifacts.append(Artifact(str(paths["log"]), "log", "Application output"))
        report.summary = {
            "plan": plan.to_dict(),
            "mode": "foreground",
            "exit_code": result.exit_code,
            "timed_out": result.timed_out,
        }
    else:
        token = secrets.token_urlsafe(24)
        _remove_stale_request(paths["request"])
        supervisor_command = [
            sys.executable,
            str(Path(__file__).with_name("supervisor.py")),
            "--metadata",
            str(paths["metadata"]),
            "--request",
            str(paths["request"]),
            "--token",
            token,
            "--cwd",
            str(settings.project_root / plan.cwd),
            "--log",
            str(paths["log"]),
            "--",
            *plan.command,
        ]
        _spawn_supervisor(supervisor_command, settings.project_root)
        state = _wait_for_state(paths["metadata"], {"running", "exited"}, 5.0)
        if state.get("status") != "running":
            report.status = "failed"
            report.issues.append(
                Issue("error", "Managed process failed to start.", code="START_FAILED")
            )
        else:
            report.status = "success"
        report.summary = {
            "plan": plan.to_dict(),
            "mode": "background",
            "status": state.get("status", "unknown"),
            "supervisor_pid": state.get("supervisor_pid"),
            "child_pid": state.get("child_pid"),
        }
        report.artifacts.extend(
            [
                Artifact(str(paths["log"]), "log", "Application output"),
                Artifact(str(paths["metadata"]), "runtime-state", "Managed process state"),
            ]
        )
    if not report.summary:
        report.summary = {
            "plan": plan.to_dict() if plan else None,
            "explain": options.explain,
            "dry_run": options.dry_run,
        }
    report.finish()
    write_markdown(report, settings.reports_directory / "run-latest.md")
    write_json(report, settings.reports_directory / "run-latest.json")
    return report


def stop_application(
    project_root: Path, *, explain: bool = False, timeout_seconds: int = 10
) -> Report:
    settings = load_settings(project_root)
    report = Report(command="stop", project_root=settings.project_root)
    paths = _runtime_paths(settings.project_root)
    state = _read_json(paths["metadata"])
    public_state = _public_state(state)
    if not state:
        report.status = "partial"
        report.summary = {"status": "not_running", "state": {}}
    elif state.get("status") not in {"running", "stopping"}:
        report.status = "partial"
        report.summary = {"status": "not_running", "state": public_state}
    elif not isinstance(state.get("token"), str):
        report.status = "blocked"
        report.issues.append(
            Issue(
                "error", "Runtime state has no valid control token.", code="INVALID_RUNTIME_STATE"
            )
        )
        report.summary = {"status": "unknown", "state": public_state}
    elif explain:
        report.summary = {
            "status": "would_request_stop",
            "state": public_state,
            "modifications": "NONE",
        }
    else:
        paths["request"].parent.mkdir(parents=True, exist_ok=True)
        paths["request"].write_text(str(state["token"]), encoding="utf-8")
        stopped = _wait_for_state(paths["metadata"], {"stopped", "exited"}, timeout_seconds)
        if stopped.get("status") not in {"stopped", "exited"}:
            report.status = "failed"
            report.issues.append(
                Issue(
                    "error",
                    "Supervisor did not acknowledge the stop request; no arbitrary PID was killed.",
                    code="STOP_TIMEOUT",
                )
            )
        else:
            report.status = "success"
        report.summary = {
            "status": stopped.get("status", "unknown"),
            "state": _public_state(stopped),
        }
    if paths["metadata"].exists():
        report.artifacts.append(
            Artifact(str(paths["metadata"]), "runtime-state", "Managed process state")
        )
    report.finish()
    write_markdown(report, settings.reports_directory / "stop-latest.md")
    write_json(report, settings.reports_directory / "stop-latest.json")
    return report


def resolve_run_plan(settings: Settings) -> RunPlan | None:
    configured = settings.commands.get("run")
    if configured:
        command = split_command(configured)
        return RunPlan(command, "configured") if command else None
    package_path = settings.project_root / "package.json"
    if package_path.exists():
        try:
            package = json.loads(package_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None
        scripts = package.get("scripts", {}) if isinstance(package, dict) else {}
        if isinstance(scripts, dict):
            for name in ("dev", "start", "serve"):
                if isinstance(scripts.get(name), str):
                    manager = _node_manager(settings.project_root)
                    return RunPlan([manager, "run", name], f"package.json#scripts.{name}")
    return None


def _node_manager(root: Path) -> str:
    if (root / "pnpm-lock.yaml").exists():
        return "pnpm"
    if (root / "yarn.lock").exists():
        return "yarn"
    return "npm"


def _spawn_supervisor(command: list[str], cwd: Path) -> None:
    flags = 0
    start_new_session = os.name != "nt"
    if os.name == "nt":
        flags = (
            getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            | getattr(subprocess, "DETACHED_PROCESS", 0)
            | getattr(subprocess, "CREATE_NO_WINDOW", 0)
        )
    subprocess.Popen(
        command,
        cwd=cwd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
        shell=False,
        start_new_session=start_new_session,
        creationflags=flags,
    )


def _runtime_paths(root: Path) -> dict[str, Path]:
    directory = root / ".ai" / "runtime"
    return {
        "metadata": directory / "process.json",
        "request": directory / "stop.request",
        "log": root / ".ai" / "logs" / "run-latest.log",
    }


def _wait_for_state(path: Path, statuses: set[str], timeout: float) -> dict[str, object]:
    deadline = time.monotonic() + max(timeout, 0)
    latest: dict[str, object] = {}
    while time.monotonic() <= deadline:
        latest = _read_json(path)
        if latest.get("status") in statuses:
            return latest
        pending = _read_json(path.with_suffix(path.suffix + ".tmp"))
        if pending.get("status") in statuses:
            return pending
        time.sleep(0.05)
    return latest


def _read_json(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _heartbeat_is_fresh(state: dict[str, object]) -> bool:
    heartbeat = state.get("heartbeat_at")
    if not isinstance(heartbeat, str):
        return False
    try:
        from datetime import datetime

        age = datetime.now().astimezone() - datetime.fromisoformat(heartbeat).astimezone()
        return age.total_seconds() < 5
    except ValueError:
        return False


def _public_state(state: dict[str, object]) -> dict[str, object]:
    return {key: value for key, value in state.items() if key != "token"}


def _remove_stale_request(path: Path) -> None:
    with suppress(FileNotFoundError):
        path.unlink()
