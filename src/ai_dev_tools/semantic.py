from __future__ import annotations

import importlib.metadata
import json
import os
import shutil
from pathlib import Path
from typing import Protocol, cast

from ai_dev_tools.cache.repository import read_repository_index, update_repository_index
from ai_dev_tools.models.report import Artifact, Issue, Report
from ai_dev_tools.source_symbols import extract_source_symbols

SEMANTIC_INDEX_PATH = Path(".ai/cache/semantic-index.json")
SUPPORTED_SUFFIXES = {".py", ".js", ".jsx", ".ts", ".tsx", ".java", ".rs", ".php"}
LSP_EXECUTABLES = {
    "python": ("pyright-langserver", "pylsp"),
    "typescript": ("typescript-language-server",),
    "rust": ("rust-analyzer",),
    "java": ("jdtls",),
    "php": ("intelephense",),
}


class SemanticBackend(Protocol):
    def index(self, project_root: Path, paths: list[Path]) -> list[dict[str, object]]: ...


def run_semantic(project_root: Path, action: str, backend: str = "auto") -> Report:
    root = project_root.resolve()
    report = Report(command=f"semantic {action}", project_root=root)
    capabilities = semantic_capabilities()
    if action == "status":
        path = root / SEMANTIC_INDEX_PATH
        report.summary = {**capabilities, "indexed": path.exists(), "index_path": str(path)}
        return report

    repository = read_repository_index(root) or update_repository_index(root)
    paths = _source_paths(root, repository.get("entries"))
    selected_backend = "structural" if backend == "auto" else backend
    try:
        symbols = _index_with_backend(root, paths, selected_backend)
    except (ImportError, AttributeError, TypeError, ValueError) as exc:
        report.status = "invalid_configuration"
        report.summary = {
            **capabilities,
            "backend": selected_backend,
            "reason_code": "SEMANTIC_BACKEND_UNAVAILABLE",
            "message": str(exc),
        }
        return report
    bounded_symbols = symbols[:10_000]
    payload: dict[str, object] = {
        "schema_version": "1",
        "backend": selected_backend,
        "files_considered": len(paths),
        "symbols": bounded_symbols,
        "truncated": len(symbols) > 10_000,
    }
    output = root / SEMANTIC_INDEX_PATH
    _write_json(output, payload)
    report.summary = {**capabilities, **payload, "symbol_count": len(bounded_symbols)}
    report.artifacts.append(Artifact(str(output), "semantic-index", "Local semantic symbol index"))
    if payload["truncated"]:
        report.status = "partial"
        report.issues.append(
            Issue(
                "warning",
                "Semantic index reached its 10,000 symbol bound.",
                code="SEMANTIC_INDEX_TRUNCATED",
            )
        )
    return report


def semantic_capabilities() -> dict[str, object]:
    plugins = sorted(_backend_entry_points())
    lsp = {
        language: [name for name in names if shutil.which(name)]
        for language, names in LSP_EXECUTABLES.items()
    }
    return {
        "protocol_version": "1",
        "default_backend": "structural",
        "available_backends": ["structural", *plugins],
        "plugin_group": "ai_dev_tools.semantic_backends",
        "lsp_servers": lsp,
        "lsp_available": any(lsp.values()),
        "fallback": "structural",
        "local_only": True,
    }


def _index_with_backend(root: Path, paths: list[Path], backend: str) -> list[dict[str, object]]:
    if backend == "structural":
        return _structural_index(root, paths)
    entry_points = _backend_entry_points()
    if backend not in entry_points:
        raise ValueError(f"Unknown semantic backend: {backend}")
    loaded = entry_points[backend].load()
    instance = loaded() if isinstance(loaded, type) else loaded
    provider = cast(SemanticBackend, instance)
    result = provider.index(root, paths)
    if not isinstance(result, list):
        raise TypeError("Semantic backend must return a list of symbol objects")
    return [item for item in result if isinstance(item, dict)]


def _structural_index(root: Path, paths: list[Path]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for path in paths[:2_000]:
        try:
            if path.stat().st_size > 2_000_000:
                continue
            source = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        symbols = extract_source_symbols(source, path.suffix)
        if symbols is None:
            continue
        relative = path.relative_to(root).as_posix()
        rows.extend(
            {
                "path": relative,
                "name": item.name,
                "kind": item.kind,
                "start_line": item.start_line,
                "end_line": item.end_line,
                "backend": "structural",
            }
            for item in symbols
        )
    return rows


def _source_paths(root: Path, entries: object) -> list[Path]:
    if not isinstance(entries, list):
        return []
    paths: list[Path] = []
    for item in entries:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            continue
        path = root / str(item["path"])
        if path.suffix.lower() in SUPPORTED_SUFFIXES and path.is_file():
            paths.append(path)
    return paths


def _backend_entry_points() -> dict[str, importlib.metadata.EntryPoint]:
    points = importlib.metadata.entry_points().select(group="ai_dev_tools.semantic_backends")
    return {point.name: point for point in points}


def _write_json(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)
