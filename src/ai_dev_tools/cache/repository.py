from __future__ import annotations

import contextlib
import fnmatch
import hashlib
import json
import os
import posixpath
import subprocess
import threading
import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager, suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import TypedDict

from ai_dev_tools.cache.graph import build_impact_graph as build_impact_graph
from ai_dev_tools.config import DEFAULT_IGNORES, load_settings

INDEX_SCHEMA_VERSION = "1"
INDEX_RELATIVE_PATH = Path(".ai/cache/repository-index.json")
_COMMIT_LOCK_TIMEOUT_SECONDS = 10.0
_COMMIT_LOCK_STALE_SECONDS = 30.0


@contextmanager
def _commit_lock(
    index_path: Path, timeout: float = _COMMIT_LOCK_TIMEOUT_SECONDS
) -> Iterator[None]:
    lock = index_path.with_suffix(".lock")
    lock.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + timeout
    acquired = False
    while True:
        try:
            descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(descriptor)
            acquired = True
            break
        except (FileExistsError, PermissionError):
            try:
                if time.time() - lock.stat().st_mtime > _COMMIT_LOCK_STALE_SECONDS:
                    with suppress(OSError):
                        lock.unlink()
                    continue
            except OSError:
                pass
            if time.monotonic() >= deadline:
                break
            time.sleep(0.01)
    if not acquired:
        raise TimeoutError(
            f"Could not acquire repository commit lock for {index_path} within {timeout}s"
        )
    try:
        yield
    finally:
        with suppress(OSError):
            lock.unlink()


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
    settings = load_settings(resolved_root)
    custom_ignores = (settings.ignore_paths - DEFAULT_IGNORES) | {".ai", ".git"}
    fallback_ignores = {
        item.replace(chr(92), "/").strip("/")
        for item in (DEFAULT_IGNORES | settings.ignore_paths)
        if item.strip()
    }

    file_entries = list(_project_file_entries(resolved_root, custom_ignores, fallback_ignores))
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

    with _commit_lock(index_path):
        known_previous = set(previous_entries)
        latest_on_disk = read_repository_index(resolved_root)
        if latest_on_disk and latest_on_disk.get("generated_at"):
            disk_time = str(latest_on_disk.get("generated_at", ""))
            prev_time = str(previous.get("generated_at", ""))
            if disk_time > prev_time:
                disk_entry_map = _entry_map(latest_on_disk.get("entries"))
                known_previous = set(disk_entry_map)
                for entry in final_entries:
                    disk_entry = disk_entry_map.get(entry["path"])
                    if disk_entry and disk_entry["mtime_ns"] > entry["mtime_ns"]:
                        entry["size"] = disk_entry["size"]
                        entry["mtime_ns"] = disk_entry["mtime_ns"]
                        entry["sha256"] = disk_entry["sha256"]
                for path_key, disk_entry in disk_entry_map.items():
                    if path_key not in {e["path"] for e in final_entries} and (
                        resolved_root / path_key
                    ).exists():
                        final_entries.append(disk_entry)
                final_entries = [e for e in final_entries if (resolved_root / e["path"]).exists()]
                final_entries.sort(key=lambda e: e["path"])
                merged_paths = {item["path"] for item in final_entries}
                reused_paths = {
                    item["path"]
                    for item in final_entries
                    if item["path"] in disk_entry_map or item["path"] in reused_paths
                }
                graph = build_impact_graph(
                    resolved_root,
                    merged_paths,
                    reused_paths=reused_paths,
                    previous_edges=latest_on_disk.get("graph"),
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
                "removed": len(known_previous - {item["path"] for item in final_entries}),
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


def _git_project_file_entries(
    root: Path, custom_ignores: set[str]
) -> list[tuple[Path, str, os.stat_result]] | None:
    try:
        proc = subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
            cwd=root,
            capture_output=True,
            text=False,
            timeout=10,
        )
        if proc.returncode != 0:
            return None
        parts = [
            p.decode("utf-8", errors="surrogateescape")
            for p in proc.stdout.split(b"\0")
            if p
        ]
        entries: list[tuple[Path, str, os.stat_result]] = []
        for rel in sorted(parts):
            rel_normalized = rel.replace("\\", "/").strip("/")
            if is_ignored_path(rel_normalized, custom_ignores):
                continue
            path = root / rel_normalized
            try:
                stat = path.stat(follow_symlinks=False)
            except OSError:
                continue
            entries.append((path, rel_normalized, stat))
        return entries
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return None


def _project_file_entries(
    root: Path, custom_ignores: set[str], fallback_ignores: set[str]
) -> list[tuple[Path, str, os.stat_result]]:
    git_entries = _git_project_file_entries(root, custom_ignores)
    if git_entries is not None:
        return git_entries

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
                if _is_ignored_name(name, fallback_ignores):
                    continue
                if parent_name in {"test", "tests"} and name == "fixtures":
                    continue
                if is_ignored_path(rel_path, fallback_ignores):
                    continue
                subdirs.append(entry)
            else:
                try:
                    if not entry.is_file(follow_symlinks=False):
                        continue
                except OSError:
                    continue
                if _is_ignored_name(name, fallback_ignores):
                    continue
                if is_ignored_path(rel_path, fallback_ignores):
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
    return [path for path, _, _ in _project_file_entries(root, set(), ignored)]


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
