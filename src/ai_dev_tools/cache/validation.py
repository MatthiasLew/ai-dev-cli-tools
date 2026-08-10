from __future__ import annotations

import json
import os
import platform
import sys
from datetime import UTC, datetime
from pathlib import Path

from ai_dev_tools.cache.repository import repository_fingerprint
from ai_dev_tools.utils.subprocess import CommandResult

CACHE_SCHEMA_VERSION = "1"
DEFAULT_MAX_ENTRIES = 200
DEFAULT_MAX_BYTES = 100 * 1024 * 1024


def validation_cache_key(
    entries: object,
    command: list[str],
    workspace: str,
) -> str:
    return repository_fingerprint(
        entries,
        workspace,
        (
            *command,
            platform.system(),
            platform.machine(),
            sys.version,
        ),
    )


def load_validation_result(
    root: Path,
    key: str,
    command: list[str],
) -> CommandResult | None:
    path = _cache_path(root, key)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if (
        not isinstance(value, dict)
        or value.get("schema_version") != CACHE_SCHEMA_VERSION
        or value.get("key") != key
        or value.get("command") != command
        or value.get("exit_code") != 0
    ):
        return None
    stdout = value.get("stdout")
    stderr = value.get("stderr")
    if not isinstance(stdout, str) or not isinstance(stderr, str):
        return None
    return CommandResult(
        command=command,
        exit_code=0,
        stdout=stdout,
        stderr=stderr,
        duration_seconds=0.0,
        timed_out=False,
        cached=True,
    )


def store_validation_result(root: Path, key: str, result: CommandResult) -> Path | None:
    if result.exit_code != 0 or result.timed_out:
        return None
    path = _cache_path(root, key)
    payload: dict[str, object] = {
        "schema_version": CACHE_SCHEMA_VERSION,
        "key": key,
        "command": result.command,
        "exit_code": result.exit_code,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "duration_seconds": result.duration_seconds,
        "created_at": datetime.now(UTC).isoformat(),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)
    prune_validation_cache(root)
    return path


def validation_cache_stats(root: Path) -> dict[str, int]:
    directory = root.resolve() / ".ai" / "cache" / "checks"
    files = list(directory.glob("*.json")) if directory.exists() else []
    sizes = [_safe_size(path) for path in files]
    return {"entries": len(files), "bytes": sum(sizes)}


def prune_validation_cache(
    root: Path,
    *,
    max_entries: int = DEFAULT_MAX_ENTRIES,
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> dict[str, int]:
    directory = root.resolve() / ".ai" / "cache" / "checks"
    files = sorted(
        directory.glob("*.json") if directory.exists() else [],
        key=_safe_mtime,
        reverse=True,
    )
    kept = 0
    kept_bytes = 0
    removed = 0
    removed_bytes = 0
    for path in files:
        size = _safe_size(path)
        if kept < max(max_entries, 0) and kept_bytes + size <= max(max_bytes, 0):
            kept += 1
            kept_bytes += size
            continue
        try:
            path.unlink()
        except OSError:
            continue
        removed += 1
        removed_bytes += size
    return {
        "entries": kept,
        "bytes": kept_bytes,
        "removed": removed,
        "removed_bytes": removed_bytes,
        "max_entries": max_entries,
        "max_bytes": max_bytes,
    }


def clear_validation_cache(root: Path) -> dict[str, int]:
    return prune_validation_cache(root, max_entries=0, max_bytes=0)


def _safe_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def _safe_mtime(path: Path) -> int:
    try:
        return path.stat().st_mtime_ns
    except OSError:
        return 0


def _cache_path(root: Path, key: str) -> Path:
    return root.resolve() / ".ai" / "cache" / "checks" / f"{key}.json"
