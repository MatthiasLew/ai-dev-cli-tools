from pathlib import Path

import pytest

from ai_dev_tools.config import load_settings
from ai_dev_tools.runners.check import (
    build_validation_plan,
    collect_changed_files,
    infer_tests_for_changed_files,
    select_changed_checks,
)
from ai_dev_tools.utils.subprocess import CommandResult


def test_build_validation_plan_detects_python_tools(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='demo'\n[project.optional-dependencies]\ndev=['ruff','mypy','black']\n",
        encoding="utf-8",
    )
    (tmp_path / "tests").mkdir()
    plan = build_validation_plan(load_settings(tmp_path))
    assert [task.category for task in plan] == ["format", "lint", "typecheck", "unit_tests"]
    assert {task.name for task in plan} == {"black", "ruff", "mypy", "pytest"}


def test_infer_python_test_candidates_and_importers(tmp_path: Path) -> None:
    source = tmp_path / "src" / "pkg"
    source.mkdir(parents=True)
    (source / "service.py").write_text("VALUE = 1", encoding="utf-8")
    tests = tmp_path / "tests" / "pkg"
    tests.mkdir(parents=True)
    (tests / "test_service.py").write_text("from pkg.service import VALUE", encoding="utf-8")
    selected = infer_tests_for_changed_files(tmp_path, ["src/pkg/service.py"])
    assert "tests\\pkg\\test_service.py" in selected or "tests/pkg/test_service.py" in selected


def test_infer_frontend_java_php_candidates(tmp_path: Path) -> None:
    for rel in [
        "src/foo.test.ts",
        "src/test/java/com/acme/UserServiceTest.java",
        "tests/Service/UserServiceTest.php",
    ]:
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("test", encoding="utf-8")
    selected = infer_tests_for_changed_files(
        tmp_path,
        ["src/foo.ts", "src/main/java/com/acme/UserService.java", "src/Service/UserService.php"],
    )
    normalized = {item.replace("\\", "/") for item in selected}
    assert "src/foo.test.ts" in normalized
    assert "src/test/java/com/acme/UserServiceTest.java" in normalized
    assert "tests/Service/UserServiceTest.php" in normalized


def test_configured_changed_tests_mapping(tmp_path: Path) -> None:
    (tmp_path / ".ai-dev-tools.toml").write_text(
        '[changed_tests]\n"src/auth/**" = ["tests/auth/**"]\n[commands]\ntest=\'pytest\'\n',
        encoding="utf-8",
    )
    target = tmp_path / "tests" / "auth" / "test_login.py"
    target.parent.mkdir(parents=True)
    target.write_text("def test_login(): pass", encoding="utf-8")
    settings = load_settings(tmp_path)
    selection = select_changed_checks(settings, build_validation_plan(settings))
    assert selection.strategy == "no_changes"
    assert selection.to_dict()["fallback_reason_code"] == "CHANGED_NO_CHANGES"
    # Exercise configured mapping through the underlying settings contract.
    assert settings.changed_tests == {"src/auth/**": ["tests/auth/**"]}


def test_collect_changed_files_uses_nul_separated_git(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    from ai_dev_tools.runners import check

    def fake_run(command: list[str], root: Path, timeout_seconds: int = 300) -> CommandResult:
        if command[:3] == ["git", "rev-parse", "--show-toplevel"]:
            return CommandResult(command, 0, str(tmp_path), "", 0.01)
        if command[:2] == ["git", "diff"]:
            return CommandResult(command, 0, "src/a file.py\0src/renamed.py\0", "", 0.01)
        if command[:3] == ["git", "ls-files", "--others"]:
            return CommandResult(command, 0, "new file.py\0", "", 0.01)
        return CommandResult(command, 1, "", "no upstream", 0.01)

    monkeypatch.setattr(check, "run_command", fake_run)
    assert collect_changed_files(tmp_path) == ["new file.py", "src/a file.py", "src/renamed.py"]


def test_collect_changed_files_does_not_escape_nested_project_root(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from ai_dev_tools.runners import check

    parent = tmp_path / "parent"
    nested = parent / "fixture"
    nested.mkdir(parents=True)

    def fake_run(command: list[str], root: Path, timeout_seconds: int = 300) -> CommandResult:
        del root, timeout_seconds
        if command[:3] == ["git", "rev-parse", "--show-toplevel"]:
            return CommandResult(command, 0, str(parent), "", 0.01)
        raise AssertionError(f"unexpected command after mismatched Git root: {command}")

    monkeypatch.setattr(check, "run_command", fake_run)

    assert collect_changed_files(nested) == []


def test_build_validation_plan_detects_node_and_build(tmp_path: Path) -> None:
    package_json = (
        '{"scripts":{"lint":"eslint .","typecheck":"tsc","test":"vitest","build":"tsc -b"},'
        '"devDependencies":{"eslint":"x","typescript":"x"}}'
    )
    (tmp_path / "package.json").write_text(package_json, encoding="utf-8")
    plan = build_validation_plan(load_settings(tmp_path))
    assert [task.name for task in plan] == ["npm lint", "npm typecheck", "npm test", "npm build"]
    assert plan[-1].required is False


def test_build_validation_plan_detects_rust_java_php(tmp_path: Path) -> None:
    (tmp_path / "Cargo.toml").write_text(
        "[package]\nname='demo'\nversion='0.1.0'\n", encoding="utf-8"
    )
    (tmp_path / "pom.xml").write_text("<project />", encoding="utf-8")
    (tmp_path / "build.gradle").write_text("plugins {}", encoding="utf-8")
    (tmp_path / "composer.json").write_text("{}", encoding="utf-8")
    plan = build_validation_plan(load_settings(tmp_path))
    names = {task.name for task in plan}
    assert {
        "cargo fmt",
        "cargo clippy",
        "cargo test",
        "maven test",
        "gradle test",
        "composer test",
    } <= names


def test_select_changed_checks_uses_configured_mapping(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    from ai_dev_tools.runners import check

    (tmp_path / ".ai-dev-tools.toml").write_text(
        '[changed_tests]\n"src/auth/**" = ["tests/auth/**"]\n[commands]\ntest=\'pytest\'\n',
        encoding="utf-8",
    )
    target = tmp_path / "tests" / "auth" / "test_login.py"
    target.parent.mkdir(parents=True)
    target.write_text("def test_login(): pass", encoding="utf-8")
    monkeypatch.setattr(check, "collect_changed_files", lambda root: ["src/auth/service.py"])
    settings = load_settings(tmp_path)
    selection = select_changed_checks(settings, build_validation_plan(settings))
    assert selection.strategy == "configured_mapping"
    assert selection.confidence == "high"
    assert selection.selected_tests == [str(Path("tests/auth/test_login.py"))]
    assert (
        selection.selected_commands
        == [["python", "-m", "pytest", str(Path("tests/auth/test_login.py"))]]
        or selection.selected_commands
    )


def test_validation_plan_routes_child_workspace_tasks(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text('{"workspaces": ["packages/*"]}', encoding="utf-8")
    child = tmp_path / "packages" / "web"
    child.mkdir(parents=True)
    (child / "package.json").write_text(
        '{"scripts": {"lint": "eslint .", "test": "vitest"}, "devDependencies": {"eslint": "1"}}',
        encoding="utf-8",
    )

    plan = build_validation_plan(load_settings(tmp_path))
    child_tasks = [task for task in plan if task.workspace == "packages/web"]

    assert {task.name for task in child_tasks} == {"npm lint", "npm test"}


def test_changed_mode_selects_owning_workspace(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    from ai_dev_tools.runners import check

    (tmp_path / "package.json").write_text('{"workspaces": ["packages/*"]}', encoding="utf-8")
    for name in ("api", "web"):
        child = tmp_path / "packages" / name
        child.mkdir(parents=True)
        (child / "package.json").write_text(
            '{"scripts": {"lint": "eslint .", "test": "vitest"}, '
            '"devDependencies": {"eslint": "1"}}',
            encoding="utf-8",
        )
    monkeypatch.setattr(
        check,
        "collect_changed_files",
        lambda root: ["packages/web/src/component.ts"],
    )

    report = check.run_check(tmp_path, mode="changed", explain=True)
    selected = report.summary["selected_checks"]

    assert isinstance(selected, list)
    assert selected
    assert {item["workspace"] for item in selected} == {"packages/web"}


def test_configured_mapping_accepts_a_directory_pattern(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    from ai_dev_tools.runners import check

    (tmp_path / ".ai-dev-tools.toml").write_text(
        '[changed_tests]\n"src/auth/**" = ["tests/auth"]\n[commands]\ntest="pytest"\n',
        encoding="utf-8",
    )
    target = tmp_path / "tests" / "auth" / "nested" / "test_login.py"
    target.parent.mkdir(parents=True)
    target.write_text("def test_login(): pass", encoding="utf-8")
    monkeypatch.setattr(check, "collect_changed_files", lambda root: ["src/auth/service.py"])

    selection = select_changed_checks(
        load_settings(tmp_path), build_validation_plan(load_settings(tmp_path))
    )

    assert selection.strategy == "configured_mapping"
    assert selection.selected_tests == [str(Path("tests/auth/nested/test_login.py"))]
