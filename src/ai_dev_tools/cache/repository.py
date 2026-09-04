from __future__ import annotations

import fnmatch
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import TypedDict

from ai_dev_tools.cache.graph import build_impact_graph
from ai_dev_tools.config import DEFAULT_IGNORES

INDEX_SCHEMA_VERSION = "1"
INDEX_RELATIVE_PATH = Path(".ai/cache/repository-index.json")


class IndexEntry(TypedDict):
    path: str
    size: int
    mtime_ns: int
    sha256: str


def update_repository_index(root: Path, *, rebuild: bool = False) -> dict[str, object]:
    resolved_root = root.resolve()
    index_path = resolved_root / INDEX_RELATIVE_PATH
    previous = {} if rebuild else read_repository_index(resolved_root)
    previous_entries = _entry_map(previous.get("entries"))
    entries: list[IndexEntry] = []
    reused = 0
    hashed = 0
    reused_paths: set[str] = set()

    for path in _project_files(resolved_root):
        relative = path.relative_to(resolved_root).as_posix()
        stat = path.stat()
        old = previous_entries.get(relative)
        if old is not None and old["size"] == stat.st_size and old["mtime_ns"] == stat.st_mtime_ns:
            digest = old["sha256"]
            reused += 1
            reused_paths.add(relative)
        else:
            digest = _sha256(path)
            hashed += 1
        entries.append(
            {
                "path": relative,
                "size": stat.st_size,
                "mtime_ns": stat.st_mtime_ns,
                "sha256": digest,
            }
        )

    graph = build_impact_graph(
        resolved_root,
        {item["path"] for item in entries},
        reused_paths=reused_paths,
        previous_edges=previous.get("graph"),
    )

    payload: dict[str, object] = {
        "schema_version": INDEX_SCHEMA_VERSION,
        "project_root": str(resolved_root),
        "generated_at": datetime.now(UTC).isoformat(),
        "entries": entries,
        "graph": graph,
        "summary": {
            "files": len(entries),
            "hashed": hashed,
            "reused": reused,
            "removed": len(set(previous_entries) - {item["path"] for item in entries}),
            "graph_edges": len(graph),
        },
    }
    _write_json(index_path, payload)
    return payload


def read_repository_index(root: Path) -> dict[str, object]:
    path = root.resolve() / INDEX_RELATIVE_PATH
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(value, dict) or value.get("schema_version") != INDEX_SCHEMA_VERSION:
        return {}
    return value


def repository_fingerprint(
    entries: object, workspace: str = "", extra: tuple[str, ...] = ()
) -> str:
    prefix = workspace.replace(chr(92), "/").strip("/")
    selected = []
    for entry in _entry_list(entries):
        path = entry["path"]
        if not prefix or path == prefix or path.startswith(prefix + "/"):
            selected.append((path, entry["sha256"]))
    payload = json.dumps(
        {"workspace": prefix, "files": selected, "extra": extra},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _is_ignored_name(name: str, ignored: set[str]) -> bool:
    if name in ignored:
        return True
    return any(
        fnmatch.fnmatch(name, pat)
        or (
            pat in {".venv", "venv"}
            and (
                name.startswith(f"{pat}-")
                or name.startswith(f"{pat}_")
                or (len(name) > len(pat) and name.startswith(pat))
            )
        )
        for pat in ignored
    )


def _is_ignored_path(relative: str, ignored: set[str]) -> bool:
    parts = relative.split("/")
    if any(_is_ignored_name(part, ignored) for part in parts):
        return True
    return any(
        relative == item
        or relative.startswith(f"{item}/")
        or fnmatch.fnmatch(relative, item)
        or fnmatch.fnmatch(Path(relative).name, item)
        for item in ignored
    )


def _project_files(root: Path) -> list[Path]:
    ignored = {item.replace(chr(92), "/").strip("/") for item in DEFAULT_IGNORES}
    files: list[Path] = []
    for current, directories, names in os.walk(root, followlinks=False):
        current_path = Path(current)
        directories[:] = sorted(
            name
            for name in directories
            if not _is_ignored_name(name, ignored)
            and not (current_path.name in {"test", "tests"} and name == "fixtures")
        )
        for name in sorted(names):
            path = current_path / name
            if path.is_symlink() or not path.is_file():
                continue
            relative = path.relative_to(root).as_posix()
            if _is_ignored_path(relative, ignored):
                continue
            files.append(path)
    return files


def _entry_map(value: object) -> dict[str, IndexEntry]:
    return {entry["path"]: entry for entry in _entry_list(value)}


def _entry_list(value: object) -> list[IndexEntry]:
    if not isinstance(value, list):
        return []
    result: list[IndexEntry] = []
    for item in value:
        if (
            isinstance(item, dict)
            and isinstance(item.get("path"), str)
            and isinstance(item.get("size"), int)
            and isinstance(item.get("mtime_ns"), int)
            and isinstance(item.get("sha256"), str)
        ):
            result.append(
                {
                    "path": item["path"],
                    "size": item["size"],
                    "mtime_ns": item["mtime_ns"],
                    "sha256": item["sha256"],
                }
            )
    return result


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)
