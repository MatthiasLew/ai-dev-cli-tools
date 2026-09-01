from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path

from ai_dev_tools.cache.repository import read_repository_index, repository_fingerprint


def context_state_fingerprint(root: Path, arguments: dict[str, object]) -> str:
    """Bind an acknowledgement to repository content and the semantic MCP request."""
    index = read_repository_index(root)
    request = {
        key: value
        for key, value in arguments.items()
        if key not in {"acknowledged_state", "delta"}
    }
    canonical_request = json.dumps(
        request, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
    )
    repository_state = repository_fingerprint(
        index.get("entries", []), extra=(canonical_request,)
    )
    return hashlib.sha256(repository_state.encode("utf-8")).hexdigest()[:20]


def apply_context_delta(
    payload: dict[str, object],
    *,
    acknowledged_fingerprint: str | None,
    current_fingerprint: str,
    enabled: bool,
    eligible: bool,
) -> dict[str, object]:
    projected = deepcopy(payload)
    summary = projected.get("summary")
    if not isinstance(summary, dict):
        return projected
    reason = _reason(enabled, eligible, acknowledged_fingerprint, current_fingerprint)
    reused = reason == "UNCHANGED_CONTEXT_REUSED"
    before = _serialized_chars(projected)
    live_context_chars_avoided = 0
    if reused:
        live_context_chars_avoided = _live_context_chars(summary)
        receipt = _context_receipt(summary)
        projected["summary"] = receipt
        summary = receipt
    summary["delta"] = {
        "enabled": enabled,
        "reused": reused,
        "reason_code": reason,
        "state_fingerprint": current_fingerprint,
        "acknowledged_fingerprint": acknowledged_fingerprint,
        "chars_avoided": 0,
        "live_context_chars_avoided": live_context_chars_avoided,
        "expansion_hint": "Call build_context with delta=false to request full live context.",
    }
    delta = summary["delta"]
    if isinstance(delta, dict):
        for _ in range(3):
            avoided = max(before - _serialized_chars(projected), 0)
            if delta["chars_avoided"] == avoided:
                break
            delta["chars_avoided"] = avoided
    return projected


def _reason(
    enabled: bool,
    eligible: bool,
    acknowledged_fingerprint: str | None,
    current_fingerprint: str,
) -> str:
    if not enabled:
        return "CONTEXT_DELTA_DISABLED"
    if not eligible:
        return "LIVE_CONTEXT_REQUIRED"
    if acknowledged_fingerprint is None:
        return "ACKNOWLEDGEMENT_REQUIRED"
    if acknowledged_fingerprint != current_fingerprint:
        return "ACKNOWLEDGED_CONTEXT_CHANGED"
    return "UNCHANGED_CONTEXT_REUSED"


def _context_receipt(summary: dict[str, object]) -> dict[str, object]:
    selected = summary.get("selected_files")
    incremental = summary.get("incremental")
    incremental_dict = incremental if isinstance(incremental, dict) else {}
    return {
        "task": summary.get("task", ""),
        "context_receipt": {
            "unchanged": True,
            "reason_code": "UNCHANGED_CONTEXT_REUSED",
            "selected_file_count": len(selected) if isinstance(selected, list) else 0,
            "context_id": incremental_dict.get("context_id"),
            "base_context_id": incremental_dict.get("base_context_id"),
        },
    }


def _serialized_chars(value: object) -> int:
    return len(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str))


def _live_context_chars(summary: dict[str, object]) -> int:
    omitted = {key: value for key, value in summary.items() if key != "task"}
    return _serialized_chars(omitted)
