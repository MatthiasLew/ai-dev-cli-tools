from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from ai_dev_tools.config import load_settings
from ai_dev_tools.detectors.runtime import (
    detect_runtime_requirements,
    evaluate_requirement,
)
from ai_dev_tools.models.report import Report
from ai_dev_tools.reporters.writer import write_json, write_markdown
from ai_dev_tools.utils.subprocess import run_command


@dataclass(frozen=True, slots=True)
class ToolSpec:
    name: str
    executable: str
    version_command: list[str]
    required: bool = False


TOOLS: tuple[ToolSpec, ...] = (
    ToolSpec("git", "git", ["git", "--version"], required=True),
    ToolSpec("python", "python", ["python", "--version"], required=True),
    ToolSpec("uv", "uv", ["uv", "--version"]),
    ToolSpec("poetry", "poetry", ["poetry", "--version"]),
    ToolSpec("node", "node", ["node", "--version"]),
    ToolSpec("npm", "npm", ["npm", "--version"]),
    ToolSpec("pnpm", "pnpm", ["pnpm", "--version"]),
    ToolSpec("yarn", "yarn", ["yarn", "--version"]),
    ToolSpec("java", "java", ["java", "--version"]),
    ToolSpec("maven", "mvn", ["mvn", "--version"]),
    ToolSpec("gradle", "gradle", ["gradle", "--version"]),
    ToolSpec("php", "php", ["php", "--version"]),
    ToolSpec("composer", "composer", ["composer", "--version"]),
    ToolSpec("rust", "rustc", ["rustc", "--version"]),
    ToolSpec("cargo", "cargo", ["cargo", "--version"]),
    ToolSpec("docker", "docker", ["docker", "--version"]),
    ToolSpec("docker_compose", "docker", ["docker", "compose", "version"]),
    ToolSpec("github_cli", "gh", ["gh", "--version"]),
)


def run_doctor(project_root: Path) -> Report:
    settings = load_settings(project_root)
    report = Report(command="doctor", project_root=settings.project_root)
    tools: dict[str, dict[str, str | bool | None]] = {}
    for spec in TOOLS:
        path = shutil.which(spec.executable)
        if path is None:
            tools[spec.name] = {
                "status": "missing",
                "version": None,
                "path": None,
                "required": spec.required,
            }
            continue
        result = run_command(spec.version_command, project_root, timeout_seconds=20)
        version = (
            (result.stdout or result.stderr).splitlines()[0]
            if result.combined_output
            else "available"
        )
        status = "ok" if result.exit_code == 0 else "error"
        tools[spec.name] = {
            "status": status,
            "version": version,
            "path": path,
            "required": spec.required,
        }
    requirements = detect_runtime_requirements(settings.project_root)
    runtime_compatibility = [
        evaluate_requirement(
            requirement,
            str(tools.get(requirement.runtime, {}).get("version"))
            if tools.get(requirement.runtime, {}).get("version")
            else None,
        )
        for requirement in requirements
    ]
    incompatible_runtimes = [
        item for item in runtime_compatibility if item["status"] == "incompatible"
    ]
    missing_project_runtimes = [
        item for item in runtime_compatibility if item["status"] == "missing"
    ]
    report.summary = {
        "tools": tools,
        "missing_required": [
            k for k, v in tools.items() if v["required"] and v["status"] == "missing"
        ],
        "missing_optional": [
            k for k, v in tools.items() if not v["required"] and v["status"] == "missing"
        ],
        "errors_required": [
            k for k, v in tools.items() if v["required"] and v["status"] == "error"
        ],
        "runtime_requirements": [item.to_dict() for item in requirements],
        "runtime_compatibility": runtime_compatibility,
        "incompatible_runtimes": incompatible_runtimes,
        "missing_project_runtimes": missing_project_runtimes,
        "errors_optional": [
            k for k, v in tools.items() if not v["required"] and v["status"] == "error"
        ],
    }
    report.status = (
        "failed"
        if (
            report.summary["missing_required"]
            or report.summary["errors_required"]
            or incompatible_runtimes
            or missing_project_runtimes
        )
        else "warning"
        if report.summary["errors_optional"]
        else "success"
    )
    report.finish()
    write_markdown(report, settings.reports_directory / "doctor.md")
    write_json(report, settings.reports_directory / "doctor.json")
    return report
