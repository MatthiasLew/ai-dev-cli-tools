from __future__ import annotations

import posixpath
import re
from collections import deque
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
        edges.update(_configuration_relationships(relative, paths))
        edges.update(_generated_relationships(source, relative, paths))
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


def shortest_reason_paths(
    graph: object,
    changed_files: list[str],
    *,
    selected_files: list[str] | None = None,
    changed_symbols: list[dict[str, object]] | None = None,
    selected_tests: list[str] | None = None,
    selected_commands: list[list[str]] | None = None,
    selection_reason_code: str = "CHANGED_SELECTION",
    max_paths: int = 100,
    max_depth: int = 6,
) -> list[dict[str, object]]:
    changed = sorted({path.replace("\\", "/") for path in changed_files})
    adjacency = _adjacency(graph)
    paths: dict[str, list[dict[str, str]]] = {
        path: [{"kind": "changed_file", "value": path, "reason_code": "CHANGED_FILE"}]
        for path in changed
    }
    queue = deque((path, paths[path]) for path in changed)
    while queue:
        source, steps = queue.popleft()
        if len(steps) > max(max_depth, 0):
            continue
        for target, kind in adjacency.get(source, []):
            if target in paths:
                continue
            reason_code = _edge_reason_code(kind)
            target_steps = [
                *steps,
                {"kind": kind, "value": target, "reason_code": reason_code},
            ]
            paths[target] = target_steps
            queue.append((target, target_steps))

    results: dict[str, dict[str, object]] = {}
    test_set = {path.replace("\\", "/") for path in selected_tests or []}
    for target in [*(selected_files or []), *sorted(test_set)]:
        normalized = target.replace("\\", "/")
        selected_steps = paths.get(normalized)
        if selected_steps is not None:
            results[normalized] = {
                "target": normalized,
                "target_kind": "test" if normalized in test_set else "file",
                "reason_code": selected_steps[-1]["reason_code"],
                "steps": selected_steps,
            }
    for symbol in changed_symbols or []:
        path = symbol.get("path")
        name = symbol.get("name")
        if not isinstance(path, str) or not isinstance(name, str) or path not in paths:
            continue
        target = f"{path}#{name}"
        results[target] = {
            "target": target,
            "target_kind": "symbol",
            "reason_code": "CHANGED_SYMBOL",
            "steps": [
                *paths[path],
                {"kind": "symbol", "value": name, "reason_code": "CHANGED_SYMBOL"},
            ],
        }
    for command in selected_commands or []:
        command_text = " ".join(command)
        test = next((path for path in sorted(test_set) if path in command), None)
        base = paths.get(test) if test is not None else paths.get(changed[0]) if changed else None
        if base is None:
            continue
        results[command_text] = {
            "target": command_text,
            "target_kind": "check",
            "reason_code": selection_reason_code,
            "steps": [
                *base,
                {"kind": "check", "value": command_text, "reason_code": selection_reason_code},
            ],
        }
    return [results[key] for key in sorted(results)[: max(max_paths, 0)]]


def _adjacency(graph: object) -> dict[str, list[tuple[str, str]]]:
    result: dict[str, list[tuple[str, str]]] = {}
    if not isinstance(graph, list):
        return result
    for edge in graph:
        if not isinstance(edge, dict):
            continue
        source, target, kind = edge.get("from"), edge.get("to"), edge.get("kind")
        if all(isinstance(item, str) for item in (source, target, kind)):
            result.setdefault(str(source), []).append((str(target), str(kind)))
            if kind == "import":
                result.setdefault(str(target), []).append((str(source), "dependent"))
    for edges in result.values():
        edges.sort()
    return result


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


def _configuration_relationships(
    relative: str, paths: set[str]
) -> set[tuple[str, str, str]]:
    name = Path(relative).name.lower()
    suffixes: set[str]
    if name in {"pyproject.toml", "requirements.txt", "requirements-dev.txt"}:
        suffixes = {".py"}
    elif name in {"package.json", "tsconfig.json", "jsconfig.json"}:
        suffixes = {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"}
    elif name == "cargo.toml":
        suffixes = {".rs"}
    elif name in {"pom.xml", "build.gradle", "build.gradle.kts"}:
        suffixes = {".java"}
    elif name == "composer.json":
        suffixes = {".php"}
    else:
        return set()
    directory = posixpath.dirname(relative)
    prefix = f"{directory}/" if directory else ""
    owned = [
        path
        for path in sorted(paths)
        if path != relative and path.startswith(prefix) and Path(path).suffix.lower() in suffixes
    ]
    return {(relative, target, "configuration") for target in owned[:500]}


def _generated_relationships(
    source: Path, relative: str, paths: set[str]
) -> set[tuple[str, str, str]]:
    if source.suffix.lower() not in {".py", ".js", ".jsx", ".ts", ".tsx", ".java", ".rs", ".php"}:
        return set()
    try:
        header = source.read_text(encoding="utf-8", errors="replace")[:4_000]
    except OSError:
        return set()
    matches = re.findall(
        r"(?im)(?:generated\s+(?:from|by)|source)\s*[:=]?\s*[`'\"]?([\w./\\-]+)",
        header,
    )
    edges: set[tuple[str, str, str]] = set()
    directory = posixpath.dirname(relative)
    for value in matches:
        candidate = posixpath.normpath(posixpath.join(directory, value.replace("\\", "/")))
        if candidate in paths and candidate != relative:
            edges.add((candidate, relative, "generated"))
    return edges


def _edge_reason_code(kind: str) -> str:
    return {
        "test": "RELATED_TEST",
        "dependent": "DEPENDENT_FILE",
        "configuration": "CONFIGURATION_OWNER",
        "generated": "GENERATED_RELATIONSHIP",
    }.get(kind, "DEPENDENCY_EDGE")


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
