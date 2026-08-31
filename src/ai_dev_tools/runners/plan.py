from __future__ import annotations

import hashlib
from pathlib import Path

from ai_dev_tools.config import load_settings
from ai_dev_tools.git.inspect import inspect_git
from ai_dev_tools.models.report import Report
from ai_dev_tools.reporters.writer import write_json, write_markdown
from ai_dev_tools.runners.check import run_check
from ai_dev_tools.security.execution import ExecutionPolicy, assess_command


def run_agent_plan(project_root: Path, task: str = "", mode: str = "changed") -> Report:
    root = project_root.resolve()
    report = Report(command=f"plan --mode {mode}", project_root=root)
    git_report = inspect_git(root, detailed=True, write_reports=False)
    check_report = run_check(root, mode=mode, explain=True, policy="feedback-first")

    all_changed_files = _strings(git_report.summary.get("changed_files"))
    all_changed_symbols = _dicts(git_report.summary.get("changed_symbols"))
    changed_files = all_changed_files[:30]
    changed_symbols = _compact_symbols(all_changed_symbols[:20])
    selected_checks = _dicts(check_report.summary.get("selected_checks"))
    command_assessments = _command_assessments(root, selected_checks)
    reason_paths = _reason_paths(check_report.summary.get("changed_analysis"))
    risks = [_risk_row(path, changed_symbols) for path in changed_files]
    highest_risk = max((item["level"] for item in risks), key=_risk_rank, default="low")
    actions = _actions(task, changed_files, changed_symbols, selected_checks)
    confidence = _confidence(check_report, changed_files)

    report.status = "partial" if not changed_files and not task else "success"
    report.summary = {
        "agent_plan_version": "1",
        "task": task,
        "mode": mode,
        "decision": {
            "ready_to_implement": bool(task or changed_files),
            "confidence": confidence,
            "highest_risk": highest_risk,
            "reason_code": "PLAN_READY" if task or changed_files else "PLAN_NEEDS_TASK",
        },
        "scope": {
            "files": changed_files,
            "symbols": changed_symbols,
            "risk": risks,
            "total_files": len(all_changed_files),
            "total_symbols": len(all_changed_symbols),
            "files_truncated": len(all_changed_files) > len(changed_files),
            "symbols_truncated": len(all_changed_symbols) > len(changed_symbols),
        },
        "next_actions": actions,
        "validation": {
            "checks": selected_checks,
            "commands": [item.get("command", []) for item in selected_checks],
            "command_assessments": command_assessments,
            "schedule": check_report.summary.get("schedule", {}),
        },
        "evidence": _evidence(changed_files, changed_symbols, reason_paths),
        "constraints": {
            "preview_only": True,
            "commands_executed": False,
            "bounded_files": 30,
            "bounded_symbols": 20,
            "bounded_evidence": 50,
        },
    }
    if not task and not changed_files:
        report.summary["message"] = "Provide --task or create a working-tree change to plan work."
    output = root / ".ai" / "reports" / "agent-plan"
    report.finish()
    write_json(report, output.with_suffix(".json"))
    write_markdown(report, output.with_suffix(".md"))
    return report


def _command_assessments(
    root: Path, checks: list[dict[str, object]]
) -> list[dict[str, object]]:
    configured = load_settings(root).execution
    policy = ExecutionPolicy(
        mode=configured.mode,
        allow_prefixes=tuple(configured.allow_prefixes),
        deny_prefixes=tuple(configured.deny_prefixes),
        maximum_impact=configured.maximum_impact,
    )
    rows: list[dict[str, object]] = []
    for check in checks:
        raw = check.get("command", [])
        command = [str(item) for item in raw] if isinstance(raw, list) else []
        rows.append(assess_command(command, root, policy).to_dict())
    return rows


def _actions(
    task: str,
    files: list[str],
    symbols: list[dict[str, object]],
    checks: list[dict[str, object]],
) -> list[dict[str, object]]:
    actions: list[dict[str, object]] = []
    if task:
        actions.append(
            {
                "id": "understand-task",
                "kind": "analysis",
                "description": task,
                "depends_on": [],
                "reason_code": "EXPLICIT_TASK",
            }
        )
    for path in files[:30]:
        names = [
            str(item.get("name"))
            for item in symbols
            if item.get("path") == path and item.get("name")
        ][:10]
        actions.append(
            {
                "id": f"inspect-{_stable_id(path)}",
                "kind": "inspect-or-edit",
                "path": path,
                "symbols": names,
                "depends_on": ["understand-task"] if task else [],
                "reason_code": "CHANGED_SCOPE",
            }
        )
    for index, check in enumerate(checks):
        actions.append(
            {
                "id": f"validate-{index + 1}",
                "kind": "validate",
                "description": str(check.get("name", "validation")),
                "command": check.get("command", []),
                "depends_on": [item["id"] for item in actions if item["kind"] == "inspect-or-edit"],
                "reason_code": "SELECTED_VALIDATION",
            }
        )
    return actions[:75]


def _risk_row(path: str, symbols: list[dict[str, object]]) -> dict[str, str]:
    lowered = path.lower()
    level = "high" if _is_high_risk(lowered) else "medium" if symbols else "low"
    symbol_risks = [
        str(item.get("risk"))
        for item in symbols
        if item.get("path") == path and item.get("risk")
    ]
    if "high" in symbol_risks:
        level = "high"
    if _is_high_risk(lowered):
        reason = "configuration-or-lockfile"
    else:
        reason = "symbol-change" if symbol_risks else "file-change"
    return {"path": path, "level": level, "reason": reason}


def _is_high_risk(path: str) -> bool:
    name = Path(path).name
    return name in {
        "pyproject.toml",
        "package.json",
        "package-lock.json",
        "pnpm-lock.yaml",
        "yarn.lock",
        "cargo.toml",
        "cargo.lock",
        "pom.xml",
        "build.gradle",
        "composer.json",
    } or path.startswith(".github/workflows/")


def _evidence(
    files: list[str], symbols: list[dict[str, object]], reason_paths: list[dict[str, object]]
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for path in files[:30]:
        rows.append(
            {
                "id": f"file-{_stable_id(path)}",
                "kind": "changed-file",
                "path": path,
                "expand": f'ai-dev explain --symbol "{path}#<symbol>" --json',
            }
        )
    for item in symbols[:20]:
        path = str(item.get("path", ""))
        name = str(item.get("name", ""))
        if path and name:
            rows.append(
                {
                    "id": f"symbol-{_stable_id(path + '#' + name)}",
                    "kind": "changed-symbol",
                    "path": path,
                    "symbol": name,
                    "expand": f'ai-dev explain --symbol "{path}#{name}" --json',
                }
            )
    rows.extend(reason_paths[:10])
    return rows[:50]


def _reason_paths(value: object) -> list[dict[str, object]]:
    if not isinstance(value, dict):
        return []
    return _dicts(value.get("reason_paths"))


def _confidence(check_report: Report, files: list[str]) -> str:
    analysis = check_report.summary.get("changed_analysis")
    if isinstance(analysis, dict) and analysis.get("confidence") in {"low", "medium", "high"}:
        return str(analysis["confidence"])
    return "medium" if files else "low"


def _risk_rank(value: str) -> int:
    return {"low": 0, "medium": 1, "high": 2}.get(value, 0)


def _stable_id(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


def _strings(value: object) -> list[str]:
    return [str(item) for item in value] if isinstance(value, list) else []


def _dicts(value: object) -> list[dict[str, object]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _compact_symbols(symbols: list[dict[str, object]]) -> list[dict[str, object]]:
    allowed = {"path", "name", "kind", "risk", "change_type", "reason_code"}
    return [
        {str(key): value for key, value in symbol.items() if key in allowed}
        for symbol in symbols
    ]
