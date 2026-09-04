from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DEFAULT_IGNORES = {
    ".ai",
    ".ai/logs",
    ".ai/reports",
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    ".venv*",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
    "venv",
    "venv*",
}


@dataclass(slots=True)
class BootstrapSettings:
    create_env: bool = False
    run_smoke_check: bool = True
    timeout_seconds: int = 900
    commands_before: list[list[str]] = field(default_factory=list)
    commands_after: list[list[str]] = field(default_factory=list)
    python_venv: str = ".venv"
    node_frozen_lockfile: bool = True


@dataclass(slots=True)
class ExecutionSettings:
    mode: str = "audit"
    allow_prefixes: list[str] = field(default_factory=list)
    deny_prefixes: list[str] = field(default_factory=list)
    maximum_impact: str = "high"


@dataclass(slots=True)
class Settings:
    project_root: Path
    reports_directory: Path
    logs_directory: Path
    commands: dict[str, str] = field(default_factory=dict)
    ignore_paths: set[str] = field(default_factory=lambda: set(DEFAULT_IGNORES))
    project_name: str | None = None
    changed_tests: dict[str, list[str]] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    bootstrap: BootstrapSettings = field(default_factory=BootstrapSettings)
    performance_budgets: dict[str, float] = field(default_factory=dict)
    performance_retention: int = 50
    execution: ExecutionSettings = field(default_factory=ExecutionSettings)


def load_settings(project_root: Path) -> Settings:
    root = project_root.resolve()
    data: dict[str, Any] = {}
    config_path = root / ".ai-dev-tools.toml"
    if config_path.exists():
        data = tomllib.loads(config_path.read_text(encoding="utf-8"))

    reports = _section(data, "reports")
    ignore = _section(data, "ignore")
    commands = _section(data, "commands")
    project = _section(data, "project")
    bootstrap = _bootstrap_settings(data)
    performance = _section(data, "performance")

    reports_dir = Path(_string_value(reports, "directory", ".ai/reports"))
    logs_dir = Path(_string_value(reports, "logs_directory", ".ai/logs"))
    ignore_paths = set(DEFAULT_IGNORES)
    ignore_paths.update(_string_list(ignore, "paths"))

    warnings = _config_warnings(data)
    changed_tests = _changed_tests(data)

    return Settings(
        project_root=root,
        reports_directory=(root / reports_dir).resolve(),
        logs_directory=(root / logs_dir).resolve(),
        commands={key: value for key, value in commands.items() if isinstance(value, str)},
        ignore_paths=ignore_paths,
        project_name=_optional_string(project, "name"),
        changed_tests=changed_tests,
        warnings=warnings,
        bootstrap=bootstrap,
        performance_budgets=_performance_budgets(data),
        performance_retention=_int_value(performance, "retention", 50),
        execution=_execution_settings(data),
    )


def _section(data: dict[str, Any], key: str) -> dict[str, Any]:
    value = data.get(key, {})
    return value if isinstance(value, dict) else {}


def _string_value(data: dict[str, Any], key: str, default: str) -> str:
    value = data.get(key, default)
    return value if isinstance(value, str) else default


def _optional_string(data: dict[str, Any], key: str) -> str | None:
    value = data.get(key)
    return value if isinstance(value, str) else None


def _string_list(data: dict[str, Any], key: str) -> list[str]:
    value = data.get(key, [])
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _config_warnings(data: dict[str, Any]) -> list[str]:
    known = {
        "project",
        "commands",
        "ignore",
        "reports",
        "changed_tests",
        "bootstrap",
        "performance",
        "execution",
    }
    warnings = [f"Unknown top-level config key: {key}" for key in sorted(data) if key not in known]
    for section in known & data.keys():
        if not isinstance(data[section], dict):
            warnings.append(f"Config section [{section}] must be a table")
    warnings.extend(_table_string_warnings(data, "commands"))
    warnings.extend(_table_string_warnings(data, "project", allowed_keys={"name"}))
    warnings.extend(
        _table_string_warnings(data, "reports", allowed_keys={"directory", "logs_directory"})
    )
    warnings.extend(_path_list_warning(data, "ignore", "paths"))
    warnings.extend(_bootstrap_warnings(data))
    warnings.extend(_performance_warnings(data))
    warnings.extend(_execution_warnings(data))
    return warnings


def _execution_settings(data: dict[str, Any]) -> ExecutionSettings:
    raw = _section(data, "execution")
    mode = _string_value(raw, "mode", "audit")
    maximum = _string_value(raw, "maximum_impact", "high")
    return ExecutionSettings(
        mode=mode if mode in {"audit", "enforce"} else "audit",
        allow_prefixes=_string_list(raw, "allow_prefixes"),
        deny_prefixes=_string_list(raw, "deny_prefixes"),
        maximum_impact=(
            maximum if maximum in {"low", "medium", "high", "critical"} else "high"
        ),
    )


def _execution_warnings(data: dict[str, Any]) -> list[str]:
    raw = data.get("execution", {})
    if not isinstance(raw, dict):
        return []
    warnings = [
        f"Unknown config key: [execution].{key}"
        for key in sorted(raw)
        if key not in {"mode", "allow_prefixes", "deny_prefixes", "maximum_impact"}
    ]
    if raw.get("mode", "audit") not in {"audit", "enforce"}:
        warnings.append("Config value [execution].mode must be audit or enforce")
    if raw.get("maximum_impact", "high") not in {"low", "medium", "high", "critical"}:
        warnings.append(
            "Config value [execution].maximum_impact must be low, medium, high, or critical"
        )
    warnings.extend(_path_list_warning(data, "execution", "allow_prefixes"))
    warnings.extend(_path_list_warning(data, "execution", "deny_prefixes"))
    return warnings


def _performance_budgets(data: dict[str, Any]) -> dict[str, float]:
    raw = _section(_section(data, "performance"), "budgets")
    return {
        key: float(value)
        for key, value in raw.items()
        if isinstance(key, str)
        and isinstance(value, (int, float))
        and not isinstance(value, bool)
        and value > 0
    }


def _performance_warnings(data: dict[str, Any]) -> list[str]:
    raw = data.get("performance", {})
    if not isinstance(raw, dict):
        return []
    warnings = [
        f"Unknown config key: [performance].{key}"
        for key in sorted(raw)
        if key not in {"retention", "budgets"}
    ]
    if "retention" in raw and (
        not isinstance(raw["retention"], int)
        or isinstance(raw["retention"], bool)
        or raw["retention"] <= 0
    ):
        warnings.append("Config value [performance].retention must be a positive integer")
    budgets = raw.get("budgets", {})
    if "budgets" in raw and not isinstance(budgets, dict):
        warnings.append("Config value [performance].budgets must be a table")
    elif isinstance(budgets, dict):
        for key, value in budgets.items():
            if not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0:
                warnings.append(
                    f"Config value [performance.budgets].{key} must be a positive number"
                )
    return warnings


def _table_string_warnings(
    data: dict[str, Any], section: str, allowed_keys: set[str] | None = None
) -> list[str]:
    raw = data.get(section, {})
    if not isinstance(raw, dict):
        return []
    warnings: list[str] = []
    for key, value in raw.items():
        if allowed_keys is not None and key not in allowed_keys:
            warnings.append(f"Unknown config key: [{section}].{key}")
        if not isinstance(value, str):
            warnings.append(f"Config value [{section}].{key} must be a string")
    return warnings


def _path_list_warning(data: dict[str, Any], section: str, key: str) -> list[str]:
    raw = data.get(section, {})
    if not isinstance(raw, dict) or key not in raw:
        return []
    value = raw[key]
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        return [f"Config value [{section}].{key} must be a list of strings"]
    return []


def _changed_tests(data: dict[str, Any]) -> dict[str, list[str]]:
    raw = data.get("changed_tests", {})
    if not isinstance(raw, dict):
        return {}
    result: dict[str, list[str]] = {}
    for key, value in raw.items():
        if (
            isinstance(key, str)
            and isinstance(value, list)
            and all(isinstance(item, str) for item in value)
        ):
            result[key] = value
    return result


def _bootstrap_settings(data: dict[str, Any]) -> BootstrapSettings:
    bootstrap = _section(data, "bootstrap")
    commands = _section(bootstrap, "commands")
    python = _section(bootstrap, "python")
    node = _section(bootstrap, "node")
    return BootstrapSettings(
        create_env=_bool_value(bootstrap, "create_env", False),
        run_smoke_check=_bool_value(bootstrap, "run_smoke_check", True),
        timeout_seconds=_int_value(bootstrap, "timeout_seconds", 900),
        commands_before=_command_list(commands, "before"),
        commands_after=_command_list(commands, "after"),
        python_venv=_string_value(python, "venv", ".venv"),
        node_frozen_lockfile=_bool_value(node, "frozen_lockfile", True),
    )


def _bool_value(data: dict[str, Any], key: str, default: bool) -> bool:
    value = data.get(key, default)
    return value if isinstance(value, bool) else default


def _int_value(data: dict[str, Any], key: str, default: int) -> int:
    value = data.get(key, default)
    return (
        value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else default
    )


def _command_list(data: dict[str, Any], key: str) -> list[list[str]]:
    value = data.get(key, [])
    if not isinstance(value, list):
        return []
    commands: list[list[str]] = []
    for item in value:
        if isinstance(item, list) and item and all(isinstance(arg, str) for arg in item):
            commands.append(item)
    return commands


def _bootstrap_warnings(data: dict[str, Any]) -> list[str]:
    raw = data.get("bootstrap", {})
    if not isinstance(raw, dict):
        return []
    allowed = {"create_env", "run_smoke_check", "timeout_seconds", "commands", "python", "node"}
    warnings = [
        f"Unknown config key: [bootstrap].{key}" for key in sorted(raw) if key not in allowed
    ]
    commands = _section(raw, "commands")
    for key in ("before", "after"):
        value = commands.get(key, [])
        invalid_commands = not isinstance(value, list) or not all(
            isinstance(item, list) and item and all(isinstance(arg, str) for arg in item)
            for item in value
        )
        if key in commands and invalid_commands:
            warnings.append(
                f"Config value [bootstrap.commands].{key} must be a list of argument lists"
            )
    python = _section(raw, "python")
    if "venv" in python and not isinstance(python["venv"], str):
        warnings.append("Config value [bootstrap.python].venv must be a string")
    node = _section(raw, "node")
    if "frozen_lockfile" in node and not isinstance(node["frozen_lockfile"], bool):
        warnings.append("Config value [bootstrap.node].frozen_lockfile must be a boolean")
    return warnings
