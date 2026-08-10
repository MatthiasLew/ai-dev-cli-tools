from __future__ import annotations

import glob
import json
import os
import re
import tomllib
from pathlib import Path

from ai_dev_tools.detectors.runtime import detect_runtime_requirements
from ai_dev_tools.models.workspace import Workspace

_IGNORED = {".git", ".ai", ".venv", "node_modules", "dist", "build", "target", "vendor"}


def detect_workspaces(root: Path) -> list[Workspace]:
    candidates: dict[Path, set[str]] = {root.resolve(): set()}
    _add_manifest_roots(root, candidates)
    _add_declared_workspaces(root, candidates)
    workspaces = [_workspace(root, path, sources) for path, sources in candidates.items()]
    result = [workspace for workspace in workspaces if workspace is not None]
    return sorted(result, key=lambda item: (item.root.count("/"), item.root, item.workspace_id))


def owning_workspace(workspaces: list[Workspace], relative_path: str) -> Workspace | None:
    owners = [workspace for workspace in workspaces if workspace.owns(relative_path)]
    return max(owners, key=lambda item: len(item.root), default=None)


def _add_manifest_roots(root: Path, candidates: dict[Path, set[str]]) -> None:
    manifests = {
        "pyproject.toml",
        "package.json",
        "Cargo.toml",
        "pom.xml",
        "build.gradle",
        "build.gradle.kts",
        "composer.json",
    }
    for current, directories, files in os.walk(root):
        current_path = Path(current)
        directories[:] = sorted(
            name
            for name in directories
            if name not in _IGNORED
            and not (current_path.name in {"test", "tests"} and name == "fixtures")
        )
        for name in sorted(manifests & set(files)):
            path = current_path / name
            resolved = path.parent.resolve()
            candidates.setdefault(resolved, set()).add(_rel(root, path))


def _add_declared_workspaces(root: Path, candidates: dict[Path, set[str]]) -> None:
    package = _json(root / "package.json")
    raw_workspaces = package.get("workspaces", [])
    if isinstance(raw_workspaces, dict):
        raw_workspaces = raw_workspaces.get("packages", [])
    if isinstance(raw_workspaces, list):
        for pattern in raw_workspaces:
            if isinstance(pattern, str):
                _add_glob(root, pattern, "package.json#workspaces", candidates)

    pnpm = _text(root / "pnpm-workspace.yaml")
    for pattern in re.findall(r"^\s*-\s*['\"]?([^'\"#]+)", pnpm, re.MULTILINE):
        _add_glob(root, pattern.strip(), "pnpm-workspace.yaml", candidates)

    cargo = _toml(root / "Cargo.toml")
    cargo_workspace = cargo.get("workspace", {})
    if isinstance(cargo_workspace, dict) and isinstance(cargo_workspace.get("members"), list):
        for pattern in cargo_workspace["members"]:
            if isinstance(pattern, str):
                _add_glob(root, pattern, "Cargo.toml#workspace", candidates)

    pom = _text(root / "pom.xml")
    for module in re.findall(r"<module>\s*([^<]+)\s*</module>", pom):
        _add_root(root, module.strip(), "pom.xml#modules", candidates)

    gradle = _text(root / "settings.gradle") + "\n" + _text(root / "settings.gradle.kts")
    for declaration in re.findall(r"\binclude\s*\(?\s*([^\n\r\)]+)", gradle):
        for module in re.findall(r"['\"]:([^'\"]+)['\"]", declaration):
            _add_root(root, module.replace(":", "/"), "Gradle settings", candidates)


def _add_glob(root: Path, pattern: str, source: str, candidates: dict[Path, set[str]]) -> None:
    normalized = pattern.replace("\\", "/").rstrip("/")
    for value in glob.glob(str(root / normalized)):
        path = Path(value)
        if path.is_dir() and not _ignored(root, path):
            candidates.setdefault(path.resolve(), set()).add(source)


def _add_root(root: Path, relative: str, source: str, candidates: dict[Path, set[str]]) -> None:
    path = (root / relative).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError:
        return
    if path.is_dir() and not _ignored(root, path):
        candidates.setdefault(path, set()).add(source)


def _workspace(root: Path, path: Path, sources: set[str]) -> Workspace | None:
    configs = [
        name
        for name in (
            "pyproject.toml",
            "requirements.txt",
            "package.json",
            "pnpm-lock.yaml",
            "yarn.lock",
            "package-lock.json",
            "Cargo.toml",
            "pom.xml",
            "build.gradle",
            "build.gradle.kts",
            "composer.json",
        )
        if (path / name).exists()
    ]
    if not configs and path != root.resolve():
        return None
    technologies: list[str] = []
    if any(name in configs for name in ("pyproject.toml", "requirements.txt")):
        technologies.append("python")
    if "package.json" in configs:
        technologies.append("node")
    if "Cargo.toml" in configs:
        technologies.append("rust")
    if any(name in configs for name in ("pom.xml", "build.gradle", "build.gradle.kts")):
        technologies.append("java")
    if "composer.json" in configs:
        technologies.append("php")
    kind = "mixed" if len(technologies) > 1 else technologies[0] if technologies else "root"
    relative = _rel(root, path)
    package_manager = _package_manager(configs, path)
    commands = _commands(path, technologies, package_manager)
    config_files = tuple(sorted({*configs, *sources}))
    workspace_id = relative.replace("/", ":") if relative else "root"
    return Workspace(
        workspace_id=workspace_id,
        root=relative,
        kind=kind,
        technologies=tuple(technologies),
        package_manager=package_manager,
        config_files=config_files,
        commands=commands,
        runtime_requirements=tuple(detect_runtime_requirements(path)),
    )


def _commands(path: Path, technologies: list[str], package_manager: str | None) -> dict[str, str]:
    commands: dict[str, str] = {}
    if "python" in technologies:
        commands["test"] = "python -m pytest"
    if "node" in technologies and package_manager:
        package = _json(path / "package.json")
        scripts = package.get("scripts", {})
        if isinstance(scripts, dict):
            for name in ("test", "lint", "typecheck", "build"):
                if isinstance(scripts.get(name), str):
                    commands[name] = f"{package_manager} run {name}"
    if package_manager == "cargo":
        commands["test"] = "cargo test"
    if package_manager == "maven":
        commands["test"] = "mvn test"
    if package_manager == "gradle":
        commands["test"] = "gradle test"
    if package_manager == "composer":
        commands.setdefault("install", "composer install --no-interaction")
    return commands


def _package_manager(configs: list[str], path: Path) -> str | None:
    if "pnpm-lock.yaml" in configs:
        return "pnpm"
    if "yarn.lock" in configs:
        return "yarn"
    if "package-lock.json" in configs or "package.json" in configs:
        return "npm"
    if "Cargo.toml" in configs:
        return "cargo"
    if "pom.xml" in configs:
        return "maven"
    if "build.gradle" in configs or "build.gradle.kts" in configs:
        return "gradle"
    if "composer.json" in configs:
        return "composer"
    if "pyproject.toml" in configs or "requirements.txt" in configs:
        return "python"
    return None


def _ignored(root: Path, path: Path) -> bool:
    try:
        relative = path.resolve().relative_to(root.resolve())
    except ValueError:
        return True
    return any(part in _IGNORED for part in relative.parts)


def _rel(root: Path, path: Path) -> str:
    value = path.resolve().relative_to(root.resolve()).as_posix()
    return "" if value == "." else value


def _text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _json(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _toml(path: Path) -> dict[str, object]:
    try:
        with path.open("rb") as handle:
            value = tomllib.load(handle)
            return value if isinstance(value, dict) else {}
    except (OSError, tomllib.TOMLDecodeError):
        return {}
