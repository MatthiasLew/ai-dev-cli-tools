from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

CHECKPOINT_SCHEMA_VERSION = "1"


def load_resume_keys(root: Path, current_keys: set[str]) -> set[str]:
    try:
        payload = json.loads(_checkpoint_path(root).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    if not isinstance(payload, dict) or payload.get("schema_version") != CHECKPOINT_SCHEMA_VERSION:
        return set()
    completed = payload.get("completed_keys")
    if not isinstance(completed, list):
        return set()
    return {key for key in completed if isinstance(key, str) and key in current_keys}


def write_checkpoint(
    root: Path,
    *,
    mode: str,
    task_keys: list[str],
    successful_keys: list[str],
    cancelled: int,
) -> Path:
    path = _checkpoint_path(root)
    payload = {
        "schema_version": CHECKPOINT_SCHEMA_VERSION,
        "mode": mode,
        "task_keys": task_keys,
        "completed_keys": successful_keys,
        "cancelled": cancelled,
        "complete": len(successful_keys) == len(task_keys),
        "updated_at": datetime.now(UTC).isoformat(),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)
    return path


def _checkpoint_path(root: Path) -> Path:
    return root.resolve() / ".ai" / "cache" / "check-checkpoint.json"
