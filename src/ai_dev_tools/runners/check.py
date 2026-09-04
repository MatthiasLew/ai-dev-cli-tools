from __future__ import annotations

import hashlib
import json
import re
import sys
import time
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from threading import Event

from ai_dev_tools.cache.repository import update_repository_index
from ai_dev_tools.cache.validation import (
    load_validation_result,
    store_validation_result,
    validation_cache_key,
)
from ai_dev_tools.config import Settings, load_settings
from ai_dev_tools.detectors.runtime import detect_runtime_requirements
from ai_dev_tools.detectors.workspaces import detect_workspaces
from ai_dev_tools.models.report import Artifact, Issue, Report
from ai_dev_tools.parsers.failures import classify_failure
from ai_dev_tools.parsers.logs import parse_tool_output
from ai_dev_tools.reporters.writer import write_json, write_markdown
from ai_dev_tools.runners import check_selection as _selection
from ai_dev_tools.runners.baseline import apply_baseline_comparison
from ai_dev_tools.runners.check_checkpoint import load_resume_keys, write_checkpoint
from ai_dev_tools.runners.check_models import (
    ChangedSelection as ChangedSelection,
)
from ai_dev_tools.runners.check_models import (
    CheckCategory,
    CheckCost,
)
from ai_dev_tools.runners.check_models import (
    CheckTask as CheckTask,
)
from ai_dev_tools.runners.check_scheduler import schedule_checks, schedule_graph
from ai_dev_tools.runners.flaky import eligible_for_retry, record_result
from ai_dev_tools.runners.focused import focused_rerun
from ai_dev_tools.security.execution import ExecutionPolicy, assess_command
from ai_dev_tools.security.secrets import mask_text
from ai_dev_tools.utils.subprocess import CommandResult, run_command, split_command


def _elapsed(started: float) -> float:
    return round(time.monotonic() - started, 6)


def collect_changed_files(root: Path) -> list[str]:
    return _selection.collect_changed_files(root, run_command)


def infer_tests_for_changed_files(root: Path, changed_files: list[str]) -> list[str]:
    return _selection.infer_tests_for_changed_files(root, changed_files)


def select_changed_checks(settings: Settings, plan: list[CheckTask]) -> ChangedSelection:
    return _selection.select_changed_checks(settings, plan, collect_changed_files)


def run_check(
    project_root: Path,
    mode: str = "fast",
    explain: bool = False,
    jobs: int = 1,
    use_cache: bool = True,
    policy: str = "complete",
    resume: bool = False,
    retry_flaky: int = 0,
    retry_infra: int = 1,
    compare: str | None = None,
    cancel_event: Event | None = None,
) -> Report:
    stage_started = time.monotonic()
    settings = load_settings(project_root)
    plan = build_validation_plan(settings)
    timings = {"detection": _elapsed(stage_started)}
    stage_started = time.monotonic()
    changed_selection = select_changed_checks(settings, plan) if mode == "changed" else None
    tasks = _tasks_for_mode(plan, mode, changed_selection)
    timings["selection"] = _elapsed(stage_started)
    command = f"check --mode {mode}" + (" --explain" if explain else "")
    report = Report(command=command, project_root=settings.project_root)
    if not 0 <= retry_flaky <= 3:
        report.status = "invalid_configuration"
        report.summary = {
            "reason_code": "INVALID_FLAKY_RETRY_LIMIT",
            "retry_flaky": retry_flaky,
            "maximum": 3,
        }
        return report.finish()
    if not 0 <= retry_infra <= 3:
        report.status = "invalid_configuration"
        report.summary = {
            "reason_code": "INVALID_INFRASTRUCTURE_RETRY_LIMIT",
            "retry_infra": retry_infra,
            "maximum": 3,
        }
        return report.finish()
    if explain:
        stage_started = time.monotonic()
        schedule = schedule_graph(tasks, policy)
        timings["scheduling"] = _elapsed(stage_started)
        report.summary = {
            "mode": mode,
            "plan": [task.to_dict() for task in plan],
            "selected_checks": [task.to_dict() for task in tasks],
            "changed_analysis": changed_selection.to_dict() if changed_selection else None,
            "explain_only": True,
            "schedule": schedule,
            "resume_requested": resume,
            "performance": {"stages_seconds": timings},
        }
        _add_runtime_summary(report, settings.project_root)
        if compare is not None:
            apply_baseline_comparison(report, settings.project_root, compare)
        report.finish()
        _write_check_reports(report, f"{mode}-explain")
        return report
    if not tasks:
        report.status = "partial"
        report.summary = {
            "mode": mode,
            "message": "No configured checks detected",
            "reason_code": "NO_CHECKS_DETECTED",
            "plan": [task.to_dict() for task in plan],
        }
        if changed_selection is not None:
            report.summary["changed_analysis"] = changed_selection.to_dict()
        _add_runtime_summary(report, settings.project_root)
        if compare is not None:
            apply_baseline_comparison(report, settings.project_root, compare)
        report.finish()
        _write_check_reports(report, mode)
        return report

    index = update_repository_index(settings.project_root)
    entries = index.get("entries", [])
    selected_tasks = tasks
    cache_enabled = use_cache or resume
    task_keys = [
        validation_cache_key(entries, task.command, task.workspace) for task in selected_tasks
    ]
    resume_keys = load_resume_keys(settings.project_root, set(task_keys)) if resume else set()
    worker_count = max(1, min(jobs, len(selected_tasks)))
    scheduled = schedule_checks(
        selected_tasks,
        worker_count,
        policy,
        lambda task: (
            _run_logged(
                task,
                settings.project_root,
                settings.logs_directory,
                entries,
                cache_enabled,
                retry_flaky,
                retry_infra,
                cancel_event,
            )
            if cancel_event is not None
            else _run_logged(
                task,
                settings.project_root,
                settings.logs_directory,
                entries,
                cache_enabled,
                retry_flaky,
                retry_infra,
            )
        ),
    )
    tasks = scheduled.tasks
    results = scheduled.results

    failed = [result for result in results if result.exit_code != 0]
    flaky_results = [result for result in results if result.flaky]
    recovered_results = [result for result in results if result.infrastructure_recovered]
    report.status = (
        "failed" if failed else "warning" if flaky_results or recovered_results else "success"
    )
    for task, result in zip(tasks, results, strict=True):
        if result.flaky:
            report.issues.append(
                Issue(
                    "warning",
                    f"{task.name} failed initially and passed after {result.attempts - 1} retry.",
                    code="FLAKY_PASS",
                )
            )
        if result.infrastructure_recovered:
            report.issues.append(
                Issue(
                    "warning",
                    f"{task.name} recovered after a transient infrastructure retry.",
                    code="INFRASTRUCTURE_RETRY_RECOVERED",
                )
            )
    report.summary = _summary_for_results(mode, plan, tasks, results, changed_selection)
    report.summary["selected_checks"] = [task.to_dict() for task in selected_tasks]
    result_rows = report.summary.get("results", [])
    if isinstance(result_rows, list):
        for task, result, row in zip(tasks, results, result_rows, strict=True):
            if not isinstance(row, dict):
                continue
            key = validation_cache_key(entries, task.command, task.workspace)
            row["reuse"] = (
                "resumed"
                if result.cached and key in resume_keys
                else "cached"
                if result.cached
                else "executed"
            )
    successful_keys = [
        validation_cache_key(entries, task.command, task.workspace)
        for task, result in zip(tasks, results, strict=True)
        if result.exit_code == 0 and not result.flaky
    ]
    checkpoint_path = write_checkpoint(
        settings.project_root,
        mode=mode,
        task_keys=task_keys,
        successful_keys=successful_keys,
        cancelled=len(scheduled.cancelled),
    )
    report.artifacts.append(Artifact(str(checkpoint_path), "checkpoint", "Validation resume state"))
    index_summary = index.get("summary", {})
    report.summary["execution"] = {
        "jobs": worker_count,
        "parallel": worker_count > 1,
        "policy": policy,
        "schedule": schedule_graph(selected_tasks, policy),
        "cancelled": [task.to_dict() for task in scheduled.cancelled],
        "cache_enabled": cache_enabled,
        "cache_hits": sum(result.cached for result in results),
        "resumed": sum(
            result.cached
            and validation_cache_key(entries, task.command, task.workspace) in resume_keys
            for task, result in zip(tasks, results, strict=True)
        ),
        "wall_seconds": scheduled.wall_seconds,
        "aggregate_subprocess_seconds": scheduled.aggregate_seconds,
        "time_to_first_failure_seconds": scheduled.time_to_first_failure_seconds,
        "retry_flaky": retry_flaky,
        "retry_infra": retry_infra,
        "retry_attempts": sum(max(0, result.attempts - 1) for result in results),
        "infrastructure_retry_attempts": sum(
            result.infrastructure_attempts for result in results
        ),
        "infrastructure_recoveries": len(recovered_results),
        "flaky_passes": len(flaky_results),
        "index": index_summary,
    }

    _add_runtime_summary(report, settings.project_root)
    if compare is not None:
        apply_baseline_comparison(report, settings.project_root, compare)
    report.finish()
    _write_check_reports(report, mode)
    return report


def _project_python(root: Path) -> str:
    win_python = root / ".venv" / "Scripts" / "python.exe"
    if win_python.is_file():
        return str(win_python)
    posix_python = root / ".venv" / "bin" / "python"
    if posix_python.is_file():
        return str(posix_python)
    return sys.executable


def build_validation_plan(
    settings: Settings, *, include_workspaces: bool = True
) -> list[CheckTask]:
    if settings.commands:
        return _configured_plan(settings.commands)
    root = settings.project_root
    python_bin = _project_python(root)
    tasks: list[CheckTask] = []
    if (root / "pyproject.toml").exists() or (root / "requirements.txt").exists():
        text = (
            (root / "pyproject.toml").read_text(encoding="utf-8", errors="replace")
            if (root / "pyproject.toml").exists()
            else ""
        )
        if "ruff" in text:
            tasks.append(
                CheckTask(
                    "ruff", "lint", [python_bin, "-m", "ruff", "check", "."], "fast", "detected"
                )
            )
        if "mypy" in text:
            tasks.append(
                CheckTask(
                    "mypy",
                    "typecheck",
                    [python_bin, "-m", "mypy", "src", "tests"],
                    "medium",
                    "detected",
                )
            )
        if "black" in text:
            tasks.append(
                CheckTask(
                    "black",
                    "format",
                    [python_bin, "-m", "black", "--check", "."],
                    "fast",
                    "detected",
                )
            )
        if (root / "tests").exists():
            tasks.append(
                CheckTask(
                    "pytest", "unit_tests", [python_bin, "-m", "pytest"], "medium", "detected"
                )
            )
    if (root / "package.json").exists():
        package = (root / "package.json").read_text(encoding="utf-8", errors="replace")
        if "eslint" in package:
            tasks.append(
                CheckTask("npm lint", "lint", ["npm", "run", "lint"], "medium", "detected")
            )
        if "typescript" in package or "tsc" in package:
            tasks.append(
                CheckTask(
                    "npm typecheck", "typecheck", ["npm", "run", "typecheck"], "medium", "detected"
                )
            )
        if '"test"' in package:
            tasks.append(CheckTask("npm test", "unit_tests", ["npm", "test"], "medium", "detected"))
        if '"build"' in package:
            tasks.append(
                CheckTask(
                    "npm build",
                    "build",
                    ["npm", "run", "build"],
                    "slow",
                    "detected",
                    required=False,
                )
            )
    if (root / "Cargo.toml").exists():
        tasks.extend(
            [
                CheckTask("cargo fmt", "format", ["cargo", "fmt", "--check"], "fast", "detected"),
                CheckTask("cargo clippy", "lint", ["cargo", "clippy"], "medium", "detected"),
                CheckTask("cargo test", "unit_tests", ["cargo", "test"], "medium", "detected"),
            ]
        )
    if (root / "pom.xml").exists():
        tasks.append(CheckTask("maven test", "unit_tests", ["mvn", "test"], "slow", "detected"))
    if (root / "build.gradle").exists() or (root / "build.gradle.kts").exists():
        tasks.append(CheckTask("gradle test", "unit_tests", ["gradle", "test"], "slow", "detected"))
    if (root / "composer.json").exists():
        tasks.append(
            CheckTask("composer test", "unit_tests", ["composer", "test"], "medium", "detected")
        )
    if include_workspaces:
        for workspace in detect_workspaces(root):
            if not workspace.root:
                continue
            workspace_root = root / workspace.root
            child_settings = load_settings(workspace_root)
            child_tasks = build_validation_plan(child_settings, include_workspaces=False)
            tasks.extend(replace(task, workspace=workspace.root) for task in child_tasks)
    return sorted(_deduplicate_tasks(tasks), key=_task_order)


def _configured_plan(commands: dict[str, str]) -> list[CheckTask]:
    mapping: list[tuple[str, CheckCategory, CheckCost]] = [
        ("format", "format", "fast"),
        ("lint", "lint", "fast"),
        ("typecheck", "typecheck", "medium"),
        ("test", "unit_tests", "medium"),
        ("integration_test", "integration_tests", "slow"),
        ("build", "build", "slow"),
    ]
    tasks = [
        CheckTask(key, category, split_command(commands[key]), cost, "configured")
        for key, category, cost in mapping
        if key in commands
    ]
    return sorted(tasks, key=_task_order)


def _tasks_for_mode(
    plan: list[CheckTask], mode: str, changed: ChangedSelection | None
) -> list[CheckTask]:
    if mode == "full":
        return plan
    if mode == "fast":
        fast_tasks = [
            task for task in plan if task.cost == "fast" or task.category in {"lint", "typecheck"}
        ]
        return fast_tasks or [task for task in plan if task.category == "unit_tests"][:1]
    broad_strategies = {"no_changes", "configuration_change"}
    if changed is None or changed.strategy in broad_strategies:
        return [
            task for task in plan if task.category in {"format", "lint", "typecheck", "unit_tests"}
        ]
    relevant_plan = _tasks_for_changed_workspaces(plan, changed.changed_files)
    if changed.strategy == "broad_fallback":
        return [
            task
            for task in relevant_plan
            if task.category in {"format", "lint", "typecheck", "unit_tests"}
        ]
    selected_commands = {tuple(command) for command in changed.selected_commands}
    selected_tasks = [
        task for task in relevant_plan if task.category in {"format", "lint", "typecheck"}
    ]
    for command in selected_commands:
        workspace = _workspace_for_command(relevant_plan, list(command))
        selected_tasks.append(
            CheckTask(
                "affected tests",
                "unit_tests",
                _command_relative_to_workspace(list(command), workspace),
                "fast",
                "detected",
                workspace=workspace,
            )
        )
    return sorted(selected_tasks, key=_task_order)


def _run_logged(
    task: CheckTask,
    root: Path,
    logs_dir: Path,
    index_entries: object,
    use_cache: bool,
    retry_flaky: int = 0,
    retry_infra: int = 1,
    cancel_event: Event | None = None,
) -> CommandResult:
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_path = logs_dir / f"check-{datetime.now().strftime('%Y%m%d-%H%M%S-%f')}.log"
    working_directory = root / task.workspace if task.workspace else root
    cache_key = validation_cache_key(index_entries, task.command, task.workspace)
    result = load_validation_result(root, cache_key, task.command) if use_cache else None
    if result is None:
        execution = load_settings(root).execution
        assessment = assess_command(
            task.command,
            root,
            ExecutionPolicy(
                mode=execution.mode,
                allow_prefixes=tuple(execution.allow_prefixes),
                deny_prefixes=tuple(execution.deny_prefixes),
                maximum_impact=execution.maximum_impact,
            ),
        )
        if not assessment.allowed:
            result = CommandResult(
                task.command,
                126,
                "",
                assessment.reason_code,
                0.0,
                failure_class="policy",
            )
        else:
            result = (
                run_command(task.command, working_directory, cancel_event=cancel_event)
                if cancel_event is not None
                else run_command(task.command, working_directory)
            )
        result.stdout = mask_text(result.stdout)
        result.stderr = mask_text(result.stderr)
        first_output = result.combined_output
        first_exit_code = result.exit_code
        total_duration = result.duration_seconds
        attempts = 1
        classification = classify_failure(result)
        result.failure_class = classification.category
        result.retryable = classification.retryable
        if retry_infra and classification.retryable and not result.cancelled:
            for _ in range(retry_infra):
                retry = (
                    run_command(task.command, working_directory, cancel_event=cancel_event)
                    if cancel_event is not None
                    else run_command(task.command, working_directory)
                )
                retry.stdout = mask_text(retry.stdout)
                retry.stderr = mask_text(retry.stderr)
                attempts += 1
                total_duration += retry.duration_seconds
                result = retry
                result.infrastructure_attempts = attempts - 1
                classification = classify_failure(result)
                result.failure_class = classification.category
                result.retryable = classification.retryable
                if retry.exit_code == 0:
                    result.infrastructure_recovered = True
                    break
                if not classification.retryable:
                    break
        if retry_flaky and not result.cancelled and eligible_for_retry(task, result):
            for _ in range(retry_flaky):
                retry = (
                    run_command(task.command, working_directory, cancel_event=cancel_event)
                    if cancel_event is not None
                    else run_command(task.command, working_directory)
                )
                retry.stdout = mask_text(retry.stdout)
                retry.stderr = mask_text(retry.stderr)
                attempts += 1
                total_duration += retry.duration_seconds
                result = retry
                classification = classify_failure(result)
                result.failure_class = classification.category
                result.retryable = classification.retryable
                if retry.exit_code == 0:
                    result.flaky = True
                    break
        result.duration_seconds = round(total_duration, 3)
        result.attempts = attempts
        if attempts > 1:
            result.initial_exit_code = first_exit_code
            result.initial_output = first_output
        if use_cache and not result.flaky and not result.cancelled:
            store_validation_result(root, cache_key, result)
        if task.category in {"unit_tests", "integration_tests"}:
            record_result(root, task, cache_key, result)
    log_text = result.combined_output
    if result.attempts > 1:
        log_text = chr(10).join(
            [
                f"FIRST_ATTEMPT_EXIT={result.initial_exit_code}",
                result.initial_output,
                f"FINAL_ATTEMPT={result.attempts} EXIT={result.exit_code}",
                result.combined_output,
            ]
        )
    log_path.write_text(log_text + chr(10), encoding="utf-8")
    result.stdout += chr(10) + f"FULL_LOG: {log_path}"
    return result


def _summary_for_results(
    mode: str,
    plan: list[CheckTask],
    tasks: list[CheckTask],
    results: list[CommandResult],
    changed_selection: ChangedSelection | None,
) -> dict[str, object]:
    result_summaries = [
        _result_summary(task, result) for task, result in zip(tasks, results, strict=True)
    ]
    failed_results = [item for item in result_summaries if item["exit_code"] != 0]
    flaky_results = [item for item in result_summaries if item["flaky"]]
    first_failure = next(
        (item.get("first_failure") for item in failed_results if item.get("first_failure")),
        next(
            (item.get("initial_failure") for item in flaky_results if item.get("initial_failure")),
            None,
        ),
    )
    summary: dict[str, object] = {
        "mode": mode,
        "checks_total": len(result_summaries),
        "checks_passed": len(result_summaries) - len(failed_results) - len(flaky_results),
        "checks_failed": len(failed_results),
        "checks_flaky": len(flaky_results),
        "tests_total": sum(_int_value(item.get("tests_total")) for item in result_summaries),
        "tests_passed": sum(_int_value(item.get("passed")) for item in result_summaries),
        "tests_failed": sum(_int_value(item.get("failed")) for item in result_summaries),
        "tests_skipped": sum(_int_value(item.get("skipped")) for item in result_summaries),
        "first_failure": first_failure,
        "plan": [task.to_dict() for task in plan],
        "selected_checks": [task.to_dict() for task in tasks],
        "results": result_summaries,
    }
    if changed_selection is not None:
        summary["changed_analysis"] = changed_selection.to_dict()
    return summary


def _int_value(value: object) -> int:
    return value if isinstance(value, int) else 0


def _result_summary(task: CheckTask, result: CommandResult) -> dict[str, object]:
    tool_label = " ".join(task.command)
    parsed = parse_tool_output(tool_label, result.combined_output, result.exit_code)
    initial_exit_code = (
        result.initial_exit_code if result.initial_exit_code is not None else result.exit_code
    )
    initial_parsed = (
        parse_tool_output(tool_label, result.initial_output, initial_exit_code)
        if result.initial_output
        else parsed
    )
    failure_signature = (
        _failure_signature(task, initial_parsed) if result.exit_code != 0 or result.flaky else None
    )
    return {
        "name": task.name,
        "category": task.category,
        "workspace": task.workspace,
        "command": " ".join(result.command),
        "exit_code": result.exit_code,
        "duration_seconds": result.duration_seconds,
        "timed_out": result.timed_out,
        "cancelled": result.cancelled,
        "failure_class": result.failure_class,
        "retryable": result.retryable,
        "infrastructure_recovered": result.infrastructure_recovered,
        "infrastructure_attempts": result.infrastructure_attempts,
        "cached": result.cached,
        "attempts": result.attempts,
        "flaky": result.flaky,
        "initial_exit_code": result.initial_exit_code,
        "initial_failure": (initial_parsed.get("first_failure") if result.attempts > 1 else None),
        "full_log": _full_log_from_output(result.stdout),
        "failure_signature": failure_signature,
        "focused_rerun": (focused_rerun(task, initial_parsed) if failure_signature else None),
        **parsed,
    }


def _failure_signature(task: CheckTask, parsed: dict[str, object]) -> str:
    failure = parsed.get("first_failure")
    canonical = {
        "tool": parsed.get("parser"),
        "workspace": task.workspace,
        "category": task.category,
        "failure": failure,
    }
    text = json.dumps(canonical, sort_keys=True, ensure_ascii=True).lower()
    text = re.sub(r"\b\d+\b", "#", text)
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
    return f"failure:{digest}"


def _task_order(task: CheckTask) -> tuple[int, str, str]:
    category_order = {
        "format": 0,
        "lint": 1,
        "typecheck": 2,
        "unit_tests": 3,
        "integration_tests": 4,
        "build": 5,
    }
    return (category_order[task.category], task.workspace, task.name)


def _tasks_for_changed_workspaces(
    plan: list[CheckTask], changed_files: list[str]
) -> list[CheckTask]:
    workspace_roots = sorted(
        {task.workspace for task in plan if task.workspace},
        key=len,
        reverse=True,
    )
    selected: set[str] = set()
    for path in changed_files:
        normalized = path.replace(chr(92), "/").strip("/")
        owner = next(
            (
                root
                for root in workspace_roots
                if normalized == root or normalized.startswith(root + "/")
            ),
            "",
        )
        selected.add(owner)
    return [task for task in plan if task.workspace in selected]


def _workspace_for_command(plan: list[CheckTask], command: list[str]) -> str:
    normalized_arguments = [item.replace(chr(92), "/") for item in command]
    roots = sorted({task.workspace for task in plan if task.workspace}, key=len, reverse=True)
    return next(
        (
            root
            for root in roots
            if any(argument.startswith(root + "/") for argument in normalized_arguments)
        ),
        "",
    )


def _command_relative_to_workspace(command: list[str], workspace: str) -> list[str]:
    if not workspace:
        return command
    prefix = workspace.replace(chr(92), "/").rstrip("/") + "/"
    return [
        item.replace(chr(92), "/")[len(prefix) :]
        if item.replace(chr(92), "/").startswith(prefix)
        else item
        for item in command
    ]


def _deduplicate_tasks(tasks: list[CheckTask]) -> list[CheckTask]:
    unique: dict[tuple[str, str, tuple[str, ...]], CheckTask] = {}
    for task in tasks:
        unique[(task.workspace, task.category, tuple(task.command))] = task
    return list(unique.values())


def _full_log_from_output(output: str) -> str | None:
    for line in output.splitlines():
        if line.startswith("FULL_LOG:"):
            return line.split(":", 1)[1].strip()
    return None


def _add_runtime_summary(report: Report, root: Path) -> None:
    report.summary["runtime_requirements"] = [
        item.to_dict() for item in detect_runtime_requirements(root)
    ]


def _write_check_reports(report: Report, mode: str) -> None:
    settings = load_settings(report.project_root)
    write_markdown(report, settings.reports_directory / f"check-{mode}-latest.md")
    write_json(report, settings.reports_directory / f"check-{mode}-latest.json")
