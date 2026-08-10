from __future__ import annotations

import fnmatch
import hashlib
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Literal

from ai_dev_tools.cache.repository import update_repository_index
from ai_dev_tools.cache.validation import (
    load_validation_result,
    store_validation_result,
    validation_cache_key,
)
from ai_dev_tools.config import Settings, load_settings
from ai_dev_tools.detectors.runtime import detect_runtime_requirements
from ai_dev_tools.detectors.workspaces import detect_workspaces
from ai_dev_tools.models.report import Report
from ai_dev_tools.parsers.logs import parse_tool_output
from ai_dev_tools.reporters.writer import write_json, write_markdown
from ai_dev_tools.utils.subprocess import CommandResult, run_command, split_command

CheckCategory = Literal["format", "lint", "typecheck", "unit_tests", "integration_tests", "build"]
CheckCost = Literal["fast", "medium", "slow"]
CheckSource = Literal["detected", "configured"]
ChangedStrategy = Literal[
    "changed_test_direct",
    "direct_test_match",
    "module_match",
    "package_match",
    "workspace_match",
    "configured_mapping",
    "configuration_change",
    "broad_fallback",
    "no_changes",
]


@dataclass(frozen=True, slots=True)
class CheckTask:
    name: str
    category: CheckCategory
    command: list[str]
    cost: CheckCost
    source: CheckSource
    required: bool = True
    workspace: str = ""

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ChangedSelection:
    strategy: ChangedStrategy
    confidence: str
    changed_files: list[str]
    selected_tests: list[str]
    selected_commands: list[list[str]]
    fallback_reason: str | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def run_check(
    project_root: Path,
    mode: str = "fast",
    explain: bool = False,
    jobs: int = 1,
    use_cache: bool = True,
) -> Report:
    settings = load_settings(project_root)
    plan = build_validation_plan(settings)
    changed_selection = select_changed_checks(settings, plan) if mode == "changed" else None
    tasks = _tasks_for_mode(plan, mode, changed_selection)
    command = f"check --mode {mode}" + (" --explain" if explain else "")
    report = Report(command=command, project_root=settings.project_root)
    if explain:
        report.summary = {
            "mode": mode,
            "plan": [task.to_dict() for task in plan],
            "selected_checks": [task.to_dict() for task in tasks],
            "changed_analysis": changed_selection.to_dict() if changed_selection else None,
            "explain_only": True,
        }
        _add_runtime_summary(report, settings.project_root)
        report.finish()
        _write_check_reports(report, f"{mode}-explain")
        return report
    if not tasks:
        report.status = "partial"
        report.summary = {
            "mode": mode,
            "message": "No configured checks detected",
            "plan": [task.to_dict() for task in plan],
        }
        if changed_selection is not None:
            report.summary["changed_analysis"] = changed_selection.to_dict()
        _add_runtime_summary(report, settings.project_root)
        report.finish()
        _write_check_reports(report, mode)
        return report

    index = update_repository_index(settings.project_root)
    entries = index.get("entries", [])
    worker_count = max(1, min(jobs, len(tasks)))
    if worker_count == 1:
        results = [
            _run_logged(
                task,
                settings.project_root,
                settings.logs_directory,
                entries,
                use_cache,
            )
            for task in tasks
        ]
    else:
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            results = list(
                executor.map(
                    lambda task: _run_logged(
                        task,
                        settings.project_root,
                        settings.logs_directory,
                        entries,
                        use_cache,
                    ),
                    tasks,
                )
            )
    failed = [result for result in results if result.exit_code != 0]
    report.status = "failed" if failed else "success"
    report.summary = _summary_for_results(mode, plan, tasks, results, changed_selection)
    index_summary = index.get("summary", {})
    report.summary["execution"] = {
        "jobs": worker_count,
        "parallel": worker_count > 1,
        "cache_enabled": use_cache,
        "cache_hits": sum(result.cached for result in results),
        "index": index_summary,
    }
    _add_runtime_summary(report, settings.project_root)
    report.finish()
    _write_check_reports(report, mode)
    return report


def build_validation_plan(
    settings: Settings, *, include_workspaces: bool = True
) -> list[CheckTask]:
    if settings.commands:
        return _configured_plan(settings.commands)
    root = settings.project_root
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
                    "ruff", "lint", [sys.executable, "-m", "ruff", "check", "."], "fast", "detected"
                )
            )
        if "mypy" in text:
            tasks.append(
                CheckTask(
                    "mypy",
                    "typecheck",
                    [sys.executable, "-m", "mypy", "src", "tests"],
                    "medium",
                    "detected",
                )
            )
        if "black" in text:
            tasks.append(
                CheckTask(
                    "black",
                    "format",
                    [sys.executable, "-m", "black", "--check", "."],
                    "fast",
                    "detected",
                )
            )
        if (root / "tests").exists():
            tasks.append(
                CheckTask(
                    "pytest", "unit_tests", [sys.executable, "-m", "pytest"], "medium", "detected"
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


def select_changed_checks(settings: Settings, plan: list[CheckTask]) -> ChangedSelection:
    changed_files = collect_changed_files(settings.project_root)
    if not changed_files:
        return ChangedSelection("no_changes", "high", [], [], [], "No changed files detected.")
    config_reason = _configuration_change_reason(changed_files)
    if config_reason:
        return ChangedSelection(
            "configuration_change",
            "low",
            changed_files,
            [],
            [],
            config_reason,
        )
    direct_changed_tests = [path for path in changed_files if _is_test_path(Path(path))]
    if direct_changed_tests:
        return ChangedSelection(
            "changed_test_direct",
            "high",
            changed_files,
            sorted(direct_changed_tests),
            _commands_for_selected_tests(plan, sorted(direct_changed_tests)),
            None,
        )
    configured_tests = _configured_changed_tests(settings, changed_files)
    if configured_tests:
        return ChangedSelection(
            "configured_mapping",
            "high",
            changed_files,
            configured_tests,
            _commands_for_selected_tests(plan, configured_tests),
            None,
        )
    selected_tests = infer_tests_for_changed_files(settings.project_root, changed_files)
    if selected_tests:
        strategy: ChangedStrategy = "direct_test_match"
        return ChangedSelection(
            strategy,
            "medium",
            changed_files,
            selected_tests,
            _commands_for_selected_tests(plan, selected_tests),
            None,
        )
    return ChangedSelection(
        "broad_fallback",
        "low",
        changed_files,
        [],
        [],
        "Changed files were detected, but no reliable test dependency map is available yet.",
    )


def collect_changed_files(root: Path) -> list[str]:
    seen: dict[str, None] = {}
    commands = [
        ["git", "diff", "--name-only", "-z"],
        ["git", "diff", "--cached", "--name-only", "-z"],
        ["git", "ls-files", "--others", "--exclude-standard", "-z"],
    ]
    upstream = run_command(
        ["git", "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"], root, 30
    )
    if upstream.exit_code == 0 and upstream.stdout.strip():
        commands.append(["git", "diff", "--name-only", "-z", upstream.stdout.strip() + "...HEAD"])
    for command in commands:
        result = run_command(command, root, 30)
        if result.exit_code != 0:
            continue
        for item in _split_nul(result.stdout):
            if item:
                seen[item] = None
    return sorted(seen)


def infer_tests_for_changed_files(root: Path, changed_files: list[str]) -> list[str]:
    selected: dict[str, None] = {}
    for rel in changed_files:
        path = Path(rel)
        if _is_test_path(path):
            _add_existing(root, selected, rel)
            continue
        candidates = _candidate_tests_for_source(path)
        for candidate in candidates:
            _add_existing(root, selected, candidate)
        for importer in _python_importing_tests(root, path):
            selected[importer] = None
    return sorted(selected)


def _configuration_change_reason(changed_files: list[str]) -> str | None:
    broad_files = {
        "pyproject.toml",
        "pytest.ini",
        "tox.ini",
        "noxfile.py",
        "package.json",
        "pnpm-workspace.yaml",
        "jest.config.js",
        "jest.config.ts",
        "vitest.config.js",
        "vitest.config.ts",
        "pom.xml",
        "build.gradle",
        "build.gradle.kts",
        "settings.gradle",
        "settings.gradle.kts",
        "Cargo.toml",
        "Cargo.lock",
        "composer.json",
        "phpunit.xml",
    }
    for rel in changed_files:
        path = Path(rel)
        normalized = path.as_posix()
        if path.name == "conftest.py" or "fixtures" in path.parts:
            return f"Shared test fixture changed: {rel}"
        if normalized in broad_files or path.name in broad_files:
            return f"Project or test configuration changed: {rel}"
    return None


def _candidate_tests_for_source(path: Path) -> list[str]:
    stem = path.stem
    suffix = path.suffix.lower()
    parts = list(path.parts)
    candidates: list[str] = []
    if suffix == ".py":
        relative_parts = parts[1:] if parts and parts[0] in {"src", "lib"} else parts
        if relative_parts:
            relative_parts[-1] = f"test_{stem}.py"
            candidates.append(str(Path("tests", *relative_parts)))
        candidates.append(str(Path("tests", f"test_{stem}.py")))
    if suffix in {".js", ".jsx", ".ts", ".tsx"}:
        candidates.extend(
            [
                str(path.with_name(f"{stem}.test{suffix}")),
                str(path.with_name(f"{stem}.spec{suffix}")),
                str(Path("tests", f"{stem}.test{suffix}")),
                str(Path("tests", f"{stem}.spec{suffix}")),
            ]
        )
    if suffix == ".java" and parts[:3] == ["src", "main", "java"]:
        test_parts = ["src", "test", "java", *parts[3:]]
        test_parts[-1] = f"{stem}Test.java"
        candidates.append(str(Path(*test_parts)))
    if suffix == ".php":
        rel_parts = parts[1:] if parts and parts[0] == "src" else parts
        if rel_parts:
            rel_parts[-1] = f"{stem}Test.php"
            candidates.append(str(Path("tests", *rel_parts)))
    return candidates


def _python_importing_tests(root: Path, source_path: Path) -> list[str]:
    if source_path.suffix.lower() != ".py" or not (root / "tests").exists():
        return []
    module = ".".join(source_path.with_suffix("").parts)
    if module.startswith("src."):
        module = module[4:]
    needle_options = {
        f"import {module}",
        f"from {module} import",
        f"from {module.rsplit('.', 1)[0]} import" if "." in module else "",
    }
    matches: list[str] = []
    for test_path in (root / "tests").rglob("test_*.py"):
        text = test_path.read_text(encoding="utf-8", errors="replace")
        if any(needle and needle in text for needle in needle_options):
            matches.append(str(test_path.relative_to(root)))
    return matches


def _configured_changed_tests(settings: Settings, changed_files: list[str]) -> list[str]:
    selected: dict[str, None] = {}
    for source_pattern, test_patterns in settings.changed_tests.items():
        if not any(
            fnmatch.fnmatch(path.replace("\\", "/"), source_pattern) for path in changed_files
        ):
            continue
        for pattern in test_patterns:
            for match in settings.project_root.glob(pattern):
                if match.is_file():
                    selected[str(match.relative_to(settings.project_root))] = None
    return sorted(selected)


def _commands_for_selected_tests(
    plan: list[CheckTask], selected_tests: list[str]
) -> list[list[str]]:
    commands: list[list[str]] = []
    if not selected_tests:
        return commands
    if any(path.endswith(".py") for path in selected_tests):
        commands.append([sys.executable, "-m", "pytest", *selected_tests])
    if any(path.endswith((".js", ".jsx", ".ts", ".tsx")) for path in selected_tests):
        npm_test = next((task.command for task in plan if task.name == "npm test"), ["npm", "test"])
        commands.append(npm_test)
    if any(path.endswith(".java") for path in selected_tests):
        maven = next((task.command for task in plan if task.name == "maven test"), None)
        gradle = next((task.command for task in plan if task.name == "gradle test"), None)
        commands.append(maven or gradle or ["mvn", "test"])
    if any(path.endswith(".php") for path in selected_tests):
        commands.append(
            next(
                (task.command for task in plan if task.name == "composer test"),
                ["composer", "test"],
            )
        )
    return commands


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
) -> CommandResult:
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_path = logs_dir / f"check-{datetime.now().strftime('%Y%m%d-%H%M%S-%f')}.log"
    working_directory = root / task.workspace if task.workspace else root
    cache_key = validation_cache_key(index_entries, task.command, task.workspace)
    result = load_validation_result(root, cache_key, task.command) if use_cache else None
    if result is None:
        result = run_command(task.command, working_directory)
        if use_cache:
            store_validation_result(root, cache_key, result)
    log_path.write_text(result.combined_output + "\n", encoding="utf-8")
    result.stdout += f"\nFULL_LOG: {log_path}"
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
    first_failure = next(
        (item.get("first_failure") for item in failed_results if item.get("first_failure")), None
    )
    summary: dict[str, object] = {
        "mode": mode,
        "checks_total": len(result_summaries),
        "checks_passed": len(result_summaries) - len(failed_results),
        "checks_failed": len(failed_results),
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
    parsed = parse_tool_output(tool_label, result.combined_output)
    failure_signature = _failure_signature(task, parsed) if result.exit_code != 0 else None
    return {
        "name": task.name,
        "category": task.category,
        "workspace": task.workspace,
        "command": " ".join(result.command),
        "exit_code": result.exit_code,
        "duration_seconds": result.duration_seconds,
        "timed_out": result.timed_out,
        "cached": result.cached,
        "full_log": _full_log_from_output(result.stdout),
        "failure_signature": failure_signature,
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


def _is_test_path(path: Path) -> bool:
    text = path.as_posix().lower()
    return (
        "/tests/" in f"/{text}"
        or ".test." in text
        or ".spec." in text
        or path.name.startswith("test_")
    )


def _add_existing(root: Path, selected: dict[str, None], rel: str) -> None:
    path = root / rel
    if path.exists() and path.is_file():
        selected[str(path.relative_to(root))] = None


def _split_nul(output: str) -> list[str]:
    return [item for item in output.split("\0") if item]


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
