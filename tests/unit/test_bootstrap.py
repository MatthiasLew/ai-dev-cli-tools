from __future__ import annotations

import sys
from pathlib import Path

import ai_dev_tools.runners.bootstrap as boot
from ai_dev_tools.config import load_settings
from ai_dev_tools.models.report import Report
from ai_dev_tools.runners.bootstrap import BootstrapOptions, build_bootstrap_plan, run_bootstrap
from ai_dev_tools.utils.subprocess import CommandResult


def _ok_doctor(root: Path, tools: dict[str, str] | None = None) -> Report:
    tools = tools or {}
    report = Report(command="doctor", project_root=root)
    names = ["uv", "poetry", "npm", "pnpm", "yarn", "maven", "gradle", "cargo", "composer"]
    report.summary = {
        "tools": {
            name: {"status": tools.get(name, "ok"), "version": "test", "path": name}
            for name in names
        }
    }
    return report.finish()


def test_bootstrap_python_uv_plan(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    (tmp_path / "uv.lock").write_text("", encoding="utf-8")
    plan = build_bootstrap_plan(load_settings(tmp_path), BootstrapOptions(explain=True))
    assert plan.project_type == "python"
    assert plan.package_manager == "uv"
    assert plan.steps[0].command == ["uv", "sync"]


def test_bootstrap_python_poetry_plan(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[tool.poetry]\nname='x'\n", encoding="utf-8")
    plan = build_bootstrap_plan(load_settings(tmp_path), BootstrapOptions(explain=True))
    assert plan.package_manager == "poetry"
    assert plan.steps[0].command == ["poetry", "install"]


def test_bootstrap_python_requirements_plan(tmp_path: Path) -> None:
    (tmp_path / "requirements.txt").write_text("pytest\n", encoding="utf-8")
    plan = build_bootstrap_plan(load_settings(tmp_path), BootstrapOptions(explain=True))
    commands = [step.command for step in plan.steps]
    assert commands[0][:4] == [sys.executable, "-m", "venv", ".venv"]
    assert commands[1][1:4] == ["-m", "pip", "install"]
    assert commands[-1][-2:] == ["-r", "requirements.txt"]


def test_bootstrap_python_pyproject_installable_plan(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    plan = build_bootstrap_plan(load_settings(tmp_path), BootstrapOptions(explain=True))
    assert any(step.command[-2:] == ["-e", "."] for step in plan.steps)


def test_bootstrap_node_npm_plan(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text('{"scripts":{"test":"vitest"}}', encoding="utf-8")
    (tmp_path / "package-lock.json").write_text("{}", encoding="utf-8")
    plan = build_bootstrap_plan(load_settings(tmp_path), BootstrapOptions(explain=True))
    assert plan.package_manager == "npm"
    assert plan.steps[0].command == ["npm", "ci"]


def test_bootstrap_node_pnpm_plan(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text("{}", encoding="utf-8")
    (tmp_path / "pnpm-lock.yaml").write_text("lockfileVersion: '9'\n", encoding="utf-8")
    plan = build_bootstrap_plan(load_settings(tmp_path), BootstrapOptions(explain=True))
    assert plan.package_manager == "pnpm"
    assert plan.steps[0].command == ["pnpm", "install", "--frozen-lockfile"]


def test_bootstrap_node_yarn_plan(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text("{}", encoding="utf-8")
    (tmp_path / "yarn.lock").write_text("", encoding="utf-8")
    plan = build_bootstrap_plan(load_settings(tmp_path), BootstrapOptions(explain=True))
    assert plan.package_manager == "yarn"
    assert plan.steps[0].command == ["yarn", "install", "--immutable"]


def test_bootstrap_maven_wrapper_plan(tmp_path: Path) -> None:
    (tmp_path / "pom.xml").write_text("<project />", encoding="utf-8")
    (tmp_path / "mvnw.cmd").write_text("", encoding="utf-8")
    plan = build_bootstrap_plan(load_settings(tmp_path), BootstrapOptions(explain=True))
    assert plan.package_manager == "maven"
    assert plan.required_tools == []
    assert plan.steps[0].command[0] == "mvnw.cmd"


def test_bootstrap_system_maven_plan(tmp_path: Path) -> None:
    (tmp_path / "pom.xml").write_text("<project />", encoding="utf-8")
    plan = build_bootstrap_plan(load_settings(tmp_path), BootstrapOptions(explain=True))
    assert plan.steps[0].command == ["mvn", "dependency:go-offline"]
    assert plan.required_tools == ["maven"]


def test_bootstrap_gradle_wrapper_plan(tmp_path: Path) -> None:
    (tmp_path / "build.gradle").write_text("plugins {}", encoding="utf-8")
    (tmp_path / "gradlew.bat").write_text("", encoding="utf-8")
    plan = build_bootstrap_plan(load_settings(tmp_path), BootstrapOptions(explain=True))
    assert plan.required_tools == []
    assert plan.steps[0].command[0] == "gradlew.bat"


def test_bootstrap_system_gradle_plan(tmp_path: Path) -> None:
    (tmp_path / "build.gradle.kts").write_text("plugins {}", encoding="utf-8")
    plan = build_bootstrap_plan(load_settings(tmp_path), BootstrapOptions(explain=True))
    assert plan.steps[0].command == ["gradle", "dependencies"]
    assert plan.required_tools == ["gradle"]


def test_bootstrap_cargo_and_composer_plans(tmp_path: Path) -> None:
    rust = tmp_path / "rust"
    php = tmp_path / "php"
    rust.mkdir()
    php.mkdir()
    (rust / "Cargo.toml").write_text("[package]\nname='x'\nversion='0.1.0'\n", encoding="utf-8")
    (php / "composer.json").write_text("{}", encoding="utf-8")
    rust_plan = build_bootstrap_plan(load_settings(rust), BootstrapOptions(explain=True))
    php_plan = build_bootstrap_plan(load_settings(php), BootstrapOptions(explain=True))
    assert rust_plan.steps[0].command == ["cargo", "fetch"]
    assert php_plan.steps[0].command == ["composer", "install", "--no-interaction"]


def test_bootstrap_blocks_missing_runtime(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    (tmp_path / "Cargo.toml").write_text("[package]\nname='x'\nversion='0.1.0'\n", encoding="utf-8")
    monkeypatch.setattr(boot, "run_doctor", lambda root: _ok_doctor(root, {"cargo": "missing"}))
    report = run_bootstrap(tmp_path, BootstrapOptions(explain=True))
    assert report.status == "blocked"
    assert report.summary["missing_tools"] == ["cargo"]


def test_bootstrap_blocks_without_strategy(tmp_path: Path) -> None:
    report = run_bootstrap(tmp_path, BootstrapOptions(explain=True))
    assert report.status == "blocked"
    assert report.summary["project_type"] == "unknown"


def test_bootstrap_env_default_does_not_create(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    (tmp_path / ".env.example").write_text("TOKEN=\n", encoding="utf-8")
    plan = build_bootstrap_plan(load_settings(tmp_path), BootstrapOptions(explain=True))
    assert plan.env_available is True
    assert plan.env_will_create is False


def test_bootstrap_existing_env_is_not_overwritten(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    (tmp_path / ".env.example").write_text("TOKEN=example\n", encoding="utf-8")
    (tmp_path / ".env").write_text("TOKEN=real\n", encoding="utf-8")
    plan = build_bootstrap_plan(load_settings(tmp_path), BootstrapOptions(create_env=True))
    assert plan.env_will_create is False


def test_bootstrap_create_env_executes_without_overwriting(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    (tmp_path / ".env.example").write_text("TOKEN=example\n", encoding="utf-8")
    monkeypatch.setattr(boot, "run_doctor", lambda root: _ok_doctor(root))
    monkeypatch.setattr(
        boot,
        "run_command",
        lambda command, cwd, timeout_seconds=300: CommandResult(command, 0, "ok", "", 0.01),
    )
    report = run_bootstrap(tmp_path, BootstrapOptions(create_env=True))
    assert report.status == "success"
    assert report.summary["created_env"] is True
    assert (tmp_path / ".env").read_text(encoding="utf-8") == "TOKEN=example\n"


def test_bootstrap_dry_run_executes_nothing(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    (tmp_path / "package.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(boot, "run_doctor", lambda root: _ok_doctor(root))
    report = run_bootstrap(tmp_path, BootstrapOptions(dry_run=True))
    assert report.summary["dry_run"] is True
    assert report.summary["executed_commands"] == 0
    assert report.summary["planned_commands"] == 1


def test_bootstrap_explain_does_not_create_venv(tmp_path: Path) -> None:
    project = tmp_path / "project with spaces"
    project.mkdir()
    (project / "requirements.txt").write_text("pytest\n", encoding="utf-8")
    report = run_bootstrap(project, BootstrapOptions(explain=True))
    assert report.summary["explain"] is True
    assert not (project / ".venv").exists()


def test_bootstrap_timeout_reports_failed(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    monkeypatch.setattr(boot, "run_doctor", lambda root: _ok_doctor(root))
    monkeypatch.setattr(
        boot,
        "run_command",
        lambda command, cwd, timeout_seconds=300: CommandResult(
            command, 124, "", "timeout", 1.0, True
        ),
    )
    report = run_bootstrap(tmp_path, BootstrapOptions())
    assert report.status == "failed"
    assert report.exit_code == 124
    assert report.summary["executed"][0]["timed_out"] is True


def test_bootstrap_invalid_config_warns(tmp_path: Path) -> None:
    (tmp_path / ".ai-dev-tools.toml").write_text(
        "[bootstrap.commands]\nbefore = 'bad'\n", encoding="utf-8"
    )
    (tmp_path / "package.json").write_text("{}", encoding="utf-8")
    report = run_bootstrap(tmp_path, BootstrapOptions(dry_run=True))
    assert any(issue.code == "CONFIG_WARNING" for issue in report.issues)


def test_bootstrap_monorepo_reports_subprojects(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='root'\n", encoding="utf-8")
    app = tmp_path / "apps" / "web"
    app.mkdir(parents=True)
    (app / "package.json").write_text("{}", encoding="utf-8")
    plan = build_bootstrap_plan(load_settings(tmp_path), BootstrapOptions(explain=True))
    assert plan.monorepo_subprojects == ["apps/web"]
