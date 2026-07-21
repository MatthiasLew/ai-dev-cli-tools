from __future__ import annotations

import fnmatch
import sys
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

from ai_dev_tools.config import Settings, load_settings
from ai_dev_tools.models.report import Report
from ai_dev_tools.parsers.logs import parse_tool_output
from ai_dev_tools.reporters.writer import write_json, write_markdown
from ai_dev_tools.utils.subprocess import CommandResult, run_command, split_command

CheckCategory = Literal["format", "lint", "typecheck", "unit_tests", "integration_tests", "build"]
CheckCost = Literal["fast", "medium", "slow"]
CheckSource = Literal["detected", "configured"]
ChangedStrategy = Literal[
    "direct_test_match",
    "package_or_module_match",
    "configured_mapping",
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


def run_check(project_root: Path, mode: str = "fast") -> Report:
    settings = load_settings(project_root)
    plan = build_validation_plan(settings)
    changed_selection = select_changed_checks(settings, plan) if mode == "changed" else None
    tasks = _tasks_for_mode(plan, mode, changed_selection)
    report = Report(command=f"check --mode {mode}", project_root=settings.project_root)
    if not tasks:
        report.status = "warning"
        report.summary = {
            "mode": mode,
            "message": "No configured checks detected",
            "plan": [task.to_dict() for task in plan],
        }
        if changed_selection is not None:
            report.summary["changed_analysis"] = changed_selection.to_dict()
        report.finish()
        _write_check_reports(report, mode)
        return report

    results = [_run_logged(task, settings.project_root, settings.logs_directory) for task in tasks]
    failed = [result for result in results if result.exit_code != 0]
    report.status = "failed" if failed else "success"
    report.summary = _summary_for_results(mode, plan, tasks, results, changed_selection)
    report.finish()
    _write_check_reports(report, mode)
    return report


def build_validation_plan(settings: Settings) -> list[CheckTask]:
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
    return sorted(tasks, key=_task_order)


def select_changed_checks(settings: Settings, plan: list[CheckTask]) -> ChangedSelection:
    changed_files = collect_changed_files(settings.project_root)
    if not changed_files:
        return ChangedSelection("no_changes", "high", [], [], [], "No changed files detected.")
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
    if changed is None or changed.strategy in {"broad_fallback", "no_changes"}:
        return [
            task for task in plan if task.category in {"format", "lint", "typecheck", "unit_tests"}
        ]
    selected_commands = {tuple(command) for command in changed.selected_commands}
    selected_tasks = [task for task in plan if task.category in {"format", "lint", "typecheck"}]
    selected_tasks.extend(
        CheckTask("affected tests", "unit_tests", list(command), "fast", "detected")
        for command in selected_commands
    )
    return sorted(selected_tasks, key=_task_order)


def _run_logged(task: CheckTask, root: Path, logs_dir: Path) -> CommandResult:
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_path = logs_dir / f"check-{datetime.now().strftime('%Y%m%d-%H%M%S-%f')}.log"
    result = run_command(task.command, root)
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
    return {
        "name": task.name,
        "category": task.category,
        "command": " ".join(result.command),
        "exit_code": result.exit_code,
        "duration_seconds": result.duration_seconds,
        "timed_out": result.timed_out,
        "full_log": _full_log_from_output(result.stdout),
        **parsed,
    }


def _task_order(task: CheckTask) -> tuple[int, str]:
    category_order = {
        "format": 0,
        "lint": 1,
        "typecheck": 2,
        "unit_tests": 3,
        "integration_tests": 4,
        "build": 5,
    }
    return (category_order[task.category], task.name)


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


def _write_check_reports(report: Report, mode: str) -> None:
    settings = load_settings(report.project_root)
    write_markdown(report, settings.reports_directory / f"check-{mode}-latest.md")
    write_json(report, settings.reports_directory / f"check-{mode}-latest.json")
