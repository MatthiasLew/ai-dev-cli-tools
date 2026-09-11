from __future__ import annotations

import fnmatch
import os
import posixpath
import subprocess
from pathlib import Path

from ai_dev_tools.config import DEFAULT_IGNORES, load_settings
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


class _IgnoreRule:
    __slots__ = ("anchored", "dir_only", "is_negation", "pattern", "prefix")

    def __init__(self, raw: str, prefix: str) -> None:
        self.prefix = prefix
        self.is_negation = raw.startswith("!")
        clean = raw[1:] if self.is_negation else raw
        self.dir_only = clean.endswith("/")
        clean = clean.rstrip("/")
        self.anchored = clean.startswith("/") or "/" in clean
        self.pattern = clean.lstrip("/")

    def matches(self, rel_posix: str, is_dir: bool) -> bool:
        if self.dir_only and not is_dir:
            return False
        if self.prefix:
            if not (rel_posix == self.prefix or rel_posix.startswith(self.prefix + "/")):
                return False
            path_in_scope = rel_posix[len(self.prefix) + 1 :] if rel_posix != self.prefix else ""
        else:
            path_in_scope = rel_posix
        if not path_in_scope:
            return False

        if self.anchored:
            return (
                fnmatch.fnmatch(path_in_scope, self.pattern)
                or fnmatch.fnmatch(path_in_scope, f"{self.pattern}/*")
            )
        name = posixpath.basename(path_in_scope)
        return (
            fnmatch.fnmatch(name, self.pattern)
            or fnmatch.fnmatch(path_in_scope, self.pattern)
            or fnmatch.fnmatch(path_in_scope, f"*/{self.pattern}")
            or fnmatch.fnmatch(path_in_scope, f"{self.pattern}/*")
            or fnmatch.fnmatch(path_in_scope, f"*/{self.pattern}/*")
        )


def _git_ls_files(root: Path) -> list[str] | None:
    if not (root / ".git").exists() and not (root.parent / ".git").exists():
        return None
    try:
        proc = subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
            cwd=root,
            capture_output=True,
            text=False,
            timeout=10,
        )
        if proc.returncode == 0:
            return [
                part.decode("utf-8", errors="surrogateescape")
                for part in proc.stdout.split(b"\0")
                if part
            ]
    except (OSError, subprocess.TimeoutExpired, ValueError):
        pass
    return None


def _load_rules_file(path: Path, prefix: str) -> list[_IgnoreRule]:
    if not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    rules: list[_IgnoreRule] = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        rules.append(_IgnoreRule(stripped, prefix))
    return rules


def _is_rule_ignored(rel_posix: str, is_dir: bool, rules: list[_IgnoreRule]) -> bool:
    ignored = False
    for rule in rules:
        if rule.matches(rel_posix, is_dir):
            ignored = not rule.is_negation
    return ignored


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

    git_files = _git_ls_files(settings.project_root)
    if git_files is not None:
        user_ignores = (settings.ignore_paths - DEFAULT_IGNORES) | {".ai", ".git"}
        for rel_str in sorted(git_files):
            rel_normalized = rel_str.replace("\\", "/").strip("/")
            if not rel_normalized:
                continue
            path = settings.project_root / rel_normalized
            rel = Path(rel_normalized)
            if len(rel.parts) > max_depth or _ignored(rel, user_ignores):
                continue
            parent = rel.parent
            while str(parent) not in {".", ""}:
                parent_posix = parent.as_posix()
                if len(parent.parts) <= max_depth and not _ignored(parent, user_ignores):
                    dirs.add(parent_posix)
                parent = parent.parent
            if path.is_file() and not _is_binary(path):
                files.append(path)
                if any(fnmatch.fnmatch(path.name, pattern) for pattern in GENERATED_PATTERNS):
                    generated.append(rel_normalized)
    else:
        root_rules = _load_rules_file(settings.project_root / ".gitignore", "")

        def _walk(directory: Path, depth: int, rules: list[_IgnoreRule]) -> None:
            if depth > max_depth:
                return
            try:
                entries = sorted(os.scandir(directory), key=lambda e: e.name)
            except OSError:
                return
            sub_rules = list(rules)
            for entry in entries:
                if entry.name == ".gitignore":
                    try:
                        if entry.is_file(follow_symlinks=False):
                            parent_dir = Path(entry.path).relative_to(settings.project_root).parent
                            sub_rel = "" if parent_dir.as_posix() == "." else parent_dir.as_posix()
                            sub_rules.extend(_load_rules_file(Path(entry.path), sub_rel))
                    except OSError:
                        pass

            for entry in entries:
                try:
                    is_dir = entry.is_dir(follow_symlinks=False)
                    is_file = entry.is_file(follow_symlinks=False)
                except OSError:
                    continue
                path = Path(entry.path)
                rel = path.relative_to(settings.project_root)
                rel_posix = rel.as_posix()
                if len(rel.parts) > max_depth or _ignored(rel, settings.ignore_paths):
                    continue
                if _is_rule_ignored(rel_posix, is_dir, sub_rules):
                    continue
                if is_dir:
                    dirs.add(str(rel))
                    _walk(path, depth + 1, sub_rules)
                elif is_file and not _is_binary(path):
                    files.append(path)
                    if any(fnmatch.fnmatch(entry.name, pattern) for pattern in GENERATED_PATTERNS):
                        generated.append(str(rel))

        _walk(settings.project_root, 1, root_rules)

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
