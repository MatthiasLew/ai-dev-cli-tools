from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from ai_dev_tools.cache.repository import update_repository_index

MANIFEST_SCHEMA_VERSION = "2"
MANIFEST_RELATIVE_PATH = Path(".ai/cache/context-manifest.json")
MANIFEST_HISTORY_RELATIVE_PATH = Path(".ai/cache/context-manifests")
_CONTEXT_ID = re.compile(r"^[0-9a-f]{16}$")
_MAX_MANIFESTS = 50


@dataclass(slots=True)
class IncrementalSelection:
    selected: list[Path]
    reused: list[str]
    current_hashes: dict[str, str]
    previous_hashes: dict[str, str]
    index_summary: dict[str, object]


def valid_context_id(context_id: str) -> bool:
    return _CONTEXT_ID.fullmatch(context_id) is not None


def load_incremental_manifest(root: Path, context_id: str) -> dict[str, str] | None:
    if not valid_context_id(context_id):
        return None
    return _read_manifest(
        root.resolve() / MANIFEST_HISTORY_RELATIVE_PATH / f"{context_id}.json",
        context_id,
    )


def select_incremental(
    root: Path,
    candidates: list[Path],
    previous_hashes: dict[str, str] | None = None,
    *,
    memory_scope: str | None = None,
) -> IncrementalSelection:
    index = update_repository_index(root)
    current_hashes = _index_hashes(index.get("entries"))
    if previous_hashes is None:
        previous_hashes = _manifest_hashes(root, memory_scope)
    selected: list[Path] = []
    reused: list[str] = []
    for path in candidates:
        relative = path.resolve().relative_to(root.resolve()).as_posix()
        digest = current_hashes.get(relative)
        if digest is None or previous_hashes.get(relative) != digest:
            selected.append(path)
        else:
            reused.append(relative)
    summary = index.get("summary")
    return IncrementalSelection(
        selected=selected,
        reused=reused,
        current_hashes=current_hashes,
        previous_hashes=previous_hashes,
        index_summary=summary if isinstance(summary, dict) else {},
    )


def save_incremental_manifest(
    root: Path,
    state: IncrementalSelection,
    emitted_paths: list[str],
    *,
    memory_scope: str | None = None,
) -> tuple[Path, Path, str]:
    hashes = {
        path: digest
        for path, digest in state.previous_hashes.items()
        if path in state.current_hashes
    }
    for emitted_path in emitted_paths:
        digest = state.current_hashes.get(emitted_path)
        if digest is not None:
            hashes[emitted_path] = digest
    canonical = json.dumps(hashes, sort_keys=True, separators=(",", ":"))
    context_id = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]
    payload: dict[str, object] = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "context_id": context_id,
        "generated_at": datetime.now(UTC).isoformat(),
        "memory_scope": memory_scope,
        "files": hashes,
    }
    resolved = root.resolve()
    manifest_path = resolved / MANIFEST_RELATIVE_PATH
    history_path = resolved / MANIFEST_HISTORY_RELATIVE_PATH / f"{context_id}.json"
    _write_manifest(manifest_path, payload)
    _write_manifest(history_path, payload)
    _prune_history(history_path.parent)
    return manifest_path, history_path, context_id


def _manifest_hashes(root: Path, memory_scope: str | None) -> dict[str, str]:
    path = root.resolve() / MANIFEST_RELATIVE_PATH
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(value, dict) or value.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        return {}
    if memory_scope is not None and value.get("memory_scope") != memory_scope:
        return {}
    files = value.get("files")
    if not isinstance(files, dict):
        return {}
    return {
        str(key): item
        for key, item in files.items()
        if isinstance(key, str) and isinstance(item, str)
    }


def _read_manifest(path: Path, expected_id: str | None = None) -> dict[str, str] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(value, dict) or value.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        return None
    if expected_id is not None and value.get("context_id") != expected_id:
        return None
    files = value.get("files")
    if not isinstance(files, dict):
        return None
    return {
        str(key): item
        for key, item in files.items()
        if isinstance(key, str) and isinstance(item, str)
    }


def _write_manifest(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _prune_history(directory: Path) -> None:
    manifests = sorted(
        directory.glob("*.json"), key=lambda path: path.stat().st_mtime, reverse=True
    )
    for path in manifests[_MAX_MANIFESTS:]:
        path.unlink(missing_ok=True)


def _index_hashes(value: object) -> dict[str, str]:
    if not isinstance(value, list):
        return {}
    result: dict[str, str] = {}
    for item in value:
        if not isinstance(item, dict):
            continue
        path = item.get("path")
        digest = item.get("sha256")
        if isinstance(path, str) and isinstance(digest, str):
            result[path] = digest
    return result
