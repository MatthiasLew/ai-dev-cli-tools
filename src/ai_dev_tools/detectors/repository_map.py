from __future__ import annotations

import fnmatch
import os
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


def map_repository(project_root: Path, max_files: int = 500, max_depth: int = 6) -> Report:
    settings = load_settings(project_root)
    ignores = {
        pattern.replace("\\", "/").strip("/")
        for pattern in (settings.ignore_paths | _gitignore_patterns(settings.project_root))
        if pattern.strip()
    }
    files: list[Path] = []
    dirs: set[str] = set()
    generated: list[str] = []

    def _walk(directory: Path, depth: int) -> None:
        if depth > max_depth:
            return
        try:
            entries = sorted(os.scandir(directory), key=lambda e: e.name)
        except OSError:
            return
        for entry in entries:
            try:
                is_dir = entry.is_dir(follow_symlinks=False)
                is_file = entry.is_file(follow_symlinks=False)
            except OSError:
                continue
            path = Path(entry.path)
            rel = path.relative_to(settings.project_root)
            if len(rel.parts) > max_depth or _ignored(rel, ignores):
                continue
            if is_dir:
                dirs.add(str(rel))
                _walk(path, depth + 1)
            elif is_file and not _is_binary(path):
                files.append(path)
                if any(fnmatch.fnmatch(entry.name, pattern) for pattern in GENERATED_PATTERNS):
                    generated.append(str(rel))

    _walk(settings.project_root, 1)

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
    truncated = len(files) > max_files
    report.summary = {
        "directories": sorted(dirs)[:max_files],
        "important_files": sorted(important)[:max_files],
        "tests": sorted(tests)[:max_files],
        "ci_workflows": sorted(
            p for p in important if p.replace("\\", "/").startswith(".github/workflows/")
        ),
        "documentation": sorted(docs)[:max_files],
        "generated_or_lock_files": sorted(generated)[:max_files],
        "omitted_patterns": sorted(ignores),
        "file_count_scanned": len(files),
        "max_files": max_files,
        "max_depth": max_depth,
        "truncated": truncated,
        "large_files": _large_files(settings.project_root, files),
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
    return any(
        (p := pattern.replace("\\", "/")) in parts
        or text == p
        or text.startswith(f"{p}/")
        or fnmatch.fnmatch(text, p)
        or fnmatch.fnmatch(rel.name, p)
        or any(fnmatch.fnmatch(part, p) for part in parts)
        or any(
            p in {".venv", "venv"}
            and (
                part.startswith(f"{p}-")
                or part.startswith(f"{p}_")
                or (len(part) > len(p) and part.startswith(p))
            )
            for part in parts
        )
        for pattern in patterns
    )


def _is_binary(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in BINARY_EXTENSIONS


def _large_files(root: Path, files: list[Path]) -> list[str]:
    large: list[str] = []
    for path in files:
        try:
            stat = path.stat()
            if stat.st_size > 1_000_000:
                large.append(str(path.relative_to(root)))
                if len(large) >= 50:
                    break
        except OSError:
            continue
    return large
