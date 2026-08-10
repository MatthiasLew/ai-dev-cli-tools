from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from ai_dev_tools.cache.repository import update_repository_index

MANIFEST_SCHEMA_VERSION = "1"
MANIFEST_RELATIVE_PATH = Path(".ai/cache/context-manifest.json")


@dataclass(slots=True)
class IncrementalSelection:
    selected: list[Path]
    reused: list[str]
    current_hashes: dict[str, str]
    previous_hashes: dict[str, str]
    index_summary: dict[str, object]


def select_incremental(root: Path, candidates: list[Path]) -> IncrementalSelection:
    index = update_repository_index(root)
    current_hashes = _index_hashes(index.get("entries"))
    previous_hashes = _manifest_hashes(root)
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
) -> tuple[Path, str]:
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
        "files": hashes,
    }
    manifest_path = root.resolve() / MANIFEST_RELATIVE_PATH
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = manifest_path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, manifest_path)
    return manifest_path, context_id


def _manifest_hashes(root: Path) -> dict[str, str]:
    path = root.resolve() / MANIFEST_RELATIVE_PATH
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(value, dict) or value.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        return {}
    files = value.get("files")
    if not isinstance(files, dict):
        return {}
    return {
        str(key): item
        for key, item in files.items()
        if isinstance(key, str) and isinstance(item, str)
    }


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
