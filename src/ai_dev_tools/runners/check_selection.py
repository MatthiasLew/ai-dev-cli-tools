from __future__ import annotations

import fnmatch
import sys
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from ai_dev_tools.cache.graph import related_tests as graph_related_tests
from ai_dev_tools.cache.graph import shortest_reason_paths
from ai_dev_tools.cache.repository import read_repository_index, update_repository_index
from ai_dev_tools.config import Settings
from ai_dev_tools.runners.check_models import ChangedSelection, ChangedStrategy, CheckTask
from ai_dev_tools.utils.subprocess import CommandResult, run_command


def select_changed_checks(
    settings: Settings,
    plan: list[CheckTask],
    collector: Callable[[Path], list[str]] | None = None,
) -> ChangedSelection:
    changed_files = (collector or collect_changed_files)(settings.project_root)
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


def add_reason_paths(root: Path, selection: ChangedSelection) -> ChangedSelection:
    index = update_repository_index(root)
    paths = shortest_reason_paths(
        index.get("graph"),
        selection.changed_files,
        selected_files=selection.selected_tests,
        selected_tests=selection.selected_tests,
        selected_commands=selection.selected_commands,
        selection_reason_code=f"CHANGED_{selection.strategy.upper()}",
    )
    return replace(selection, reason_paths=paths)


def collect_changed_files(
    root: Path,
    command_runner: Callable[[list[str], Path, int], CommandResult] = run_command,
) -> list[str]:
    top_level = command_runner(["git", "rev-parse", "--show-toplevel"], root, 30)
    if top_level.exit_code != 0 or not top_level.stdout.strip():
        return []
    try:
        if Path(top_level.stdout.strip()).resolve() != root.resolve():
            return []
    except OSError:
        return []
    seen: dict[str, None] = {}
    commands = [
        ["git", "diff", "--name-only", "-z"],
        ["git", "diff", "--cached", "--name-only", "-z"],
        ["git", "ls-files", "--others", "--exclude-standard", "-z"],
    ]
    upstream = command_runner(
        ["git", "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"], root, 30
    )
    if upstream.exit_code == 0 and upstream.stdout.strip():
        commands.append(["git", "diff", "--name-only", "-z", upstream.stdout.strip() + "...HEAD"])
    for command in commands:
        result = command_runner(command, root, 30)
        if result.exit_code != 0:
            continue
        for item in _split_nul(result.stdout):
            if item:
                seen[item] = None
    return sorted(seen)


def infer_tests_for_changed_files(root: Path, changed_files: list[str]) -> list[str]:
    selected: dict[str, None] = {}
    index = read_repository_index(root)
    for rel in graph_related_tests(index.get("graph"), changed_files):
        _add_existing(root, selected, rel)
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
            for match in _matching_test_files(settings.project_root, pattern):
                selected[str(match.relative_to(settings.project_root))] = None
    return sorted(selected)


def _matching_test_files(root: Path, pattern: str) -> list[Path]:
    files: dict[Path, None] = {}
    for match in root.glob(pattern):
        if match.is_file():
            files[match] = None
        elif match.is_dir():
            for child in match.rglob("*"):
                if child.is_file():
                    files[child] = None
    return sorted(files)


def _commands_for_selected_tests(
    plan: list[CheckTask], selected_tests: list[str]
) -> list[list[str]]:
    commands: list[list[str]] = []
    if not selected_tests:
        return commands
    if any(path.endswith(".py") for path in selected_tests):
        pytest_cmd = next((task.command for task in plan if task.name == "pytest"), None)
        python_bin = pytest_cmd[0] if pytest_cmd else sys.executable
        commands.append([python_bin, "-m", "pytest", *selected_tests])
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
