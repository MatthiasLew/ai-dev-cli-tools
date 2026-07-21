from __future__ import annotations

import fnmatch
from pathlib import Path

from ai_dev_tools.config import load_settings
from ai_dev_tools.models.report import Report
from ai_dev_tools.reporters.writer import write_json, write_markdown

IMPORTANT_NAMES = {
    "pyproject.toml",
    "package.json",
    "Cargo.toml",
    "composer.json",
    "pom.xml",
    "build.gradle",
    "Dockerfile",
    "compose.yaml",
    "docker-compose.yml",
    "Makefile",
    "README.md",
    "LICENSE",
}
BINARY_EXTENSIONS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".ico",
    ".pdf",
    ".zip",
    ".exe",
    ".dll",
    ".so",
    ".dylib",
}
GENERATED_PATTERNS = ("*.min.js", "*.lock", "package-lock.json", "coverage.xml")


def map_repository(project_root: Path) -> Report:
    settings = load_settings(project_root)
    ignores = settings.ignore_paths | _gitignore_patterns(settings.project_root)
    files: list[Path] = []
    dirs: set[str] = set()
    generated: list[str] = []
    for path in settings.project_root.rglob("*"):
        rel = path.relative_to(settings.project_root)
        if _ignored(rel, ignores) or _is_binary(path):
            continue
        if path.is_dir():
            dirs.add(str(rel))
            continue
        files.append(path)
        if any(fnmatch.fnmatch(path.name, pattern) for pattern in GENERATED_PATTERNS):
            generated.append(str(rel))
    important = [
        str(p.relative_to(settings.project_root))
        for p in files
        if p.name in IMPORTANT_NAMES or ".github/workflows" in p.as_posix()
    ]
    tests = [
        str(p.relative_to(settings.project_root))
        for p in files
        if "test" in p.name.lower() or "tests" in p.parts
    ]
    docs = [
        str(p.relative_to(settings.project_root))
        for p in files
        if p.suffix.lower() in {".md", ".rst"} or "docs" in p.parts
    ]
    report = Report(command="map", project_root=settings.project_root)
    report.summary = {
        "directories": sorted(dirs)[:200],
        "important_files": sorted(important)[:200],
        "tests": sorted(tests)[:200],
        "ci_workflows": sorted(
            p for p in important if p.replace("\\", "/").startswith(".github/workflows/")
        ),
        "documentation": sorted(docs)[:200],
        "generated_or_lock_files": sorted(generated)[:200],
        "omitted_patterns": sorted(ignores),
        "file_count_scanned": len(files),
    }
    report.finish()
    write_markdown(report, settings.reports_directory / "repository-map.md")
    write_json(report, settings.reports_directory / "repository-map.json")
    return report


def _gitignore_patterns(root: Path) -> set[str]:
    path = root / ".gitignore"
    if not path.exists():
        return set()
    return {
        line.strip().rstrip("/")
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines()
        if line.strip() and not line.startswith("#")
    }


def _ignored(rel: Path, patterns: set[str]) -> bool:
    parts = set(rel.parts)
    text = rel.as_posix()
    normalized_patterns = {pattern.replace("\\", "/") for pattern in patterns}
    return any(
        pattern in parts
        or text == pattern
        or text.startswith(f"{pattern}/")
        or fnmatch.fnmatch(text, pattern)
        or fnmatch.fnmatch(rel.name, pattern)
        for pattern in normalized_patterns
    )


def _is_binary(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in BINARY_EXTENSIONS
