from __future__ import annotations

import json
import os
import time
from pathlib import Path

from ai_dev_tools.cache.repository import update_repository_index
from ai_dev_tools.models.report import Artifact, Report

STATE_PATH = Path(".ai/cache/index-daemon.json")


def run_index_daemon(
    project_root: Path,
    *,
    poll_ms: int = 500,
    max_updates: int = 0,
    idle_timeout_seconds: int = 0,
) -> Report:
    root = project_root.resolve()
    report = Report(command="index daemon", project_root=root)
    if poll_ms < 50 or max_updates < 0 or idle_timeout_seconds < 0:
        report.status = "invalid_configuration"
        report.summary = {"reason_code": "INVALID_INDEX_DAEMON_OPTIONS"}
        return report
    state_path = root / STATE_PATH
    updates = 0
    started = time.monotonic()
    last_change = started
    index = update_repository_index(root)
    fingerprint = _fingerprint(index)
    updates += 1
    _write_state(state_path, "running", updates, poll_ms)
    try:
        while not max_updates or updates < max_updates:
            if idle_timeout_seconds and time.monotonic() - last_change >= idle_timeout_seconds:
                break
            time.sleep(poll_ms / 1000)
            candidate = update_repository_index(root)
            next_fingerprint = _fingerprint(candidate)
            if next_fingerprint == fingerprint:
                continue
            fingerprint = next_fingerprint
            updates += 1
            last_change = time.monotonic()
            _write_state(state_path, "running", updates, poll_ms)
    except KeyboardInterrupt:
        report.status = "partial"
    finally:
        _write_state(state_path, "stopped", updates, poll_ms)
    report.summary = {
        "daemon_protocol_version": "1",
        "foreground": True,
        "updates": updates,
        "poll_ms": poll_ms,
        "idle_timeout_seconds": idle_timeout_seconds,
        "duration_seconds": round(time.monotonic() - started, 3),
        "state_path": str(state_path),
        "reason_code": "INDEX_DAEMON_STOPPED",
    }
    report.artifacts.append(Artifact(str(state_path), "daemon-state", "Index daemon state"))
    return report


def _fingerprint(index: dict[str, object]) -> tuple[tuple[str, str], ...]:
    entries = index.get("entries", [])
    if not isinstance(entries, list):
        return ()
    return tuple(
        (str(item.get("path")), str(item.get("sha256")))
        for item in entries
        if isinstance(item, dict)
    )


def _write_state(path: Path, status: str, updates: int, poll_ms: int) -> None:
    payload = {
        "schema_version": "1",
        "pid": os.getpid(),
        "status": status,
        "updates": updates,
        "poll_ms": poll_ms,
        "local_only": True,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)
