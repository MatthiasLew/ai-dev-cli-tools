from __future__ import annotations

import shutil
from pathlib import Path

from ai_dev_tools.models.report import Report
from ai_dev_tools.utils.subprocess import run_command

TOOLS: tuple[tuple[str, str, list[str]], ...] = (
    ("git", "git", ["git", "--version"]),
    ("python", "python", ["python", "--version"]),
    ("node", "node", ["node", "--version"]),
    ("npm", "npm", ["npm", "--version"]),
    ("pnpm", "pnpm", ["pnpm", "--version"]),
    ("yarn", "yarn", ["yarn", "--version"]),
    ("java", "java", ["java", "--version"]),
    ("maven", "mvn", ["mvn", "--version"]),
    ("gradle", "gradle", ["gradle", "--version"]),
    ("php", "php", ["php", "--version"]),
    ("composer", "composer", ["composer", "--version"]),
    ("rust", "rustc", ["rustc", "--version"]),
    ("cargo", "cargo", ["cargo", "--version"]),
    ("docker", "docker", ["docker", "--version"]),
    ("docker_compose", "docker", ["docker", "compose", "version"]),
    ("github_cli", "gh", ["gh", "--version"]),
)


def run_doctor(project_root: Path) -> Report:
    report = Report(command="doctor", project_root=project_root)
    tools: dict[str, dict[str, str | bool | None]] = {}
    for name, executable, version_command in TOOLS:
        path = shutil.which(executable)
        if path is None:
            tools[name] = {"status": "missing", "version": None, "path": None, "required": False}
            continue
        result = run_command(version_command, project_root, timeout_seconds=20)
        version = (
            (result.stdout or result.stderr).splitlines()[0]
            if result.combined_output
            else "available"
        )
        tools[name] = {"status": "ok", "version": version, "path": path, "required": False}
    report.summary = {
        "tools": tools,
        "missing_optional": [k for k, v in tools.items() if v["status"] == "missing"],
    }
    return report
