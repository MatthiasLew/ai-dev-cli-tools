from __future__ import annotations

import hashlib
import json
from copy import deepcopy

from ai_dev_tools.context.adaptive import adaptive_task_scope


def feedback_state_fingerprint(
    task: str,
    changed_files: list[str],
    validation: dict[str, object],
    context: dict[str, object],
    *,
    change_fingerprint: str = "",
) -> str:
    incremental = context.get("incremental")
    context_id = incremental.get("context_id") if isinstance(incremental, dict) else None
    payload = {
        "task_scope": adaptive_task_scope(task),
        "changed_files": sorted(set(changed_files)),
        "change_fingerprint": change_fingerprint,
        "validation": {
            "status": validation.get("status"),
            "checks_total": validation.get("checks_total"),
            "checks_failed": validation.get("checks_failed"),
            "failure_signatures": validation.get("failure_signatures", []),
            "results": _validation_result_fingerprints(validation),
        },
        "context": {
            "status": context.get("status"),
            "context_id": context_id,
            "selected_files": [] if context_id else _selected_file_fingerprints(context),
        },
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:20]


def apply_feedback_delta(
    summary: dict[str, object],
    *,
    acknowledged_fingerprint: str | None,
    current_fingerprint: str,
    enabled: bool,
    eligible: bool,
) -> dict[str, object]:
    projected = deepcopy(summary)
    reason = _reason(enabled, eligible, acknowledged_fingerprint, current_fingerprint)
    reused = reason == "UNCHANGED_SUCCESS_REUSED"
    before = _serialized_chars(projected)
    if reused:
        projected["validation"] = _validation_receipt(projected.get("validation"))
        projected["context"] = _context_receipt(projected.get("context"))
        projected["observations"] = _observation_receipt(projected.get("observations"))
    projected["delta"] = {
        "enabled": enabled,
        "reused": reused,
        "reason_code": reason,
        "state_fingerprint": current_fingerprint,
        "acknowledged_fingerprint": acknowledged_fingerprint,
        "chars_avoided": 0,
        "expansion_command": "ai-dev explain <evidence-id> --tail 100",
    }
    delta = projected["delta"]
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
        return "SESSION_DELTA_DISABLED"
    if not eligible:
        return "LIVE_EVIDENCE_REQUIRED"
    if acknowledged_fingerprint is None:
        return "ACKNOWLEDGEMENT_REQUIRED"
    if acknowledged_fingerprint != current_fingerprint:
        return "ACKNOWLEDGED_STATE_CHANGED"
    return "UNCHANGED_SUCCESS_REUSED"


def _validation_receipt(value: object) -> dict[str, object]:
    validation = value if isinstance(value, dict) else {}
    results = validation.get("results")
    return {
        "status": validation.get("status"),
        "checks_total": validation.get("checks_total", 0),
        "checks_failed": validation.get("checks_failed", 0),
        "failure_signatures": validation.get("failure_signatures", []),
        "result_count": len(results) if isinstance(results, list) else 0,
        "unchanged": True,
        "reason_code": "UNCHANGED_SUCCESS_REUSED",
    }


def _context_receipt(value: object) -> dict[str, object]:
    context = value if isinstance(value, dict) else {}
    selected = context.get("selected_files")
    return {
        "status": context.get("status"),
        "selected_file_count": len(selected) if isinstance(selected, list) else 0,
        "incremental": context.get("incremental", {}),
        "unchanged": True,
        "reason_code": "UNCHANGED_SUCCESS_REUSED",
    }


def _observation_receipt(value: object) -> dict[str, object]:
    observations = value if isinstance(value, dict) else {}
    current = observations.get("current")
    referenced = observations.get("referenced")
    current_dict = current if isinstance(current, dict) else {}
    return {
        "schema_version": observations.get("schema_version"),
        "current_evidence_id": current_dict.get("evidence_id"),
        "current_status": current_dict.get("status"),
        "current_retained_reasons": observations.get("current_retained_reasons", []),
        "referenced_count": len(referenced) if isinstance(referenced, list) else 0,
        "duplicate_observations_suppressed": observations.get(
            "duplicate_observations_suppressed", 0
        ),
        "expansion_command": "ai-dev explain <evidence-id> --tail 100",
    }


def _selected_file_fingerprints(context: dict[str, object]) -> list[dict[str, object]]:
    selected = context.get("selected_files")
    if not isinstance(selected, list):
        return []
    return [
        {
            "path": item.get("path"),
            "chars": item.get("chars"),
            "truncated": item.get("truncated"),
            "omitted_content_sha256": item.get("omitted_content_sha256"),
        }
        for item in selected
        if isinstance(item, dict)
    ]


def _validation_result_fingerprints(
    validation: dict[str, object],
) -> list[dict[str, object]]:
    results = validation.get("results")
    if not isinstance(results, list):
        return []
    stable_keys = (
        "name",
        "command",
        "workspace",
        "status",
        "exit_code",
        "failure_signature",
        "first_failure",
        "flaky",
        "reason_code",
    )
    return [
        {key: item[key] for key in stable_keys if key in item}
        for item in results
        if isinstance(item, dict)
    ]


def _serialized_chars(value: object) -> int:
    return len(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str))
