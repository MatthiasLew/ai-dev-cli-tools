from __future__ import annotations

import os
import shutil
import sys
import tomllib
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

from ai_dev_tools.config import BootstrapSettings, Settings, load_settings
from ai_dev_tools.detectors.environment import run_doctor
from ai_dev_tools.detectors.project import scan_project
from ai_dev_tools.models.report import Artifact, Issue, Report
from ai_dev_tools.reporters.writer import write_json, write_markdown
from ai_dev_tools.utils.subprocess import CommandResult, run_command

BootstrapStatus = Literal["planned", "executed", "skipped", "failed"]


@dataclass(frozen=True, slots=True)
class BootstrapOptions:
    dry_run: bool = False
    explain: bool = False
    create_env: bool = False


@dataclass(frozen=True, slots=True)
class BootstrapStep:
    name: str
    command: list[str]
    reason: str
    source: str
    modifies_project: bool = True
    required_tool: str | None = None
    action: str = "command"

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class BootstrapPlan:
    project_type: str
    package_manager: str | None
    steps: list[BootstrapStep]
    smoke_steps: list[BootstrapStep]
    required_tools: list[str]
    env_available: bool = False
    env_will_create: bool = False
    monorepo_subprojects: list[str] | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "project_type": self.project_type,
            "package_manager": self.package_manager,
            "steps": [step.to_dict() for step in self.steps],
            "smoke_steps": [step.to_dict() for step in self.smoke_steps],
            "required_tools": self.required_tools,
            "env_available": self.env_available,
            "env_will_create": self.env_will_create,
            "monorepo_subprojects": self.monorepo_subprojects or [],
        }


def run_bootstrap(project_root: Path, options: BootstrapOptions) -> Report:
    settings = load_settings(project_root)
    report = Report(command="bootstrap", project_root=settings.project_root)
    scan = scan_project(settings.project_root)
    doctor = run_doctor(settings.project_root)
    plan = build_bootstrap_plan(settings, options)
    missing_tools = _missing_required_tools(plan, doctor)
    log_path = _log_path(settings.logs_directory)

    if settings.warnings:
        report.issues.extend(
            Issue("warning", warning, code="CONFIG_WARNING") for warning in settings.warnings
        )
    if not plan.steps and plan.project_type == "unknown":
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
        "explain": options.explain,
        "planned_commands": len(plan.steps),
        "executed_commands": len([item for item in executed if item["exit_code"] == 0]),
        "created_venv": created_venv,
        "created_env": created_env,
        "smoke_check": smoke_check,
        "plan": plan.to_dict(),
        "executed": executed,
        "missing_tools": missing_tools,
        "scan": scan.summary,
        "modifications": "NONE" if options.explain or options.dry_run else "PLANNED",
    }
    if log_path.exists():
        summary["full_log"] = str(log_path)
        report.artifacts.append(Artifact(str(log_path), "log", "Full bootstrap command output"))
    report.summary = summary
    report.finish()
    write_markdown(report, settings.reports_directory / "bootstrap-latest.md")
    write_json(report, settings.reports_directory / "bootstrap-latest.json")
    return report


def build_bootstrap_plan(settings: Settings, options: BootstrapOptions) -> BootstrapPlan:
    root = settings.project_root
    configured_create_env = settings.bootstrap.create_env or options.create_env
    before = _custom_steps(
        settings.bootstrap.commands_before, "configured bootstrap before command"
    )
    after = _custom_steps(settings.bootstrap.commands_after, "configured bootstrap after command")
    env_available = (root / ".env.example").exists()
    env_will_create = configured_create_env and env_available and not (root / ".env").exists()
    env_step = (
        [
            BootstrapStep(
                "create .env from example",
                ["copy", ".env.example", ".env"],
                "--create-env or [bootstrap].create_env enabled and .env is missing",
                "detected",
                modifies_project=True,
                action="copy_env",
            )
        ]
        if env_will_create
        else []
    )

    strategy = _strategy_for_root(settings)
    monorepo = _detect_subprojects(root)
    if strategy is None:
        return BootstrapPlan(
            "unknown",
            None,
            [*before, *env_step, *after],
            [],
            [],
            env_available,
            env_will_create,
            monorepo,
        )
    project_type, package_manager, steps, smoke, tools = strategy
    return BootstrapPlan(
        project_type,
        package_manager,
        [*before, *env_step, *steps, *after],
        smoke,
        tools,
        env_available,
        env_will_create,
        monorepo,
    )


def _strategy_for_root(
    settings: Settings,
) -> tuple[str, str, list[BootstrapStep], list[BootstrapStep], list[str]] | None:
    root = settings.project_root
    if (root / "uv.lock").exists() and (root / "pyproject.toml").exists():
        return _python_uv_strategy(root)
    if _is_poetry_project(root):
        return _python_poetry_strategy(root)
    if (root / "pyproject.toml").exists():
        return _python_pip_strategy(settings)
    if (root / "requirements.txt").exists():
        return _python_requirements_strategy(settings)
    if (root / "package.json").exists():
        return _node_strategy(root, settings.bootstrap)
    if (root / "pom.xml").exists():
        return _maven_strategy(root)
    if (root / "build.gradle").exists() or (root / "build.gradle.kts").exists():
        return _gradle_strategy(root)
    if (root / "Cargo.toml").exists():
        return _simple_strategy("rust", "cargo", "cargo fetch", ["cargo", "fetch"], "cargo")
    if (root / "composer.json").exists():
        return _simple_strategy(
            "php",
            "composer",
            "composer install --no-interaction",
            ["composer", "install", "--no-interaction"],
            "composer",
        )
    return None


def _python_uv_strategy(
    root: Path,
) -> tuple[str, str, list[BootstrapStep], list[BootstrapStep], list[str]]:
    return (
        "python",
        "uv",
        [
            BootstrapStep(
                "uv sync",
                ["uv", "sync"],
                "uv.lock and pyproject.toml detected",
                "detected",
                required_tool="uv",
            )
        ],
        _pytest_smoke(["uv", "run", "pytest", "--collect-only"], root, "uv"),
        ["uv"],
    )


def _python_poetry_strategy(
    root: Path,
) -> tuple[str, str, list[BootstrapStep], list[BootstrapStep], list[str]]:
    return (
        "python",
        "poetry",
        [
            BootstrapStep(
                "poetry install",
                ["poetry", "install"],
                "Poetry configuration detected",
                "detected",
                required_tool="poetry",
            )
        ],
        _pytest_smoke(["poetry", "run", "pytest", "--collect-only"], root, "poetry"),
        ["poetry"],
    )


def _python_pip_strategy(
    settings: Settings,
) -> tuple[str, str, list[BootstrapStep], list[BootstrapStep], list[str]]:
    root = settings.project_root
    venv_dir = root / settings.bootstrap.python_venv
    venv_python = _venv_python(settings.bootstrap.python_venv)
    steps: list[BootstrapStep] = []
    if not venv_dir.exists():
        steps.append(
            BootstrapStep(
                "create virtual environment",
                [sys.executable, "-m", "venv", settings.bootstrap.python_venv],
                "pip bootstrap uses an isolated local virtual environment",
                "detected",
                action="create_venv",
            )
        )
    steps.append(
        BootstrapStep(
            "upgrade pip",
            [venv_python, "-m", "pip", "install", "--upgrade", "pip"],
            "ensure local virtual environment has a current pip",
            "detected",
        )
    )
    if _is_installable_python_project(root):
        steps.append(
            BootstrapStep(
                "install project editable",
                [venv_python, "-m", "pip", "install", "-e", "."],
                "installable Python project metadata detected",
                "detected",
            )
        )
    return (
        "python",
        "pip",
        steps,
        _pytest_smoke([venv_python, "-m", "pytest", "--collect-only"], root, None),
        ["python"],
    )


def _python_requirements_strategy(
    settings: Settings,
) -> tuple[str, str, list[BootstrapStep], list[BootstrapStep], list[str]]:
    project_type, package_manager, steps, smoke, tools = _python_pip_strategy(settings)
    venv_python = _venv_python(settings.bootstrap.python_venv)
    steps.append(
        BootstrapStep(
            "install requirements",
            [venv_python, "-m", "pip", "install", "-r", "requirements.txt"],
            "requirements.txt detected",
            "detected",
        )
    )
    return project_type, package_manager, steps, smoke, tools


def _node_strategy(
    root: Path, bootstrap: BootstrapSettings
) -> tuple[str, str, list[BootstrapStep], list[BootstrapStep], list[str]]:
    package_text = (root / "package.json").read_text(encoding="utf-8", errors="replace")
    package_manager = _node_package_manager(root, package_text)
    command: list[str]
    reason: str
    if package_manager == "pnpm":
        command = ["pnpm", "install"]
        if bootstrap.node_frozen_lockfile and (root / "pnpm-lock.yaml").exists():
            command.append("--frozen-lockfile")
        reason = "pnpm lockfile or packageManager detected"
    elif package_manager == "yarn":
        command = ["yarn", "install"]
        if bootstrap.node_frozen_lockfile and (root / "yarn.lock").exists():
            command.append("--immutable")
        reason = "yarn lockfile or packageManager detected"
    else:
        command = ["npm", "ci"] if (root / "package-lock.json").exists() else ["npm", "install"]
        reason = "npm lockfile detected" if command[-1] == "ci" else "npm fallback without lockfile"
    return (
        "node",
        package_manager,
        [
            BootstrapStep(
                "install node dependencies",
                command,
                reason,
                "detected",
                required_tool=package_manager,
            )
        ],
        [],
        [package_manager],
    )


def _maven_strategy(
    root: Path,
) -> tuple[str, str, list[BootstrapStep], list[BootstrapStep], list[str]]:
    wrapper = _wrapper(root, "mvnw", "mvnw.cmd")
    command = [wrapper or "mvn", "dependency:go-offline"]
    tool = None if wrapper else "maven"
    return (
        "java",
        "maven",
        [
            BootstrapStep(
                "maven go offline",
                command,
                "pom.xml detected; wrapper preferred when present",
                "detected",
                required_tool=tool,
            )
        ],
        [],
        [] if wrapper else ["maven"],
    )


def _gradle_strategy(
    root: Path,
) -> tuple[str, str, list[BootstrapStep], list[BootstrapStep], list[str]]:
    wrapper = _wrapper(root, "gradlew", "gradlew.bat")
    command = [wrapper or "gradle", "dependencies"]
    tool = None if wrapper else "gradle"
    return (
        "java",
        "gradle",
        [
            BootstrapStep(
                "gradle dependencies",
                command,
                "Gradle build file detected; wrapper preferred when present",
                "detected",
                required_tool=tool,
            )
        ],
        [],
        [] if wrapper else ["gradle"],
    )


def _simple_strategy(
    project_type: str, package_manager: str, name: str, command: list[str], tool: str
) -> tuple[str, str, list[BootstrapStep], list[BootstrapStep], list[str]]:
    return (
        project_type,
        package_manager,
        [
            BootstrapStep(
                name,
                command,
                f"{package_manager} project file detected",
                "detected",
                required_tool=tool,
            )
        ],
        [],
        [tool],
    )


def _pytest_smoke(command: list[str], root: Path, tool: str | None) -> list[BootstrapStep]:
    if (root / "tests").exists() or "pytest" in _pyproject_text(root):
        return [
            BootstrapStep(
                "pytest collect only",
                command,
                "pytest configuration or tests directory detected",
                "detected",
                modifies_project=False,
                required_tool=tool,
            )
        ]
    return []


def _execute_step(step: BootstrapStep, settings: Settings, log_path: Path) -> CommandResult:
    if step.action == "copy_env":
        source = settings.project_root / ".env.example"
        target = settings.project_root / ".env"
        if target.exists():
            result = CommandResult(step.command, 0, "Skipped existing .env", "", 0.0)
        else:
            shutil.copyfile(source, target)
            result = CommandResult(step.command, 0, "Created .env from .env.example", "", 0.0)
    else:
        result = run_command(
            step.command, settings.project_root, settings.bootstrap.timeout_seconds
        )
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


def _custom_steps(commands: list[list[str]], reason: str) -> list[BootstrapStep]:
    return [
        BootstrapStep(
            "configured command",
            command,
            reason,
            "configured",
            required_tool=command[0] if command else None,
        )
        for command in commands
    ]


def _is_poetry_project(root: Path) -> bool:
    text = _pyproject_text(root)
    return "[tool.poetry]" in text or "poetry-core" in text


def _is_installable_python_project(root: Path) -> bool:
    if (root / "setup.py").exists() or (root / "setup.cfg").exists():
        return True
    try:
        data = tomllib.loads(_pyproject_text(root))
    except tomllib.TOMLDecodeError:
        return False
    return isinstance(data.get("project"), dict)


def _pyproject_text(root: Path) -> str:
    path = root / "pyproject.toml"
    return path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""


def _node_package_manager(root: Path, package_text: str) -> str:
    if (root / "pnpm-lock.yaml").exists():
        return "pnpm"
    if (root / "yarn.lock").exists():
        return "yarn"
    if (root / "package-lock.json").exists():
        return "npm"
    lowered = package_text.lower()
    if '"packagemanager"' in lowered:
        if "pnpm@" in lowered:
            return "pnpm"
        if "yarn@" in lowered:
            return "yarn"
    return "npm"


def _wrapper(root: Path, posix_name: str, windows_name: str) -> str | None:
    windows = root / windows_name
    posix = root / posix_name
    if os.name == "nt" and windows.exists():
        return windows_name
    if posix.exists():
        return f"./{posix_name}"
    if windows.exists():
        return windows_name
    return None


def _venv_python(venv: str) -> str:
    if os.name == "nt":
        return str(Path(venv) / "Scripts" / "python.exe")
    return str(Path(venv) / "bin" / "python")


def _detect_subprojects(root: Path) -> list[str]:
    signals = {
        "pyproject.toml",
        "requirements.txt",
        "package.json",
        "pom.xml",
        "build.gradle",
        "build.gradle.kts",
        "Cargo.toml",
        "composer.json",
    }
    found: list[str] = []
    for path in root.rglob("*"):
        if not path.is_file() or path.name not in signals:
            continue
        rel = path.relative_to(root)
        if len(rel.parts) <= 1 or any(
            part in {".git", "node_modules", ".venv"} for part in rel.parts
        ):
            continue
        found.append(str(rel.parent.as_posix()))
    return sorted(set(found))[:25]


def _log_path(logs_dir: Path) -> Path:
    return logs_dir / f"bootstrap-{datetime.now().strftime('%Y%m%d-%H%M%S-%f')}.log"
