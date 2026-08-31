from __future__ import annotations

from pathlib import Path

from ai_dev_tools.config import load_settings
from ai_dev_tools.models.report import Report
from ai_dev_tools.security.execution import ExecutionPolicy, assess_command


def run_policy_assess(project_root: Path, command: list[str]) -> Report:
    settings = load_settings(project_root)
    configured = settings.execution
    policy = ExecutionPolicy(
        mode=configured.mode,
        allow_prefixes=tuple(configured.allow_prefixes),
        deny_prefixes=tuple(configured.deny_prefixes),
        maximum_impact=configured.maximum_impact,
    )
    assessment = assess_command(command, settings.project_root, policy)
    report = Report(command="policy assess", project_root=settings.project_root)
    report.status = "success" if assessment.allowed else "blocked"
    report.summary = {
        "policy": {
            "mode": policy.mode,
            "maximum_impact": policy.maximum_impact,
            "allow_prefixes": list(policy.allow_prefixes),
            "deny_prefixes": list(policy.deny_prefixes),
        },
        "assessment": assessment.to_dict(),
        "preview_only": True,
        "commands_executed": False,
    }
    return report
