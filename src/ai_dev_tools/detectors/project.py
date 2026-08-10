from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

from ai_dev_tools.config import load_settings
from ai_dev_tools.detectors.runtime import detect_runtime_requirements
from ai_dev_tools.detectors.workspaces import detect_workspaces
from ai_dev_tools.models.report import Report
from ai_dev_tools.reporters.writer import write_json, write_markdown

SIGNALS = {
    "pyproject.toml": "python",
    "requirements.txt": "python",
    "Pipfile": "python",
    "package.json": "javascript",
    "pnpm-lock.yaml": "javascript",
    "yarn.lock": "javascript",
    "pom.xml": "java",
    "build.gradle": "java",
    "build.gradle.kts": "java",
    "Cargo.toml": "rust",
    "composer.json": "php",
    "Dockerfile": "docker",
    "compose.yaml": "docker",
    "docker-compose.yml": "docker",
    "Makefile": "make",
}
FRAMEWORK_HINTS = {
    "django": "Django",
    "flask": "Flask",
    "fastapi": "FastAPI",
    "react": "React",
    "next": "Next.js",
    "vue": "Vue",
    "svelte": "Svelte",
    "express": "Express",
    "spring-boot": "Spring Boot",
    "laravel": "Laravel",
}


def scan_project(project_root: Path, *, write_reports: bool = True) -> Report:
    settings = load_settings(project_root)
    report = Report(command="scan", project_root=settings.project_root)
    files = {path.name: path for path in settings.project_root.iterdir() if path.is_file()}
    scripts = _detect_scripts(settings.project_root)
    dependencies = _dependency_names(settings.project_root)
    workspaces = detect_workspaces(settings.project_root)
    runtime_requirements = detect_runtime_requirements(settings.project_root)
    report.summary = {
        "project_name": settings.project_name or settings.project_root.name,
        "languages": sorted({language for name, language in SIGNALS.items() if name in files}),
        "frameworks": sorted(
            {label for dep, label in FRAMEWORK_HINTS.items() if dep in dependencies}
        ),
        "package_managers": _detect_package_managers(files),
        "entrypoints": _entrypoints(settings.project_root, scripts),
        "tests": _matching_scripts(scripts, ("test", "pytest", "phpunit")),
        "lint": _matching_scripts(scripts, ("lint", "ruff", "eslint", "checkstyle", "clippy")),
        "formatter": _matching_scripts(
            scripts, ("format", "fmt", "black", "prettier", "php-cs-fixer")
        ),
        "type_checker": _matching_scripts(scripts, ("type", "mypy", "tsc", "phpstan")),
        "run": _matching_scripts(scripts, ("start", "dev", "serve", "run")),
        "ci": sorted(
            str(path.relative_to(settings.project_root))
            for path in (settings.project_root / ".github" / "workflows").glob("*.y*ml")
        ),
        "docker": any(
            name in files for name in ("Dockerfile", "compose.yaml", "docker-compose.yml")
        ),
        "env_example_variables": _env_examples(settings.project_root),
        "config_files": sorted(name for name in files if name in SIGNALS or name.startswith(".")),
        "config_warnings": settings.warnings,
        "runtime_requirements": [requirement.to_dict() for requirement in runtime_requirements],
        "workspaces": [workspace.to_dict() for workspace in workspaces],
        "workspace_count": len(workspaces),
    }
    report.finish()
    if write_reports:
        write_markdown(report, settings.reports_directory / "project-scan.md")
        write_json(report, settings.reports_directory / "project-scan.json")
    return report


def _detect_package_managers(files: dict[str, Path]) -> list[str]:
    pairs = [
        ("pyproject.toml", "pip/pyproject"),
        ("requirements.txt", "pip"),
        ("package.json", "npm"),
        ("pnpm-lock.yaml", "pnpm"),
        ("yarn.lock", "yarn"),
        ("pom.xml", "maven"),
        ("Cargo.toml", "cargo"),
        ("composer.json", "composer"),
    ]
    managers = [manager for filename, manager in pairs if filename in files]
    if "build.gradle" in files or "build.gradle.kts" in files:
        managers.append("gradle")
    return managers


def _detect_scripts(root: Path) -> dict[str, str]:
    scripts: dict[str, str] = {}
    package_json = root / "package.json"
    if package_json.exists():
        try:
            package = json.loads(package_json.read_text(encoding="utf-8"))
            scripts.update({f"npm:{k}": str(v) for k, v in package.get("scripts", {}).items()})
        except json.JSONDecodeError:
            pass
    pyproject = root / "pyproject.toml"
    if pyproject.exists():
        try:
            data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
            scripts.update(
                {
                    f"python:{k}": str(v)
                    for k, v in data.get("project", {}).get("scripts", {}).items()
                }
            )
        except tomllib.TOMLDecodeError:
            pass
    makefile = root / "Makefile"
    if makefile.exists():
        for line in makefile.read_text(encoding="utf-8", errors="replace").splitlines():
            match = re.match(r"^([A-Za-z0-9_.-]+):", line)
            if match:
                scripts[f"make:{match.group(1)}"] = f"make {match.group(1)}"
    return scripts


def _dependency_names(root: Path) -> set[str]:
    names: set[str] = set()
    package_json = root / "package.json"
    if package_json.exists():
        try:
            package = json.loads(package_json.read_text(encoding="utf-8"))
            names.update(package.get("dependencies", {}))
            names.update(package.get("devDependencies", {}))
        except json.JSONDecodeError:
            pass
    pyproject = root / "pyproject.toml"
    if pyproject.exists():
        try:
            data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
            for dep in data.get("project", {}).get("dependencies", []):
                names.add(str(dep).split("[", 1)[0].split("=", 1)[0].lower())
            for deps in data.get("project", {}).get("optional-dependencies", {}).values():
                for dep in deps:
                    names.add(str(dep).split("[", 1)[0].split("=", 1)[0].lower())
        except tomllib.TOMLDecodeError:
            pass
    return names


def _env_examples(root: Path) -> list[str]:
    variables: set[str] = set()
    for path in root.glob(".env*"):
        if path.name == ".env":
            continue
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                variables.add(line.split("=", 1)[0].strip())
    return sorted(variables)


def _matching_scripts(scripts: dict[str, str], needles: tuple[str, ...]) -> dict[str, str]:
    return {
        key: value
        for key, value in scripts.items()
        if any(n in f"{key} {value}".lower() for n in needles)
    }


def _entrypoints(root: Path, scripts: dict[str, str]) -> list[str]:
    found = [
        name
        for name in ("main.py", "app.py", "src/main.py", "index.js", "src/index.ts", "src/main.rs")
        if (root / name).exists()
    ]
    found.extend(
        f"script:{name}"
        for name in scripts
        if any(token in name for token in ("start", "dev", "run"))
    )
    return sorted(found)
