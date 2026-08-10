from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from typing import Any

from ai_dev_tools.models.report import Artifact, Report
from ai_dev_tools.reporters.writer import write_json, write_markdown
from ai_dev_tools.runners.check_models import CheckTask
from ai_dev_tools.utils.subprocess import CommandResult

HISTORY_SCHEMA = "1.0"
HISTORY_PATH = Path(".ai/cache/flaky-tests.json")
_HISTORY_LOCK = Lock()
_DETERMINISTIC_MARKERS = (
    "syntaxerror",
    "syntax error",
    "compilation failed",
    "compiler error",
    "modulenotfounderror",
    "importerror",
    "configuration error",
    "config error",
    "collection error",
    "failed to collect",
)


def eligible_for_retry(task: CheckTask, result: CommandResult) -> bool:
    if task.category not in {"unit_tests", "integration_tests"}:
        return False
    if result.timed_out or result.exit_code in {0, 2, 126, 127}:
        return False
    output = result.combined_output.lower()
    return not any(marker in output for marker in _DETERMINISTIC_MARKERS)


def record_result(
    root: Path,
    task: CheckTask,
    fingerprint: str,
    result: CommandResult,
) -> Path:
    with _HISTORY_LOCK:
        return _record_result_unlocked(root, task, fingerprint, result)


def _record_result_unlocked(
    root: Path,
    task: CheckTask,
    fingerprint: str,
    result: CommandResult,
) -> Path:
    path = root / HISTORY_PATH
    history = _load_history(path)
    entries = history.setdefault("entries", {})
    if not isinstance(entries, dict):
        entries = {}
    entries = {
        str(key): value for key, value in entries.items() if isinstance(value, dict)
    }
    history["entries"] = entries
    key = _entry_key(task, fingerprint)
    current = entries.get(key, {})
    if not isinstance(current, dict):
        current = {}
    outcomes = current.get("outcomes", [])
    if not isinstance(outcomes, list):
        outcomes = []
    outcome = "flaky" if result.flaky else "pass" if result.exit_code == 0 else "fail"
    outcomes = [*outcomes[-19:], outcome]
    entries[key] = {
        "name": task.name,
        "workspace": task.workspace,
        "category": task.category,
        "command": task.command,
        "fingerprint": fingerprint,
        "outcomes": outcomes,
        "flaky_occurrences": sum(item == "flaky" for item in outcomes),
        "alternating": len(set(outcomes)) > 1,
        "last_outcome": outcome,
        "last_duration_seconds": result.duration_seconds,
        "last_attempts": result.attempts,
        "last_seen_at": datetime.now(UTC).isoformat(),
        "initial_exit_code": result.initial_exit_code,
    }
    if len(entries) > 200:
        oldest = sorted(
            entries,
            key=lambda item: str(entries[item].get("last_seen_at", "")),
        )
        for stale_key in oldest[:-200]:
            del entries[stale_key]
    history["schema_version"] = HISTORY_SCHEMA
    history["updated_at"] = datetime.now(UTC).isoformat()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(history, indent=2, sort_keys=True) + chr(10), encoding="utf-8")
    os.replace(temporary, path)
    return path


def run_flaky_report(project_root: Path) -> Report:
    root = project_root.resolve()
    path = root / HISTORY_PATH
    history = _load_history(path)
    entries = history.get("entries", {})
    if not isinstance(entries, dict):
        entries = {}
    rows = [
        value
        for value in entries.values()
        if isinstance(value, dict)
        and (
            _safe_int(value.get("flaky_occurrences")) > 0
            or bool(value.get("alternating"))
        )
    ]
    rows.sort(key=lambda item: (str(item.get("workspace", "")), str(item.get("name", ""))))
    report = Report(command="test flaky", project_root=root)
    report.status = "warning" if rows else "success"
    report.summary = {
        "known_flaky": len(rows),
        "tests": rows,
        "history_path": str(path),
        "local_only": True,
    }
    if path.exists():
        report.artifacts.append(Artifact(str(path), "flaky-history", "Local flaky test history"))
    report.finish()
    output = root / ".ai" / "reports" / "tests-flaky.json"
    write_json(report, output)
    write_markdown(report, output.with_suffix(".md"))
    return report


def _safe_int(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _entry_key(task: CheckTask, fingerprint: str) -> str:
    value = json.dumps(
        {
            "command": task.command,
            "workspace": task.workspace,
            "fingerprint": fingerprint,
        },
        sort_keys=True,
    )
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:20]


def _load_history(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"schema_version": HISTORY_SCHEMA, "entries": {}}
    if not isinstance(value, dict) or value.get("schema_version") != HISTORY_SCHEMA:
        return {"schema_version": HISTORY_SCHEMA, "entries": {}}
    return value