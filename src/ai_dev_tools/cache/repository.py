from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import posixpath
import time
from concurrent.futures import ThreadPoolExecutor
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
    reused = 0
    reused_paths: set[str] = set()
    ignored = {item.replace(chr(92), "/").strip("/") for item in DEFAULT_IGNORES}

    file_entries = list(_project_file_entries(resolved_root, ignored))
    entries: list[IndexEntry | None] = [None] * len(file_entries)
    to_hash: list[tuple[int, Path, str, os.stat_result]] = []

    for idx, (path, relative, stat) in enumerate(file_entries):
        old = previous_entries.get(relative)
        if old is not None and old["size"] == stat.st_size and old["mtime_ns"] == stat.st_mtime_ns:
            entries[idx] = {
                "path": relative,
                "size": stat.st_size,
                "mtime_ns": stat.st_mtime_ns,
                "sha256": old["sha256"],
            }
            reused += 1
            reused_paths.add(relative)
        else:
            to_hash.append((idx, path, relative, stat))

    hashed = len(to_hash)
    if hashed == 1:
        idx, path, relative, stat = to_hash[0]
        entries[idx] = {
            "path": relative,
            "size": stat.st_size,
            "mtime_ns": stat.st_mtime_ns,
            "sha256": _sha256(path),
        }
    elif hashed > 1:
        workers = min(hashed, min(8, os.cpu_count() or 4))
        if workers > 1:
            with ThreadPoolExecutor(max_workers=workers) as executor:
                digests = list(executor.map(_sha256, [item[1] for item in to_hash]))
            for (idx, _path, relative, stat), digest in zip(to_hash, digests, strict=True):
                entries[idx] = {
                    "path": relative,
                    "size": stat.st_size,
                    "mtime_ns": stat.st_mtime_ns,
                    "sha256": digest,
                }
        else:
            for idx, path, relative, stat in to_hash:
                entries[idx] = {
                    "path": relative,
                    "size": stat.st_size,
                    "mtime_ns": stat.st_mtime_ns,
                    "sha256": _sha256(path),
                }

    final_entries: list[IndexEntry] = [item for item in entries if item is not None]

    graph = build_impact_graph(
        resolved_root,
        {item["path"] for item in final_entries},
        reused_paths=reused_paths,
        previous_edges=previous.get("graph"),
    )

    payload: dict[str, object] = {
        "schema_version": INDEX_SCHEMA_VERSION,
        "project_root": str(resolved_root),
        "generated_at": datetime.now(UTC).isoformat(),
        "entries": final_entries,
        "graph": graph,
        "summary": {
            "files": len(final_entries),
            "hashed": hashed,
            "reused": reused,
            "removed": len(set(previous_entries) - {item["path"] for item in final_entries}),
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
    if name.startswith((".venv-", ".venv_", "venv-", "venv_")):
        return True
    if name.startswith(".venv") or (len(name) > 4 and name.startswith("venv")):
        return True
    return any(("*" in pat or "?" in pat) and fnmatch.fnmatch(name, pat) for pat in ignored)


def is_ignored_path(relative: str, ignored: set[str]) -> bool:
    parts = relative.split("/")
    if any(_is_ignored_name(part, ignored) for part in parts):
        return True
    if relative in ignored:
        return True
    for item in ignored:
        if relative.startswith(f"{item}/"):
            return True
        if ("*" in item or "?" in item) and (
            fnmatch.fnmatch(relative, item) or fnmatch.fnmatch(posixpath.basename(relative), item)
        ):
            return True
    return False


def _project_file_entries(root: Path, ignored: set[str]) -> list[tuple[Path, str, os.stat_result]]:
    entries: list[tuple[Path, str, os.stat_result]] = []

    def _walk(current_dir: str, rel_prefix: str, parent_name: str) -> None:
        try:
            with os.scandir(current_dir) as iterator:
                dir_entries = list(iterator)
        except OSError:
            return

        dir_entries.sort(key=lambda e: e.name)
        subdirs: list[os.DirEntry[str]] = []

        for entry in dir_entries:
            try:
                if entry.is_symlink():
                    continue
            except OSError:
                continue

            name = entry.name
            rel_path = f"{rel_prefix}/{name}" if rel_prefix else name

            try:
                is_dir = entry.is_dir(follow_symlinks=False)
            except OSError:
                continue

            if is_dir:
                if _is_ignored_name(name, ignored):
                    continue
                if parent_name in {"test", "tests"} and name == "fixtures":
                    continue
                if is_ignored_path(rel_path, ignored):
                    continue
                subdirs.append(entry)
            else:
                try:
                    if not entry.is_file(follow_symlinks=False):
                        continue
                except OSError:
                    continue
                if _is_ignored_name(name, ignored):
                    continue
                if is_ignored_path(rel_path, ignored):
                    continue
                try:
                    stat = entry.stat(follow_symlinks=False)
                except OSError:
                    continue
                entries.append((Path(entry.path), rel_path, stat))

        for subdir in subdirs:
            sub_rel = f"{rel_prefix}/{subdir.name}" if rel_prefix else subdir.name
            _walk(subdir.path, sub_rel, subdir.name)

    _walk(str(root), "", root.name)
    return entries


def _project_files(root: Path) -> list[Path]:
    ignored = {item.replace(chr(92), "/").strip("/") for item in DEFAULT_IGNORES}
    return [path for path, _, _ in _project_file_entries(root, ignored)]


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
    temporary = path.with_name(f"{path.name}.{os.getpid()}.{time.time_ns()}.tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)
