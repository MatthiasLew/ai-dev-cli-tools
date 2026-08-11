from __future__ import annotations

import fnmatch
import re
from pathlib import Path

from ai_dev_tools.context.models import ContextOptions, RejectedFile, SelectedFile
from ai_dev_tools.context.symbols import (
    SymbolSnippet,
    select_javascript_symbols,
    select_python_symbols,
    select_structural_symbols,
)
from ai_dev_tools.detectors.repository_map import BINARY_EXTENSIONS
from ai_dev_tools.security.secrets import mask_text

BLOCKED_NAMES = {".env", ".env.local", ".env.production", ".env.development", ".DS_Store"}
BLOCKED_SUFFIXES = {".pyc", ".pyo", ".pem", ".key", ".p12", ".pfx"}
ALWAYS_IGNORE = {
    ".ai/logs",
    ".ai/reports",
    ".ai/context",
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "__pycache__",
    "node_modules",
    ".venv",
    "venv",
    "dist",
    "build",
}


def _select_candidates(
    root: Path,
    options: ContextOptions,
    changed_files: list[str],
    scan_summary: dict[str, object],
    map_summary: dict[str, object],
    related_tests: list[str],
) -> tuple[dict[Path, str], list[RejectedFile]]:
    candidates: dict[Path, str] = {}
    rejected: list[RejectedFile] = []
    for pattern in options.include:
        for path in root.glob(pattern):
            _add_candidate(
                root, path, f"included by pattern: {pattern}", candidates, rejected, options
            )
    for rel in changed_files:
        _add_candidate(root, root / rel, "changed file", candidates, rejected, options)
    for rel in related_tests:
        _add_candidate(root, root / rel, "related affected test", candidates, rejected, options)
    for rel in _object_list(scan_summary.get("entrypoints")):
        if not rel.startswith("script:"):
            _add_candidate(root, root / rel, "detected entrypoint", candidates, rejected, options)
    for key, reason in (
        ("important_files", "important project file"),
        ("tests", "repository test file"),
        ("ci_workflows", "CI workflow"),
        ("documentation", "documentation"),
    ):
        for rel in _object_list(map_summary.get(key)):
            _add_candidate(root, root / rel, reason, candidates, rejected, options)
    return candidates, rejected


def _add_candidate(
    root: Path,
    path: Path,
    reason: str,
    candidates: dict[Path, str],
    rejected: list[RejectedFile],
    options: ContextOptions,
) -> None:
    if not path.exists() or not path.is_file():
        return
    try:
        resolved = path.resolve()
        resolved.relative_to(root.resolve())
    except ValueError:
        rejected.append(RejectedFile(str(path), "outside project root", "OUTSIDE_PROJECT_ROOT"))
        return
    rel = _rel(root, path)
    blocked = _blocked_reason(path, rel, options.exclude)
    if blocked:
        rejected.append(RejectedFile(rel, blocked, _rejection_reason_code(blocked)))
        return
    candidates[path] = reason


def _blocked_reason(path: Path, rel: str, excludes: tuple[str, ...]) -> str | None:
    normalized = rel.replace("\\", "/")
    parts = set(Path(normalized).parts)
    if path.name in BLOCKED_NAMES:
        return "environment or secret-bearing file"
    if path.suffix.lower() in BLOCKED_SUFFIXES or path.suffix.lower() in BINARY_EXTENSIONS:
        return "binary or sensitive file type"
    if any(pattern in parts or normalized.startswith(f"{pattern}/") for pattern in ALWAYS_IGNORE):
        return "ignored generated/cache path"
    if any(fnmatch.fnmatch(normalized, pattern.replace("\\", "/")) for pattern in excludes):
        return "excluded by user pattern"
    return None


def _read_selected_files(
    root: Path, paths: list[Path], reasons: dict[Path, str], options: ContextOptions
) -> tuple[list[SelectedFile], list[RejectedFile]]:
    selected: list[SelectedFile] = []
    rejected: list[RejectedFile] = []
    for path in paths:
        rel = _rel(root, path)
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            rejected.append(RejectedFile(rel, f"unreadable: {exc}", "UNREADABLE_FILE"))
            continue
        masked = mask_text(text)
        suffix = path.suffix.lower()
        if suffix == ".py":
            symbol_selection = select_python_symbols(
                text, masked, options.task, options.max_file_chars
            )
            symbol_strategy = "python-ast"
        elif suffix in {".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".mts", ".cts"}:
            symbol_selection = select_javascript_symbols(
                text, masked, options.task, options.max_file_chars
            )
            symbol_strategy = "javascript-structure"
        elif suffix in {".java", ".rs", ".php"}:
            symbol_selection = select_structural_symbols(
                text, masked, options.task, options.max_file_chars, suffix
            )
            symbol_strategy = {
                ".java": "java-structure",
                ".rs": "rust-structure",
                ".php": "php-structure",
            }[suffix]
        else:
            symbol_selection = None
            symbol_strategy = "file-prefix"
        if symbol_selection is None:
            snippet, truncated = _truncate_text(masked, options.max_file_chars)
            strategy = "file-prefix"
            omitted_content = truncated
            snippets: list[SymbolSnippet] = []
        else:
            snippet = symbol_selection.content
            truncated = symbol_selection.truncated
            strategy = symbol_strategy
            omitted_content = symbol_selection.omitted_content
            snippets = symbol_selection.snippets
        selected.append(
            SelectedFile(
                path=rel,
                reason=reasons[path],
                reason_code=_selection_reason_code(reasons[path]),
                chars=len(snippet),
                truncated=truncated,
                content=snippet,
                selection_strategy=strategy,
                omitted_content=omitted_content,
                snippets=snippets,
            )
        )
    return selected, rejected


def _selection_reason_code(reason: str) -> str:
    return {
        "included by user": "USER_INCLUDE",
        "changed file": "CHANGED_FILE",
        "related affected test": "RELATED_TEST",
        "detected entrypoint": "DETECTED_ENTRYPOINT",
        "important project file": "IMPORTANT_FILE",
        "repository test file": "TEST_FILE",
        "CI workflow": "CI_WORKFLOW",
        "documentation": "DOCUMENTATION",
        "hierarchical retrieval refinement": "HIERARCHICAL_REFINEMENT",
        "Python dependency": "PYTHON_DEPENDENCY",
        "JavaScript/TypeScript dependency": "JS_TS_DEPENDENCY",
        "Rust dependency": "RUST_DEPENDENCY",
        "Java dependency": "JAVA_DEPENDENCY",
        "PHP dependency": "PHP_DEPENDENCY",
    }.get(reason, "SELECTED_FILE")


def _rejection_reason_code(reason: str) -> str:
    return {
        "environment or secret-bearing file": "SENSITIVE_OR_ENV_FILE",
        "binary or sensitive file type": "BINARY_OR_SENSITIVE_TYPE",
        "ignored generated/cache path": "IGNORED_GENERATED_PATH",
        "excluded by user pattern": "USER_EXCLUDED",
    }.get(reason, "REJECTED_FILE")


def _dependency_files(root: Path, candidates: dict[Path, str]) -> dict[Path, str]:
    discovered: dict[Path, str] = {}
    for path in list(candidates):
        rel = _rel(root, path)
        if path.suffix == ".py":
            for module in _python_imports(path):
                for dep in _python_module_paths(root, module):
                    if dep.exists():
                        discovered[dep] = f"local Python dependency imported by {rel}"
        if path.suffix.lower() in {".js", ".jsx", ".ts", ".tsx"}:
            for dep in _relative_js_imports(path):
                discovered[dep] = f"local JS/TS dependency imported by {rel}"
        if path.suffix == ".rs":
            for dep in _rust_mod_paths(path):
                discovered[dep] = f"local Rust module referenced by {rel}"
        if path.suffix == ".java":
            for dep in _java_same_package_paths(path):
                discovered[dep] = f"nearby Java package file related to {rel}"
        if path.suffix == ".php":
            for dep in _php_nearby_paths(path):
                discovered[dep] = f"nearby PHP file related to {rel}"
    return {path: reason for path, reason in discovered.items() if path.is_file()}


def _python_imports(path: Path) -> set[str]:
    text = path.read_text(encoding="utf-8", errors="replace")
    names: set[str] = set()
    for line in text.splitlines():
        match = re.match(
            r"\s*(?:from\s+([A-Za-z_][\w.]*)\s+import|import\s+([A-Za-z_][\w.]*))",
            line,
        )
        if match:
            names.add(match.group(1) or match.group(2) or "")
    return {name for name in names if name}


def _python_module_paths(root: Path, module: str) -> list[Path]:
    parts = module.split(".")
    candidates = [
        root / Path(*parts).with_suffix(".py"),
        root / "src" / Path(*parts).with_suffix(".py"),
    ]
    candidates.extend(
        [root / Path(*parts) / "__init__.py", root / "src" / Path(*parts) / "__init__.py"]
    )
    return candidates


def _relative_js_imports(path: Path) -> list[Path]:
    text = path.read_text(encoding="utf-8", errors="replace")
    deps: list[Path] = []
    for match in re.finditer(r"(?:from\s+|require\()(['\"])(\.{1,2}/[^'\"]+)\1", text):
        base = (path.parent / match.group(2)).resolve()
        for suffix in ("", ".ts", ".tsx", ".js", ".jsx", "/index.ts", "/index.js"):
            candidate = Path(f"{base}{suffix}")
            if candidate.exists() and candidate.is_file():
                deps.append(candidate)
                break
    return deps


def _rust_mod_paths(path: Path) -> list[Path]:
    text = path.read_text(encoding="utf-8", errors="replace")
    deps: list[Path] = []
    for match in re.finditer(r"^\s*mod\s+([A-Za-z_][\w]*)\s*;", text, re.MULTILINE):
        name = match.group(1)
        deps.extend([path.parent / f"{name}.rs", path.parent / name / "mod.rs"])
    return deps


def _java_same_package_paths(path: Path) -> list[Path]:
    return sorted(path.parent.glob("*.java"))[:5]


def _php_nearby_paths(path: Path) -> list[Path]:
    return sorted(path.parent.glob("*.php"))[:5]


def _truncate_text(text: str, max_chars: int) -> tuple[str, bool]:
    if max_chars < 0:
        max_chars = 0
    if len(text) <= max_chars:
        return text, False
    marker = "\n[TRUNCATED]\n"
    keep = max(max_chars - len(marker), 0)
    return text[:keep] + marker, True


def _object_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


def _rel(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()
