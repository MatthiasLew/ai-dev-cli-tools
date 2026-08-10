from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path
from typing import Literal

from ai_dev_tools.config import Settings, load_settings
from ai_dev_tools.detectors.environment import run_doctor
from ai_dev_tools.detectors.project import scan_project
from ai_dev_tools.models.report import Artifact, Issue, Report
from ai_dev_tools.reporters.writer import write_json, write_markdown
from ai_dev_tools.runners.bootstrap_models import (
    BootstrapOptions as BootstrapOptions,
)
from ai_dev_tools.runners.bootstrap_models import (
    BootstrapPlan as BootstrapPlan,
)
from ai_dev_tools.runners.bootstrap_models import (
    BootstrapStep as BootstrapStep,
)
from ai_dev_tools.runners.bootstrap_strategies import (
    build_bootstrap_plan as build_bootstrap_plan,
)
from ai_dev_tools.runners.environment_state import (
    capture_environment_state,
    inspect_environment_state,
)
from ai_dev_tools.security.secrets import mask_text
from ai_dev_tools.utils.subprocess import CommandResult, run_command

BootstrapStatus = Literal["planned", "executed", "skipped", "failed"]


def run_bootstrap(project_root: Path, options: BootstrapOptions) -> Report:
    settings = load_settings(project_root)
    report = Report(command="bootstrap", project_root=settings.project_root)
    plan = build_bootstrap_plan(settings, options)
    warm_state = inspect_environment_state(settings.project_root, plan)
    if options.if_needed and warm_state["reusable"] and not options.explain:
        report.summary = {
            "project_type": plan.project_type,
            "package_manager": plan.package_manager,
            "if_needed": True,
            "skipped": True,
            "reason_code": "WARM_ENVIRONMENT_REUSED",
            "planned_commands": len(plan.steps),
            "executed_commands": 0,
            "plan": plan.to_dict(),
            "environment_state": {
                "reusable": True,
                "state_path": warm_state["state_path"],
                "reason_codes": [],
            },
            "modifications": "NONE",
        }
        state_path = Path(str(warm_state["state_path"]))
        report.artifacts.append(
            Artifact(str(state_path), "environment-state", "Reused warm environment state")
        )
        report.finish()
        write_markdown(report, settings.reports_directory / "bootstrap-latest.md")
        write_json(report, settings.reports_directory / "bootstrap-latest.json")
        return report

    scan = scan_project(settings.project_root)
    doctor = run_doctor(settings.project_root)
    missing_tools = _missing_required_tools(plan, doctor)
    incompatible_runtimes = list(doctor.summary.get("incompatible_runtimes", []))
    log_path = _log_path(settings.logs_directory)

    if settings.warnings:
        report.issues.extend(
            Issue("warning", warning, code="CONFIG_WARNING") for warning in settings.warnings
        )
    if incompatible_runtimes:
        report.status = "blocked"
        report.issues.extend(
            Issue(
                "error",
                (
                    f"Incompatible {item.get('runtime')} runtime: "
                    f"requires {item.get('constraint')}, detected {item.get('detected')}."
                ),
                code="INCOMPATIBLE_RUNTIME",
            )
            for item in incompatible_runtimes
            if isinstance(item, dict)
        )
    elif not plan.steps and plan.project_type == "unknown":
        report.status = "blocked"
        report.issues.append(
            Issue("error", "No supported project bootstrap strategy detected.", code="NO_STRATEGY")
        )
    elif missing_tools:
        report.status = "blocked"
        report.issues.extend(
            Issue("error", f"Missing required bootstrap tool: {tool}", code="MISSING_RUNTIME")
            for tool in missing_tools
        )
    else:
        report.status = "success"

    executed: list[dict[str, object]] = []
    created_venv = False
    created_env = False
    smoke_check = "skipped"

    should_execute = report.status == "success" and not options.explain and not options.dry_run
    if should_execute:
        for step in plan.steps:
            result = _execute_step(step, settings, log_path)
            executed.append(_step_result(step, result))
            if step.action == "create_venv" and result.exit_code == 0:
                created_venv = True
            if step.action == "copy_env" and result.exit_code == 0:
                created_env = True
            if result.exit_code != 0:
                report.status = "failed"
                report.exit_code = result.exit_code
                report.issues.append(
                    Issue("error", f"Bootstrap command failed: {step.name}", code="COMMAND_FAILED")
                )
                break
        if report.status == "success" and settings.bootstrap.run_smoke_check:
            smoke_results = [_execute_step(step, settings, log_path) for step in plan.smoke_steps]
            executed.extend(
                _step_result(step, result)
                for step, result in zip(plan.smoke_steps, smoke_results, strict=True)
            )
            smoke_check = (
                "passed" if all(result.exit_code == 0 for result in smoke_results) else "failed"
            )
            if smoke_check == "failed":
                report.status = "partial"
                report.issues.append(
                    Issue("warning", "Bootstrap smoke check failed.", code="SMOKE_FAILED")
                )
    elif options.explain or options.dry_run:
        smoke_check = "planned" if plan.smoke_steps else "skipped"

    summary: dict[str, object] = {
        "project_type": plan.project_type,
        "package_manager": plan.package_manager,
        "dry_run": options.dry_run,
        "if_needed": options.if_needed,
        "explain": options.explain,
        "planned_commands": len(plan.steps),
        "executed_commands": len([item for item in executed if item["exit_code"] == 0]),
        "created_venv": created_venv,
        "created_env": created_env,
        "smoke_check": smoke_check,
        "plan": plan.to_dict(),
        "executed": executed,
        "missing_tools": missing_tools,
        "runtime_compatibility": doctor.summary.get("runtime_compatibility", []),
        "scan": scan.summary,
        "modifications": "NONE" if options.explain or options.dry_run else "PLANNED",
    }
    if log_path.exists():
        summary["full_log"] = str(log_path)
        report.artifacts.append(Artifact(str(log_path), "log", "Full bootstrap command output"))
    summary["environment_state"] = {
        "reusable_before": warm_state["reusable"],
        "reason_codes": warm_state["reason_codes"],
        "state_path": warm_state["state_path"],
        "captured": False,
    }
    if report.status == "success" and should_execute:
        state_path = capture_environment_state(
            settings.project_root,
            plan,
            doctor.summary,
        )
        summary["environment_state"] = {
            "reusable_before": warm_state["reusable"],
            "reason_codes": warm_state["reason_codes"],
            "state_path": str(state_path),
            "captured": True,
        }
        report.artifacts.append(
            Artifact(str(state_path), "environment-state", "Warm environment state")
        )
    report.summary = summary
    report.finish()
    write_markdown(report, settings.reports_directory / "bootstrap-latest.md")
    write_json(report, settings.reports_directory / "bootstrap-latest.json")
    return report


def _execute_step(step: BootstrapStep, settings: Settings, log_path: Path) -> CommandResult:
    working_directory = (
        settings.project_root / step.workspace if step.workspace else settings.project_root
    )
    if step.action == "copy_env":
        source = working_directory / ".env.example"
        target = working_directory / ".env"
        if target.exists():
            result = CommandResult(step.command, 0, "Skipped existing .env", "", 0.0)
        else:
            shutil.copyfile(source, target)
            result = CommandResult(step.command, 0, "Created .env from .env.example", "", 0.0)
    else:
        result = run_command(step.command, working_directory, settings.bootstrap.timeout_seconds)
    result.stdout = mask_text(result.stdout)
    result.stderr = mask_text(result.stderr)
    _append_log(log_path, step, result)
    return result


def _append_log(log_path: Path, step: BootstrapStep, result: CommandResult) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(f"$ {' '.join(step.command)}\n")
        handle.write(result.combined_output + "\n")
        handle.write(f"EXIT_CODE={result.exit_code} DURATION={result.duration_seconds}s\n\n")


def _step_result(step: BootstrapStep, result: CommandResult) -> dict[str, object]:
    return {
        "name": step.name,
        "command": step.command,
        "exit_code": result.exit_code,
        "duration_seconds": result.duration_seconds,
        "timed_out": result.timed_out,
    }


def _missing_required_tools(plan: BootstrapPlan, doctor: Report) -> list[str]:
    tools = doctor.summary.get("tools", {})
    if not isinstance(tools, dict):
        return plan.required_tools
    missing: list[str] = []
    for tool in plan.required_tools:
        if tool == "python":
            continue
        tool_info = tools.get(tool)
        if not isinstance(tool_info, dict) or tool_info.get("status") != "ok":
            missing.append(tool)
    return sorted(set(missing))


def _log_path(logs_dir: Path) -> Path:
    return logs_dir / f"bootstrap-{datetime.now().strftime('%Y%m%d-%H%M%S-%f')}.log"
