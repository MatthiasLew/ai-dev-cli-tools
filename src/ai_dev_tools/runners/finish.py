from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from ai_dev_tools.config import load_settings
from ai_dev_tools.git.inspect import inspect_git
from ai_dev_tools.models.report import Report
from ai_dev_tools.reporters.writer import write_json, write_markdown
from ai_dev_tools.runners.check import run_check
from ai_dev_tools.security.secrets import scan_paths_for_secrets

UNSAFE_REPO_STATES = {"CONFLICT", "DETACHED_HEAD", "DIVERGED"}


def run_finish(project_root: Path) -> Report:
    settings = load_settings(project_root)
    git_report = inspect_git(settings.project_root, detailed=True)
    changed = [str(path) for path in git_report.summary.get("changed_files", [])]
    check_report = run_check(settings.project_root, mode="changed")
    findings = scan_paths_for_secrets(
        settings.project_root, [settings.project_root / path for path in changed]
    )
    blocking_reasons = _blocking_reasons(git_report, check_report, findings, changed)
    ready = not blocking_reasons
    report = Report(
        command="finish",
        project_root=settings.project_root,
        status="success" if ready else "failed",
    )
    report.summary = {
        "ready_to_commit": ready,
        "blocking_reasons": blocking_reasons,
        "blocking_reason_codes": [_blocking_reason_code(reason) for reason in blocking_reasons],
        "changed": _classify_changed(changed),
        "validation": {
            "checks": check_report.status,
            "secrets": "none" if not findings else f"{len(findings)} finding(s)",
        },
        "secret_findings": [finding.masked_dict() for finding in findings],
        "reports": {
            "git": [artifact.path for artifact in git_report.artifacts],
            "check": [artifact.path for artifact in check_report.artifacts],
        },
    }
    report.finish()
    write_markdown(report, settings.reports_directory / "finish-latest.md")
    write_json(report, settings.reports_directory / "finish-latest.json")
    return report


def _blocking_reasons(
    git_report: Report,
    check_report: Report,
    findings: Sequence[object],
    changed: list[str],
) -> list[str]:
    reasons: list[str] = []
    states = set(str(item) for item in git_report.summary.get("states", []))
    conflicts = git_report.summary.get("conflicted_files", [])
    if not changed:
        reasons.append("no_changes")
    if conflicts:
        reasons.append("repository has merge conflicts")
    for state in sorted(states & UNSAFE_REPO_STATES):
        if state != "CONFLICT":
            reasons.append(f"repository state is {state}")
    if check_report.status == "failed":
        checks_failed = check_report.summary.get("checks_failed")
        if isinstance(checks_failed, int) and checks_failed:
            reasons.append(f"{checks_failed} check(s) failed")
        else:
            reasons.append("required checks failed")
    if findings:
        reasons.append(f"{len(findings)} potential secret(s) detected")
    return reasons


def _blocking_reason_code(reason: str) -> str:
    if reason == "no_changes":
        return "NO_CHANGES"
    if "merge conflicts" in reason:
        return "MERGE_CONFLICTS"
    if reason.startswith("repository state is "):
        return f"UNSAFE_REPOSITORY_{reason.rsplit(' ', 1)[-1]}"
    if "check" in reason and "failed" in reason:
        return "CHECKS_FAILED"
    if "secret" in reason:
        return "POTENTIAL_SECRETS"
    return "FINISH_BLOCKED"


def _classify_changed(paths: list[str]) -> dict[str, int]:
    result = {"production_files": 0, "test_files": 0, "documentation_files": 0, "other_files": 0}
    for path in paths:
        lower = path.lower()
        if lower.endswith((".md", ".rst", ".txt")) or lower.startswith("docs/"):
            result["documentation_files"] += 1
        elif "test" in lower:
            result["test_files"] += 1
        elif lower.endswith((".py", ".js", ".ts", ".java", ".rs", ".php")):
            result["production_files"] += 1
        else:
            result["other_files"] += 1
    return result
