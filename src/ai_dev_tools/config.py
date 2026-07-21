from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DEFAULT_IGNORES = {
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

    reports_dir = Path(data.get("reports", {}).get("directory", ".ai/reports"))
    logs_dir = Path(data.get("reports", {}).get("logs_directory", ".ai/logs"))
    ignore_paths = set(DEFAULT_IGNORES)
    ignore_paths.update(data.get("ignore", {}).get("paths", []))

    warnings = _config_warnings(data)
    changed_tests = _changed_tests(data)

    return Settings(
        project_root=root,
        reports_directory=(root / reports_dir).resolve(),
        logs_directory=(root / logs_dir).resolve(),
        commands=dict(data.get("commands", {})),
        ignore_paths=ignore_paths,
        project_name=data.get("project", {}).get("name"),
        changed_tests=changed_tests,
        warnings=warnings,
    )


def _config_warnings(data: dict[str, Any]) -> list[str]:
    known = {"project", "commands", "ignore", "reports", "changed_tests"}
    return [f"Unknown top-level config key: {key}" for key in sorted(data) if key not in known]


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
