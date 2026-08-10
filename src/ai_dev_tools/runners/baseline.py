from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ai_dev_tools.models.report import Artifact, Report

BASELINE_SCHEMA_VERSION = "1"
_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


def run_baseline(project_root: Path, action: str, name: str | None = None) -> Report:
    root = project_root.resolve()
    report = Report(command=f"baseline {action}" + (f" {name}" if name else ""), project_root=root)
    directory = root / ".ai" / "cache" / "baselines"
    if action == "list":
        names = sorted(path.stem for path in directory.glob("*.json"))
        report.summary = {"baselines": names, "count": len(names)}
        return report
    if not name or not _SAFE_NAME.fullmatch(name):
        report.status = "failed"
        report.exit_code = 2
        report.summary = {
            "message": "Baseline name must use 1-64 letters, digits, dots, dashes, or underscores.",
            "reason_code": "INVALID_BASELINE_NAME",
        }
        return report
    path = directory / f"{name}.json"
    if action == "create":
        snapshot = _snapshot(root, name)
        directory.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(snapshot, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        report.summary = {
            "name": name,
            "reports": len(snapshot["reports"]),
            "failures": len(_all_failures(snapshot)),
            "created_at": snapshot["created_at"],
        }
        report.artifacts.append(Artifact(str(path), "baseline", "Local report baseline"))
        return report
    if action == "compare":
        baseline = _load_baseline(path)
        if baseline is None:
            report.status = "failed"
            report.exit_code = 1
            report.summary = {
                "message": f"Baseline does not exist or is invalid: {name}",
                "reason_code": "BASELINE_NOT_FOUND",
            }
            return report
        current = _snapshot(root, name)
        report.summary = _compare(baseline, current)
        report.summary["name"] = name
        report.summary["baseline_created_at"] = baseline.get("created_at")
        report.summary["ready"] = not (
            report.summary["new_failures"] or report.summary["status_regressions"]
        )
        report.status = "success" if report.summary["ready"] else "failed"
        return report
    raise ValueError(f"Unsupported baseline action: {action}")


def _snapshot(root: Path, name: str) -> dict[str, Any]:
    reports: dict[str, dict[str, object]] = {}
    paths = [
        *sorted((root / ".ai" / "reports").glob("*latest.json")),
        *sorted((root / ".ai" / "context").glob("*latest.json")),
    ]
    for path in paths:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        command = payload.get("command")
        if not isinstance(command, str):
            continue
        reports[command] = {
            "status": payload.get("status"),
            "failures": sorted(_failure_signatures(payload)),
            "issue_codes": sorted(_issue_codes(payload)),
            "source": str(path.relative_to(root)),
        }
    return {
        "schema_version": BASELINE_SCHEMA_VERSION,
        "name": name,
        "created_at": datetime.now(UTC).isoformat(),
        "reports": reports,
    }


def _compare(baseline: dict[str, Any], current: dict[str, Any]) -> dict[str, object]:
    old_reports = _report_map(baseline)
    new_reports = _report_map(current)
    old_failures = _all_failures(baseline)
    new_failures = _all_failures(current)
    changed_statuses = [
        {
            "command": command,
            "baseline": old_reports[command].get("status"),
            "current": new_reports[command].get("status"),
        }
        for command in sorted(old_reports.keys() & new_reports.keys())
        if old_reports[command].get("status") != new_reports[command].get("status")
    ]
    old_issues = _all_report_values(baseline, "issue_codes")
    new_issues = _all_report_values(current, "issue_codes")
    status_regressions = [
        item
        for item in changed_statuses
        if item["current"] in {"failed", "blocked", "environment_error"}
    ]
    unchanged = sum(
        old_reports[command] == new_reports[command]
        for command in old_reports.keys() & new_reports.keys()
    )
    return {
        "new_failures": sorted(new_failures - old_failures),
        "resolved_failures": sorted(old_failures - new_failures),
        "new_issue_codes": sorted(new_issues - old_issues),
        "resolved_issue_codes": sorted(old_issues - new_issues),
        "changed_statuses": changed_statuses,
        "status_regressions": status_regressions,
        "new_reports": sorted(new_reports.keys() - old_reports.keys()),
        "missing_reports": sorted(old_reports.keys() - new_reports.keys()),
        "unchanged_reports": unchanged,
        "baseline_report_count": len(old_reports),
        "current_report_count": len(new_reports),
    }


def _load_baseline(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict) or payload.get("schema_version") != BASELINE_SCHEMA_VERSION:
        return None
    return payload


def _report_map(snapshot: dict[str, Any]) -> dict[str, dict[str, object]]:
    reports = snapshot.get("reports")
    if not isinstance(reports, dict):
        return {}
    return {str(command): value for command, value in reports.items() if isinstance(value, dict)}


def _all_report_values(snapshot: dict[str, Any], key: str) -> set[str]:
    values: set[str] = set()
    for command, report in _report_map(snapshot).items():
        entries = report.get(key)
        if isinstance(entries, list):
            values.update(f"{command}:{entry}" for entry in entries if isinstance(entry, str))
    return values


def _all_failures(snapshot: dict[str, Any]) -> set[str]:
    failures: set[str] = set()
    for command, report in _report_map(snapshot).items():
        values = report.get("failures")
        if isinstance(values, list):
            failures.update(f"{command}:{value}" for value in values if isinstance(value, str))
    return failures


def _failure_signatures(value: object) -> set[str]:
    result: set[str] = set()
    if isinstance(value, dict):
        for key, child in value.items():
            if key in {"failure_signature", "signature"} and isinstance(child, str) and child:
                result.add(child)
            else:
                result.update(_failure_signatures(child))
    elif isinstance(value, list):
        for child in value:
            result.update(_failure_signatures(child))
    return result


def _issue_codes(payload: dict[str, object]) -> set[str]:
    result: set[str] = set()
    issues = payload.get("issues")
    if isinstance(issues, list):
        for issue in issues:
            if isinstance(issue, dict) and isinstance(issue.get("code"), str):
                result.add(str(issue["code"]))
    return result
