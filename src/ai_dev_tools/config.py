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
    "__pycache__",
    "build",
    "dist",
    "node_modules",
    "venv",
}


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
    known = {"project", "commands", "ignore", "reports", "changed_tests"}
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
