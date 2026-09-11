from __future__ import annotations

import contextlib
import json
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from ai_dev_tools.community.config import get_user_data_dir
from ai_dev_tools.community.schema import MAX_PAYLOAD_BYTES, validate_community_payload

MAX_QUEUE_ITEMS = 1000
MAX_EVENT_AGE_SECONDS = 7 * 86400  # 7 days


def get_queue_dir() -> Path:
    return get_user_data_dir() / "queue"


def enqueue_event(payload: dict[str, Any]) -> Path | None:
    validate_community_payload(payload)
    serialized = json.dumps(payload, indent=2, sort_keys=True)
    raw_bytes = serialized.encode("utf-8")
    if len(raw_bytes) > MAX_PAYLOAD_BYTES:
        return None

    queue_dir = get_queue_dir()
    queue_dir.mkdir(parents=True, exist_ok=True)

    prune_queue()

    # File naming: <timestamp_ns>_<thread_id>_<unique_hex>_<event_id>.json
    event_id = str(payload.get("event_id", "unknown"))
    timestamp_ns = time.time_ns()
    thread_id = threading.get_ident()
    unique_suffix = uuid.uuid4().hex[:8]
    filename = f"{timestamp_ns}_{thread_id}_{unique_suffix}_{event_id}.json"
    target_path = queue_dir / filename
    temp_path = queue_dir / f"{filename}.{os.getpid()}.{thread_id}.tmp"

    try:
        temp_path.write_bytes(raw_bytes)
        temp_path.replace(target_path)
    except OSError:
        if temp_path.exists():
            with contextlib.suppress(OSError):
                temp_path.unlink()
        return None

    return target_path


def list_queued_events() -> list[tuple[Path, dict[str, Any]]]:
    queue_dir = get_queue_dir()
    if not queue_dir.is_dir():
        return []

    events: list[tuple[Path, dict[str, Any]]] = []
    # Sorted chronologically by name (which starts with timestamp_ns)
    try:
        paths = sorted(queue_dir.glob("*.json"))
    except OSError:
        return []

    now = time.time()
    for path in paths:
        try:
            stat = path.stat()
            if now - stat.st_mtime > MAX_EVENT_AGE_SECONDS:
                path.unlink(missing_ok=True)
                continue
            if stat.st_size > MAX_PAYLOAD_BYTES:
                path.unlink(missing_ok=True)
                continue
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                validate_community_payload(data)
                events.append((path, data))
            else:
                path.unlink(missing_ok=True)
        except (OSError, json.JSONDecodeError, ValueError):
            # Corrupt or unreadable file: drop it
            with contextlib.suppress(OSError):
                path.unlink(missing_ok=True)

    return events


def queue_size() -> int:
    queue_dir = get_queue_dir()
    if not queue_dir.is_dir():
        return 0
    try:
        return len(list(queue_dir.glob("*.json")))
    except OSError:
        return 0


def remove_event(path: Path) -> None:
    with contextlib.suppress(OSError):
        path.unlink(missing_ok=True)


def prune_queue() -> int:
    queue_dir = get_queue_dir()
    if not queue_dir.is_dir():
        return 0

    removed = 0
    now = time.time()
    try:
        paths = sorted(queue_dir.glob("*.json"))
    except OSError:
        return 0

    # 1. Prune expired or oversize files
    valid_paths: list[Path] = []
    for path in paths:
        try:
            stat = path.stat()
            if now - stat.st_mtime > MAX_EVENT_AGE_SECONDS or stat.st_size > MAX_PAYLOAD_BYTES:
                path.unlink(missing_ok=True)
                removed += 1
            else:
                valid_paths.append(path)
        except OSError:
            pass

    # 2. Prune if count exceeds limit (keep newest MAX_QUEUE_ITEMS - 1)
    target_count = MAX_QUEUE_ITEMS - 1
    if len(valid_paths) > target_count:
        excess = len(valid_paths) - target_count
        to_delete = valid_paths[:excess]
        for p in to_delete:
            try:
                p.unlink(missing_ok=True)
                removed += 1
            except OSError:
                pass

    # Also clean any stale temp files
    try:
        for temp_file in queue_dir.glob("*.tmp"):
            try:
                if now - temp_file.stat().st_mtime > 3600:
                    temp_file.unlink(missing_ok=True)
            except OSError:
                pass
    except OSError:
        pass

    return removed


def clear_queue() -> int:
    queue_dir = get_queue_dir()
    if not queue_dir.is_dir():
        return 0

    deleted = 0
    try:
        for item in queue_dir.iterdir():
            if item.is_file():
                try:
                    item.unlink(missing_ok=True)
                    deleted += 1
                except OSError:
                    pass
    except OSError:
        pass
    return deleted
