from __future__ import annotations

import json
import math
import platform
import re
import secrets
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ai_dev_tools import __version__
from ai_dev_tools.config import Settings, load_settings
from ai_dev_tools.models.report import Artifact, Issue, Report

PERFORMANCE_SCHEMA_VERSION = "1.0"


def record_performance(
    report: Report,
    operation: str,
    stages_seconds: dict[str, float],
    total_seconds: float,
    settings: Settings | None = None,
) -> Path:
    settings = settings or load_settings(report.project_root)
    stages = {
        key: round(value, 6)
        for key, value in sorted(stages_seconds.items())
        if _valid_number(value)
    }
    total = round(total_seconds if _valid_number(total_seconds) else 0.0, 6)
    violations = _budget_violations(operation, stages, total, settings.performance_budgets)
    directory = settings.project_root / ".ai" / "performance"
    runs = directory / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC)
    snapshot_id = secrets.token_hex(8)
    path = runs / (
        f"{_safe_name(operation)}-{timestamp.strftime('%Y%m%dT%H%M%S%fZ')}-{snapshot_id}.json"
    )
    payload: dict[str, Any] = {
        "schema_version": PERFORMANCE_SCHEMA_VERSION,
        "tool_version": __version__,
        "recorded_at": timestamp.isoformat(),
        "operation": operation,
        "command": report.command,
        "status": "warning" if violations and report.status == "success" else report.status,
        "total_seconds": total,
        "stages_seconds": stages,
        "budgets_seconds": dict(sorted(settings.performance_budgets.items())),
        "budget_violations": violations,
        "machine": {
            "implementation": platform.python_implementation().lower(),
            "platform": platform.platform(),
            "python": platform.python_version(),
        },
    }
    _write_json(path, payload)
    _write_json(directory / "latest.json", payload)
    _prune_runs(runs, settings.performance_retention)
    report.summary["performance"] = {
        "operation": operation,
        "total_seconds": total,
        "stages_seconds": stages,
        "budgets_seconds": payload["budgets_seconds"],
        "budget_violations": violations,
        "record": str(path),
    }
    report.artifacts.append(Artifact(str(path), "performance", "Local stage timings"))
    if violations:
        if report.status == "success":
            report.status = "warning"
        report.issues.append(
            Issue(
                "warning",
                "Performance budget exceeded for "
                + ", ".join(str(item["metric"]) for item in violations)
                + ".",
                code="PERFORMANCE_BUDGET_EXCEEDED",
            )
        )
    return path


def run_performance_latest(project_root: Path) -> Report:
    root = project_root.resolve()
    report = Report(command="performance latest", project_root=root)
    path = root / ".ai" / "performance" / "latest.json"
    try:
        payload = _load_record(root, path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        report.status = "partial"
        report.summary = {"reason_code": "PERFORMANCE_RECORD_MISSING", "message": str(exc)}
        return report.finish()
    report.summary = payload
    report.artifacts.append(Artifact(str(path), "performance", "Latest local stage timings"))
    if payload.get("budget_violations"):
        report.status = "warning"
        report.issues.append(
            Issue(
                "warning",
                "The latest run exceeded one or more configured performance budgets.",
                code="PERFORMANCE_BUDGET_EXCEEDED",
            )
        )
    return report.finish()


def compare_performance(project_root: Path, baseline: Path, candidate: Path) -> Report:
    root = project_root.resolve()
    report = Report(command="performance compare", project_root=root)
    try:
        left = _load_record(root, baseline)
        right = _load_record(root, candidate)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        report.status = "invalid_configuration"
        report.summary = {"reason_code": "INVALID_PERFORMANCE_RECORD", "message": str(exc)}
        return report.finish()
    if left["operation"] != right["operation"]:
        report.status = "invalid_configuration"
        report.summary = {
            "reason_code": "INCOMPARABLE_PERFORMANCE_RECORDS",
            "baseline_operation": left["operation"],
            "candidate_operation": right["operation"],
        }
        return report.finish()
    left_stages = _number_dict(left.get("stages_seconds"))
    right_stages = _number_dict(right.get("stages_seconds"))
    common = sorted(left_stages.keys() & right_stages.keys())
    total_metric = _comparison(float(left["total_seconds"]), float(right["total_seconds"]))
    metrics = {
        "total_seconds": total_metric,
        "stages_seconds": {
            name: _comparison(left_stages[name], right_stages[name]) for name in common
        },
    }
    violations = right.get("budget_violations", [])
    total_change = total_metric["percent_change"]
    report.status = "warning" if violations else "success"
    report.summary = {
        "operation": left["operation"],
        "baseline": str(_resolve_record(root, baseline)),
        "candidate": str(_resolve_record(root, candidate)),
        "metrics": metrics,
        "candidate_budget_violations": violations,
        "decision": (
            "budget_exceeded"
            if violations
            else "review_regression"
            if total_change is not None and total_change > 10
            else "within_budget"
        ),
    }
    if violations:
        report.issues.append(
            Issue(
                "warning",
                "Candidate exceeded one or more configured performance budgets.",
                code="PERFORMANCE_BUDGET_EXCEEDED",
            )
        )
    return report.finish()


def _budget_violations(
    operation: str, stages: dict[str, float], total: float, budgets: dict[str, float]
) -> list[dict[str, float | str]]:
    measured = {operation: total} | {
        f"{operation}.{stage}": value for stage, value in stages.items()
    }
    return [
        {
            "metric": metric,
            "measured_seconds": measured[metric],
            "budget_seconds": budget,
            "over_seconds": round(measured[metric] - budget, 6),
        }
        for metric, budget in sorted(budgets.items())
        if metric in measured and measured[metric] > budget
    ]


def _load_record(root: Path, path: Path) -> dict[str, Any]:
    resolved = _resolve_record(root, path)
    payload = json.loads(resolved.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema_version") != PERFORMANCE_SCHEMA_VERSION:
        raise ValueError(f"Unsupported performance record: {resolved}")
    if not isinstance(payload.get("operation"), str) or not _valid_number(
        payload.get("total_seconds")
    ):
        raise ValueError(f"Invalid performance record: {resolved}")
    return payload


def _resolve_record(root: Path, path: Path) -> Path:
    resolved = (path if path.is_absolute() else root / path).resolve()
    if resolved != root and root not in resolved.parents:
        raise ValueError("Performance record must stay inside the project")
    return resolved


def _comparison(baseline: float, candidate: float) -> dict[str, float | None]:
    return {
        "baseline": round(baseline, 6),
        "candidate": round(candidate, 6),
        "absolute_change": round(candidate - baseline, 6),
        "percent_change": (
            round(((candidate - baseline) / baseline) * 100, 2) if baseline else None
        ),
    }


def _number_dict(value: object) -> dict[str, float]:
    if not isinstance(value, dict):
        return {}
    return {
        str(key): float(item)
        for key, item in value.items()
        if isinstance(key, str) and _valid_number(item)
    }


def _valid_number(value: object) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and value >= 0
    )


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def _prune_runs(directory: Path, retention: int) -> None:
    files = sorted(directory.glob("*.json"), key=lambda path: path.stat().st_mtime, reverse=True)
    for path in files[max(retention, 1) :]:
        path.unlink(missing_ok=True)


def _safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip("-") or "performance"
