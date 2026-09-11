from __future__ import annotations

import contextlib
import hashlib
import importlib.metadata
import json
import os
import shutil
import threading
import time
from functools import lru_cache
from pathlib import Path
from typing import Protocol, cast

from ai_dev_tools.cache.repository import update_repository_index
from ai_dev_tools.models.report import Artifact, Issue, Report
from ai_dev_tools.semantic_backends import lsp_index, tree_sitter_available, tree_sitter_index
from ai_dev_tools.source_symbols import extract_source_symbols

SEMANTIC_INDEX_PATH = Path(".ai/cache/semantic-index.json")
SEMANTIC_CACHE_PATH = Path(".ai/cache/semantic-cache.json")
SEMANTIC_SCHEMA_VERSION = "2"
SEMANTIC_EXTRACTOR_VERSION = "1"
SUPPORTED_SUFFIXES = {".py", ".js", ".jsx", ".ts", ".tsx", ".java", ".rs", ".php"}
LSP_EXECUTABLES = {
    "python": ("pyright-langserver", "pylsp"),
    "typescript": ("typescript-language-server",),
    "rust": ("rust-analyzer",),
    "java": ("jdtls",),
    "php": ("intelephense",),
}


def _backend_version(backend: str) -> str:
    if backend == "treesitter":
        try:
            import importlib.metadata

            return importlib.metadata.version("tree-sitter-language-pack")
        except Exception:
            return "builtin"
    elif backend == "lsp":
        # LSP external language servers vary by system and language;
        # running discovery subprocesses per fingerprint causes severe latency.
        return "lsp_v1"
    return "builtin"


def semantic_cache_fingerprint(
    backend: str,
    schema_version: str | None = None,
    extractor_version: str | None = None,
    backend_version: str | None = None,
    config_items: tuple[str, ...] | None = None,
) -> str:
    schema = SEMANTIC_SCHEMA_VERSION if schema_version is None else schema_version
    extractor = SEMANTIC_EXTRACTOR_VERSION if extractor_version is None else extractor_version
    backend_ver = _backend_version(backend) if backend_version is None else backend_version
    config = tuple(sorted(SUPPORTED_SUFFIXES)) if config_items is None else config_items
    raw = json.dumps(
        {
            "schema_version": schema,
            "backend": backend,
            "backend_version": backend_ver,
            "extractor_version": extractor,
            "config": config,
        },
        sort_keys=True,
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


@lru_cache(maxsize=64)
def _which_cached(which_fn: object, name: str) -> str | None:
    if callable(which_fn):
        result = which_fn(name)
        return str(result) if result else None
    return shutil.which(name)


class SemanticBackend(Protocol):
    def index(self, project_root: Path, paths: list[Path]) -> list[dict[str, object]]: ...


def run_semantic(
    project_root: Path,
    action: str,
    backend: str = "auto",
    rebuild: bool = False,
) -> Report:
    root = project_root.resolve()
    report = Report(command=f"semantic {action}", project_root=root)
    capabilities = semantic_capabilities()
    if action == "status":
        path = root / SEMANTIC_INDEX_PATH
        report.summary = {**capabilities, "indexed": path.exists(), "index_path": str(path)}
        return report

    repository = update_repository_index(root)
    entries = repository.get("entries")
    paths = _source_paths(root, entries)
    selected_backend = (
        "treesitter"
        if backend == "auto" and tree_sitter_available()
        else ("structural" if backend == "auto" else backend)
    )

    if not paths:
        try:
            _index_with_backend(root, [], selected_backend)
        except (
            ImportError,
            AttributeError,
            OSError,
            RuntimeError,
            TimeoutError,
            TypeError,
            ValueError,
        ) as exc:
            if backend == "auto" and selected_backend == "treesitter":
                selected_backend = "structural"
                report.status = "partial"
                report.issues.append(
                    Issue(
                        "warning",
                        f"Tree-sitter was unavailable; used structural fallback: {exc}",
                        code="TREE_SITTER_FALLBACK",
                    )
                )
            else:
                report.status = "invalid_configuration"
                report.summary = {
                    **capabilities,
                    "backend": selected_backend,
                    "reason_code": "SEMANTIC_BACKEND_UNAVAILABLE",
                    "message": str(exc),
                }
                return report

    repo_fingerprints: dict[str, str] = {}
    if isinstance(entries, list):
        for item in entries:
            if (
                isinstance(item, dict)
                and isinstance(item.get("path"), str)
                and isinstance(item.get("sha256"), str)
            ):
                repo_fingerprints[str(item["path"])] = str(item["sha256"])

    output = root / SEMANTIC_INDEX_PATH
    cache_path = root / SEMANTIC_CACHE_PATH
    current_fingerprint = semantic_cache_fingerprint(selected_backend)

    cached_hashes: dict[str, str] = {}
    cached_symbols_by_path: dict[str, list[dict[str, object]]] = {}
    is_incremental_candidate = False

    if not rebuild and action != "rebuild":
        cache_data = _read_json(cache_path)
        if (
            cache_data is not None
            and cache_data.get("fingerprint") == current_fingerprint
            and isinstance(cache_data.get("file_hashes"), dict)
            and isinstance(cache_data.get("file_symbols"), dict)
        ):
            cached_hashes = cast(dict[str, str], cache_data["file_hashes"])
            raw_syms = cast(dict[str, object], cache_data["file_symbols"])
            for rel_path, items in raw_syms.items():
                if isinstance(items, list):
                    cached_symbols_by_path[rel_path] = [
                        sym for sym in items if isinstance(sym, dict)
                    ]
            is_incremental_candidate = True
        else:
            # Fallback to index file if present and matches fingerprint
            index_data = _read_json(output)
            if (
                index_data is not None
                and index_data.get("fingerprint") == current_fingerprint
                and isinstance(index_data.get("file_hashes"), dict)
                and isinstance(index_data.get("symbols"), list)
                and not index_data.get("truncated", False)
            ):
                cached_hashes = cast(dict[str, str], index_data["file_hashes"])
                for sym in cast(list[object], index_data["symbols"]):
                    if isinstance(sym, dict) and isinstance(sym.get("path"), str):
                        cached_symbols_by_path.setdefault(str(sym["path"]), []).append(sym)
                is_incremental_candidate = True

    paths_to_index: list[Path] = []
    cached_to_reuse: dict[str, list[dict[str, object]]] = {}
    current_file_hashes: dict[str, str] = {}
    calculated_hashes: dict[str, str] = {}

    for path in paths:
        rel = path.relative_to(root).as_posix()
        file_hash = repo_fingerprints.get(rel)
        if file_hash is None:
            file_hash = _sha256(path)
        calculated_hashes[rel] = file_hash

        if is_incremental_candidate and rel in cached_hashes and cached_hashes[rel] == file_hash:
            cached_to_reuse[rel] = cached_symbols_by_path.get(rel, [])
            current_file_hashes[rel] = file_hash
        else:
            paths_to_index.append(path)

    symbols: list[dict[str, object]] = []
    assembled_by_path: dict[str, list[dict[str, object]]] = dict(cached_to_reuse)

    if paths_to_index:
        try:
            new_symbols = _index_with_backend(root, paths_to_index, selected_backend)
        except (
            ImportError,
            AttributeError,
            OSError,
            RuntimeError,
            TimeoutError,
            TypeError,
            ValueError,
        ) as exc:
            if backend == "auto" and selected_backend == "treesitter":
                selected_backend = "structural"
                symbols = _structural_index(root, paths)
                report.status = "partial"
                report.issues.append(
                    Issue(
                        "warning",
                        f"Tree-sitter was unavailable; used structural fallback: {exc}",
                        code="TREE_SITTER_FALLBACK",
                    )
                )
            else:
                report.status = "invalid_configuration"
                report.summary = {
                    **capabilities,
                    "backend": selected_backend,
                    "reason_code": "SEMANTIC_BACKEND_UNAVAILABLE",
                    "message": str(exc),
                }
                return report
        else:
            new_symbols_by_path: dict[str, list[dict[str, object]]] = {}
            for item in new_symbols:
                if isinstance(item, dict) and isinstance(item.get("path"), str):
                    new_symbols_by_path.setdefault(str(item["path"]), []).append(item)

            for path in paths_to_index:
                rel = path.relative_to(root).as_posix()
                file_syms = new_symbols_by_path.get(rel, [])
                assembled_by_path[rel] = file_syms
                symbols.extend(file_syms)
                current_file_hashes[rel] = calculated_hashes[rel]

            for file_syms in cached_to_reuse.values():
                symbols.extend(file_syms)

            known_paths = {p.relative_to(root).as_posix() for p in paths}
            for item in new_symbols:
                if isinstance(item, dict) and str(item.get("path", "")) not in known_paths:
                    symbols.append(item)
    else:
        for file_syms in cached_to_reuse.values():
            symbols.extend(file_syms)

    bounded_symbols = symbols[:10_000]
    is_truncated = len(symbols) > 10_000

    # Write internal full cache (unbounded, enables incremental indexing for >10k repos)
    cache_payload: dict[str, object] = {
        "schema_version": SEMANTIC_SCHEMA_VERSION,
        "fingerprint": current_fingerprint,
        "backend": selected_backend,
        "extractor_version": SEMANTIC_EXTRACTOR_VERSION,
        "files_considered": len(paths),
        "total_symbols": len(symbols),
        "file_hashes": current_file_hashes,
        "file_symbols": assembled_by_path,
    }

    # Write external bounded index (max 10,000 symbols)
    index_payload: dict[str, object] = {
        "schema_version": SEMANTIC_SCHEMA_VERSION,
        "fingerprint": current_fingerprint,
        "backend": selected_backend,
        "files_considered": len(paths),
        "symbols": bounded_symbols,
        "symbol_count": len(bounded_symbols),
        "total_symbol_count": len(symbols),
        "truncated": is_truncated,
        "file_hashes": current_file_hashes,
    }

    cache_unchanged = (
        not rebuild
        and is_incremental_candidate
        and not paths_to_index
        and current_file_hashes == cached_hashes
        and cache_path.exists()
        and output.exists()
    )
    if not cache_unchanged:
        _write_json(cache_path, cache_payload)
        _write_json(output, index_payload)

    files_total = len(paths)
    files_indexed = len(paths_to_index)
    files_reused = len(cached_to_reuse)
    files_omitted = max(0, files_total - (files_indexed + files_reused))

    report.summary = {
        **capabilities,
        "schema_version": index_payload["schema_version"],
        "fingerprint": current_fingerprint,
        "backend": selected_backend,
        "files_considered": files_total,
        "files_total": files_total,
        "files_indexed": files_indexed,
        "files_reused": files_reused,
        "files_omitted": files_omitted,
        "symbol_count": len(bounded_symbols),
        "total_symbol_count": len(symbols),
        "truncated": index_payload["truncated"],
    }
    report.artifacts.append(Artifact(str(output), "semantic-index", "Local semantic symbol index"))
    if index_payload["truncated"]:
        report.status = "partial"
        report.issues.append(
            Issue(
                "warning",
                "Semantic index reached its 10,000 symbol bound.",
                code="SEMANTIC_INDEX_TRUNCATED",
            )
        )
    if files_omitted > 0:
        report.status = "partial"
        report.issues.append(
            Issue(
                "warning",
                f"{files_omitted} files could not be indexed by backend {selected_backend}.",
                code="SEMANTIC_FILES_OMITTED",
            )
        )
    return report


def semantic_capabilities() -> dict[str, object]:
    plugins = sorted(_backend_entry_points())
    lsp = {
        language: [name for name in names if _which_cached(shutil.which, name)]
        for language, names in LSP_EXECUTABLES.items()
    }
    return {
        "protocol_version": "1",
        "default_backend": "treesitter_if_available",
        "available_backends": ["structural", "treesitter", "lsp", *plugins],
        "treesitter_available": tree_sitter_available(),
        "plugin_group": "ai_dev_tools.semantic_backends",
        "lsp_servers": lsp,
        "lsp_available": any(lsp.values()),
        "fallback": "structural",
        "local_only": True,
    }


def _index_with_backend(root: Path, paths: list[Path], backend: str) -> list[dict[str, object]]:
    if backend == "structural":
        return _structural_index(root, paths)
    if backend == "treesitter":
        return tree_sitter_index(root, paths)
    if backend == "lsp":
        return lsp_index(root, paths)
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
    for path in paths:
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


@lru_cache(maxsize=1)
def _backend_entry_points() -> dict[str, importlib.metadata.EntryPoint]:
    points = importlib.metadata.entry_points().select(group="ai_dev_tools.semantic_backends")
    return {point.name: point for point in points}


def _read_json(path: Path) -> dict[str, object] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except (OSError, json.JSONDecodeError):
        pass
    return None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with open(path, "rb") as stream:
            while chunk := stream.read(65536):
                digest.update(chunk)
    except OSError:
        return ""
    return digest.hexdigest()


def _write_json(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(
        f"{path.name}.{os.getpid()}.{threading.get_ident()}.{time.time_ns()}.tmp"
    )
    try:
        temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        for attempt in range(20):
            try:
                os.replace(temporary, path)
                break
            except PermissionError:
                if attempt == 19:
                    raise
                time.sleep(0.01 * (attempt + 1))
    finally:
        if temporary.exists():
            with contextlib.suppress(OSError):
                temporary.unlink()
