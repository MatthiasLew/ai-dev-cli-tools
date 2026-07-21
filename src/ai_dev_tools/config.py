from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DEFAULT_IGNORES = {
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

    return Settings(
        project_root=root,
        reports_directory=(root / reports_dir).resolve(),
        logs_directory=(root / logs_dir).resolve(),
        commands=dict(data.get("commands", {})),
        ignore_paths=ignore_paths,
        project_name=data.get("project", {}).get("name"),
    )
