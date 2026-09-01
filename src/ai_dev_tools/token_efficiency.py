from __future__ import annotations

import json
import math
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

CLIENT_PROFILES: dict[str, dict[str, object]] = {
    "codex": {
        "context_profile": "minimal",
        "max_chars": 20_000,
        "max_files": 20,
        "max_file_chars": 4_000,
        "tokenizer": "estimate",
        "delta": True,
        "content_default": "references",
        "telemetry_tool": "record_usage",
        "telemetry_status_tool": "usage_status",
    },
    "claude": {
        "context_profile": "minimal",
        "max_chars": 24_000,
        "max_files": 24,
        "max_file_chars": 4_000,
        "tokenizer": "estimate",
        "delta": True,
        "content_default": "references",
        "telemetry_tool": "record_usage",
        "telemetry_status_tool": "usage_status",
    },
    "cursor": {
        "context_profile": "minimal",
        "max_chars": 16_000,
        "max_files": 16,
        "max_file_chars": 3_000,
        "tokenizer": "estimate",
        "delta": True,
        "content_default": "references",
        "telemetry_tool": "record_usage",
        "telemetry_status_tool": "usage_status",
    },
    "generic": {
        "context_profile": "minimal",
        "max_chars": 20_000,
        "max_files": 20,
        "max_file_chars": 4_000,
        "tokenizer": "estimate",
        "delta": True,
        "content_default": "references",
        "telemetry_tool": "record_usage",
        "telemetry_status_tool": "usage_status",
    },
}


def client_profile(client: str) -> dict[str, object]:
    try:
        return dict(CLIENT_PROFILES[client])
    except KeyError as exc:
        raise ValueError(f"unknown AI client: {client}") from exc


def load_acknowledged_state(root: Path, client: str, channel: str = "task") -> str | None:
    payload = _read_json(_state_path(root, client))
    value = payload.get("acknowledged_states", {}).get(channel)
    return value if isinstance(value, str) and value else None


def persist_acknowledged_state(
    root: Path, client: str, fingerprint: str, channel: str = "task"
) -> Path:
    path = _state_path(root, client)
    payload = _read_json(path)
    states = payload.get("acknowledged_states")
    if not isinstance(states, dict):
        states = {}
    states[channel] = fingerprint
    payload.update(
        {
            "schema_version": "1",
            "client": client,
            "acknowledged_states": states,
            "updated_at": datetime.now(UTC).isoformat(),
        }
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def compact_context(
    summary: dict[str, Any], *, include_content: bool
) -> tuple[dict[str, Any], dict[str, object]]:
    original_chars = _serialized_chars(summary)
    selected = summary.get("selected_files")
    rows = selected if isinstance(selected, list) else []
    diffs = summary.get("diffs")
    diff_rows = diffs if isinstance(diffs, list) else []
    rejected = summary.get("rejected_files")
    rejected_rows = rejected if isinstance(rejected, list) else []
    projected: dict[str, Any] = {
        "task": summary.get("task", ""),
        "selected_files": [
            _compact_evidence(item, include_content=include_content) for item in rows[:30]
        ],
        "rejected_files": [
            _compact_evidence(item, include_content=False) for item in rejected_rows[:20]
        ],
        "diffs": [
            _compact_evidence(item, include_content=include_content) for item in diff_rows[:10]
        ],
        "latest_errors": deepcopy(_bounded_list(summary.get("latest_errors"), 8)),
        "secret_findings": deepcopy(_bounded_list(summary.get("secret_findings"), 20)),
        "retrieval": _selected_fields(
            summary.get("retrieval"),
            ("mode", "decision", "reason_code", "confidence", "fallback"),
        ),
        "incremental": _selected_fields(
            summary.get("incremental"),
            (
                "enabled",
                "context_id",
                "base_context_id",
                "changed_candidates",
                "emitted",
                "reused",
                "deferred",
            ),
        ),
        "budget": _selected_fields(
            summary.get("budget"), ("max_chars", "used_chars", "truncated")
        ),
        "character_budget": _selected_fields(
            summary.get("character_budget"),
            ("chars_avoided", "content_omitted", "target_exceeded"),
        ),
    }
    compact_chars = _serialized_chars(projected)
    avoided_chars = max(original_chars - compact_chars, 0)
    receipt: dict[str, object] = {
        "schema_version": "1",
        "delivery": "full_content" if include_content else "references",
        "original_context_chars": original_chars,
        "delivered_context_chars": compact_chars,
        "chars_avoided": avoided_chars,
        "estimated_tokens_avoided": math.ceil(avoided_chars / 4),
        "included_files": len(rows),
        "expansion_command": "ai-dev explain <evidence-id> --tail 100",
    }
    return projected, receipt


def record_receipt(root: Path, receipt: dict[str, object], *, command: str, client: str) -> Path:
    directory = root / ".ai" / "token-efficiency"
    directory.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "1",
        "recorded_at": datetime.now(UTC).isoformat(),
        "command": command,
        "client": client,
        **receipt,
    }
    latest = directory / "latest.json"
    latest.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    historical = directory / "receipts" / f"{stamp}.json"
    historical.parent.mkdir(parents=True, exist_ok=True)
    historical.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return latest


def _state_path(root: Path, client: str) -> Path:
    client_profile(client)
    return root.resolve() / ".ai" / "cache" / "client-state" / f"{client}.json"


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _compact_evidence(value: object, *, include_content: bool) -> dict[str, object]:
    if not isinstance(value, dict):
        return {}
    allowed = (
        "path",
        "name",
        "reason",
        "reason_code",
        "evidence_id",
        "chars",
        "original_chars",
        "truncated",
        "omitted_content",
        "selection_strategy",
    )
    row = {key: deepcopy(value[key]) for key in allowed if key in value}
    content = str(value.get("content", ""))
    if include_content:
        row["content"] = content
    else:
        reference = str(value.get("evidence_id", "<evidence-id>"))
        row["content_reference"] = {
            "available": bool(content) or bool(value.get("omitted_content")),
            "chars": len(content),
            "command": f"ai-dev explain {reference} --tail 100",
        }
    return row


def _selected_fields(value: object, fields: tuple[str, ...]) -> dict[str, object]:
    if not isinstance(value, dict):
        return {}
    return {key: deepcopy(value[key]) for key in fields if key in value}


def _bounded_list(value: object, limit: int) -> list[object]:
    return list(value[:limit]) if isinstance(value, list) else []


def _serialized_chars(value: object) -> int:
    return len(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str))
