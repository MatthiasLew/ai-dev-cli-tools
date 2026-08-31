from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path

from ai_dev_tools.config import load_settings
from ai_dev_tools.context import ContextOptions, build_context
from ai_dev_tools.git.inspect import inspect_git
from ai_dev_tools.models.report import Artifact, Report
from ai_dev_tools.runners.check import run_check
from ai_dev_tools.runners.observations import update_observation_lifecycle
from ai_dev_tools.security.secrets import mask_text

SESSION_SCHEMA_VERSION = "1"


@dataclass(frozen=True, slots=True)
class FeedbackOptions:
    task: str = ""
    explain: bool = False
    jobs: int = 4


def run_feedback(project_root: Path, options: FeedbackOptions) -> Report:
    settings = load_settings(project_root)
    root = settings.project_root
    report = Report(command="feedback", project_root=root)
    timings: dict[str, float] = {}

    started = time.monotonic()
    git_report = inspect_git(root, detailed=True)
    timings["git_inspect"] = _elapsed(started)

    started = time.monotonic()
    check_report = run_check(
        root,
        mode="changed",
        explain=options.explain,
        jobs=options.jobs,
        policy="feedback-first",
        resume=True,
    )
    timings["validation"] = _elapsed(started)

    started = time.monotonic()
    context_report = build_context(
        root,
        ContextOptions(
            task=options.task,
            profile="minimal",
            incremental=not options.explain,
            explain=options.explain,
            adaptive=True,
        ),
    )
    timings["context"] = _elapsed(started)

    changed = [str(item) for item in git_report.summary.get("changed_files", [])]
    failures = _failure_signatures(check_report)
    blocking_codes = [
        str(issue.code or "VALIDATION_FAILED")
        for issue in check_report.issues
        if issue.severity in {"error", "critical"}
    ]
    if check_report.status == "failed" and not blocking_codes:
        blocking_codes.append("VALIDATION_FAILED")
    warning_codes = sorted(
        {
            str(issue.code or "VALIDATION_WARNING")
            for issue in check_report.issues
            if issue.severity == "warning"
        }
    )
    ready = check_report.status in {"success", "partial"} and not blocking_codes
    observations, observations_path = update_observation_lifecycle(
        root,
        {
            "command": "feedback",
            "task": options.task,
            "status": check_report.status,
            "changed_files": changed,
            "failure_signatures": failures,
            "unresolved_warnings": warning_codes,
            "validation": {
                "checks_total": check_report.summary.get("checks_total", 0),
                "checks_failed": check_report.summary.get("checks_failed", 0),
                "first_failure": check_report.summary.get("first_failure"),
                "results": _compact_validation_results(check_report),
            },
            "context": {
                "selected_files": _selected_paths(context_report),
                "incremental": context_report.summary.get("incremental", {}),
                "retrieval": context_report.summary.get("retrieval", {}),
                "adaptive_context": context_report.summary.get("adaptive_context", {}),
            },
        },
    )
    report.status = "success" if ready else "failed"
    report.summary = {
        "agent_protocol_version": "1",
        "decision": {
            "ready": ready,
            "status": report.status,
            "confidence": _confidence(check_report),
            "blocking_reason_codes": sorted(set(blocking_codes)),
        },
        "changes": {
            "files": changed,
            "count": len(changed),
            "git_states": git_report.summary.get("states", []),
        },
        "validation": {
            "status": check_report.status,
            "checks_total": check_report.summary.get("checks_total", 0),
            "checks_failed": check_report.summary.get("checks_failed", 0),
            "first_failure": check_report.summary.get("first_failure"),
            "failure_signatures": failures,
            "results": check_report.summary.get("results", []),
            "execution": check_report.summary.get("execution", {}),
        },
        "context": {
            "status": context_report.status,
            "selected_files": context_report.summary.get("selected_files", []),
            "incremental": context_report.summary.get("incremental", {}),
            "budget": context_report.summary.get("budget", {}),
            "adaptive_context": context_report.summary.get("adaptive_context", {}),
        },
        "observations": observations,
        "performance": {
            "stages_seconds": timings,
            "total_seconds": round(sum(timings.values()), 3),
        },
        "expand": [
            {"kind": artifact.kind, "path": artifact.path}
            for artifact in [*check_report.artifacts, *context_report.artifacts]
        ],
    }
    session_path = _write_session(
        root,
        {
            "schema_version": SESSION_SCHEMA_VERSION,
            "task": options.task,
            "changed_files": changed,
            "validation_status": check_report.status,
            "failure_signatures": failures,
            "context_incremental": context_report.summary.get("incremental", {}),
            "performance": timings,
            "observations": observations,
        },
    )
    report.artifacts.append(Artifact(str(session_path), "session", "Local agent session state"))
    report.artifacts.append(
        Artifact(str(observations_path), "observations", "Observation lifecycle manifest")
    )
    report.artifacts.extend(_unique_artifacts([*check_report.artifacts, *context_report.artifacts]))
    return report


def run_session_status(project_root: Path) -> Report:
    root = project_root.resolve()
    report = Report(command="session status", project_root=root)
    try:
        payload = json.loads(_session_path(root).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        report.status = "partial"
        report.summary = {
            "message": "No valid local session state exists.",
            "reason_code": "SESSION_MISSING",
        }
        return report
    if not isinstance(payload, dict) or payload.get("schema_version") != SESSION_SCHEMA_VERSION:
        report.status = "partial"
        report.summary = {
            "message": "Local session state uses an unsupported schema.",
            "reason_code": "SESSION_SCHEMA_UNSUPPORTED",
        }
        return report
    report.summary = payload
    report.artifacts.append(
        Artifact(str(_session_path(root)), "session", "Local agent session state")
    )
    return report


def _failure_signatures(report: Report) -> list[str]:
    results = report.summary.get("results")
    if not isinstance(results, list):
        return []
    return sorted(
        {
            str(item["failure_signature"])
            for item in results
            if isinstance(item, dict) and item.get("failure_signature")
        }
    )


def _compact_validation_results(report: Report) -> list[dict[str, object]]:
    results = report.summary.get("results")
    if not isinstance(results, list):
        return []
    keep = {
        "name",
        "command",
        "workspace",
        "status",
        "exit_code",
        "failure_signature",
        "first_failure",
        "flaky",
        "reuse",
        "reason_code",
    }
    return [
        {key: item[key] for key in keep if key in item}
        for item in results
        if isinstance(item, dict)
    ]


def _selected_paths(report: Report) -> list[str]:
    selected = report.summary.get("selected_files")
    if not isinstance(selected, list):
        return []
    return sorted(
        str(item["path"])
        for item in selected
        if isinstance(item, dict) and isinstance(item.get("path"), str)
    )


def _confidence(report: Report) -> str:
    changed = report.summary.get("changed_analysis")
    if isinstance(changed, dict) and isinstance(changed.get("confidence"), str):
        return str(changed["confidence"])
    return "medium" if report.status == "partial" else "high"


def _write_session(root: Path, payload: dict[str, object]) -> Path:
    path = _session_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        mask_text(json.dumps(payload, indent=2, sort_keys=True) + "\n"), encoding="utf-8"
    )
    os.replace(temporary, path)
    return path


def _session_path(root: Path) -> Path:
    return root / ".ai" / "cache" / "session.json"


def _elapsed(started: float) -> float:
    return round(time.monotonic() - started, 3)


def _unique_artifacts(artifacts: list[Artifact]) -> list[Artifact]:
    unique: dict[tuple[str, str], Artifact] = {}
    for artifact in artifacts:
        unique[(artifact.path, artifact.kind)] = artifact
    return list(unique.values())
