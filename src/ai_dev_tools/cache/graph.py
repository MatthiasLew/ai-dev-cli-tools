from __future__ import annotations

import posixpath
import re
from pathlib import Path


def build_impact_graph(
    root: Path,
    paths: set[str],
    *,
    reused_paths: set[str] | None = None,
    previous_edges: object = None,
) -> list[dict[str, str]]:
    reused_paths = reused_paths or set()
    old_by_source = _edges_by_source(previous_edges)
    edges: set[tuple[str, str, str]] = set()
    for relative in sorted(paths):
        if relative in reused_paths and relative in old_by_source:
            edges.update(old_by_source[relative])
            continue
        source = root / relative
        for target, kind in _references(source, relative, paths):
            edges.add((relative, target, kind))
        for target in _candidate_tests(relative, paths):
            edges.add((relative, target, "test"))
    return [{"from": source, "to": target, "kind": kind} for source, target, kind in sorted(edges)]


def related_tests(graph: object, changed_files: list[str]) -> list[str]:
    changed = {path.replace("\\", "/") for path in changed_files}
    selected: set[str] = set()
    if not isinstance(graph, list):
        return []
    for edge in graph:
        if (
            isinstance(edge, dict)
            and edge.get("kind") == "test"
            and edge.get("from") in changed
            and isinstance(edge.get("to"), str)
        ):
            selected.add(str(edge["to"]))
    return sorted(selected)


def _references(source: Path, relative: str, paths: set[str]) -> list[tuple[str, str]]:
    if source.suffix.lower() not in {".py", ".js", ".jsx", ".ts", ".tsx", ".rs"}:
        return []
    try:
        text = source.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    if source.suffix.lower() == ".py":
        return _python_references(relative, text, paths)
    if source.suffix.lower() in {".js", ".jsx", ".ts", ".tsx"}:
        return _js_references(relative, text, paths)
    return _rust_references(relative, text, paths)


def _python_references(relative: str, text: str, paths: set[str]) -> list[tuple[str, str]]:
    result: list[tuple[str, str]] = []
    for match in re.finditer(
        r"^\s*(?:from\s+([A-Za-z_][\w.]*)\s+import|import\s+([A-Za-z_][\w.]*))",
        text,
        re.MULTILINE,
    ):
        module = match.group(1) or match.group(2)
        module_path = module.replace(".", "/")
        candidates = [
            f"{module_path}.py",
            f"src/{module_path}.py",
            f"{module_path}/__init__.py",
            f"src/{module_path}/__init__.py",
        ]
        result.extend((candidate, "import") for candidate in candidates if candidate in paths)
    return result


def _js_references(relative: str, text: str, paths: set[str]) -> list[tuple[str, str]]:
    result: list[tuple[str, str]] = []
    directory = posixpath.dirname(relative)
    for match in re.finditer(r"(?:from\s+|require\()(['\"])(\.{1,2}/[^'\"]+)\1", text):
        base = posixpath.normpath(posixpath.join(directory, match.group(2)))
        candidates = [
            base,
            *[f"{base}{suffix}" for suffix in (".ts", ".tsx", ".js", ".jsx")],
            *[f"{base}/index{suffix}" for suffix in (".ts", ".tsx", ".js", ".jsx")],
        ]
        result.extend((candidate, "import") for candidate in candidates if candidate in paths)
    return result


def _rust_references(relative: str, text: str, paths: set[str]) -> list[tuple[str, str]]:
    directory = posixpath.dirname(relative)
    result: list[tuple[str, str]] = []
    for match in re.finditer(r"^\s*mod\s+([A-Za-z_][\w]*)\s*;", text, re.MULTILINE):
        name = match.group(1)
        for candidate in (f"{directory}/{name}.rs", f"{directory}/{name}/mod.rs"):
            normalized = candidate.lstrip("/")
            if normalized in paths:
                result.append((normalized, "import"))
    return result


def _candidate_tests(relative: str, paths: set[str]) -> list[str]:
    path = Path(relative)
    stem = path.stem
    candidates: list[str] = []
    if path.suffix == ".py":
        parts = list(path.parts)
        source_parts = parts[1:] if parts and parts[0] in {"src", "lib"} else parts
        if source_parts:
            source_parts[-1] = f"test_{stem}.py"
            candidates.append(Path("tests", *source_parts).as_posix())
        candidates.append(Path("tests", f"test_{stem}.py").as_posix())
    elif path.suffix.lower() in {".js", ".jsx", ".ts", ".tsx"}:
        candidates.extend(
            [
                path.with_name(f"{stem}.test{path.suffix}").as_posix(),
                path.with_name(f"{stem}.spec{path.suffix}").as_posix(),
            ]
        )
    return sorted({candidate for candidate in candidates if candidate in paths})


def _edges_by_source(value: object) -> dict[str, set[tuple[str, str, str]]]:
    result: dict[str, set[tuple[str, str, str]]] = {}
    if not isinstance(value, list):
        return result
    for edge in value:
        if not isinstance(edge, dict):
            continue
        source, target, kind = edge.get("from"), edge.get("to"), edge.get("kind")
        if all(isinstance(item, str) for item in (source, target, kind)):
            result.setdefault(str(source), set()).add((str(source), str(target), str(kind)))
    return result
