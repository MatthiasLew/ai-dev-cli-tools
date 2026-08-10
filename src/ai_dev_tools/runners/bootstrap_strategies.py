from __future__ import annotations

import os
import sys
import tomllib
from dataclasses import replace
from pathlib import Path

from ai_dev_tools.config import BootstrapSettings, Settings, load_settings
from ai_dev_tools.detectors.workspaces import detect_workspaces
from ai_dev_tools.runners.bootstrap_models import BootstrapOptions, BootstrapPlan, BootstrapStep


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
    workspace_steps, workspace_smoke, workspace_tools = _workspace_bootstrap_steps(settings)
    if strategy is None and not workspace_steps:
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
    if strategy is None:
        project_type, package_manager = "monorepo", "multiple"
        steps: list[BootstrapStep] = []
        smoke: list[BootstrapStep] = []
        tools: list[str] = []
    else:
        project_type, package_manager, steps, smoke, tools = strategy
    if workspace_steps:
        project_type = "monorepo"
        package_manager = "multiple"
    return BootstrapPlan(
        project_type,
        package_manager,
        [*before, *env_step, *steps, *workspace_steps, *after],
        [*smoke, *workspace_smoke],
        sorted({*tools, *workspace_tools}),
        env_available,
        env_will_create,
        monorepo,
    )


def _workspace_bootstrap_steps(
    settings: Settings,
) -> tuple[list[BootstrapStep], list[BootstrapStep], list[str]]:
    steps: list[BootstrapStep] = []
    smoke_steps: list[BootstrapStep] = []
    tools: list[str] = []
    for workspace in detect_workspaces(settings.project_root):
        if not workspace.root:
            continue
        child_settings = load_settings(settings.project_root / workspace.root)
        strategy = _strategy_for_root(child_settings)
        if strategy is None:
            continue
        _, _, child_steps, child_smoke, child_tools = strategy
        steps.extend(
            replace(
                step,
                name=f"{workspace.workspace_id}: {step.name}",
                workspace=workspace.root,
            )
            for step in child_steps
        )
        smoke_steps.extend(
            replace(
                step,
                name=f"{workspace.workspace_id}: {step.name}",
                workspace=workspace.root,
            )
            for step in child_smoke
        )
        tools.extend(child_tools)
    return steps, smoke_steps, sorted(set(tools))


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
