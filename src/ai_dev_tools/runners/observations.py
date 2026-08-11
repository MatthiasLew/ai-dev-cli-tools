from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any

from ai_dev_tools.security.secrets import mask_text

OBSERVATION_SCHEMA_VERSION = "1"
MAX_REFERENCES = 20


def update_observation_lifecycle(
    root: Path, current: dict[str, object]
) -> tuple[dict[str, Any], Path]:
    path = _manifest_path(root)
    manifest = _load_manifest(path)
    references = _dict_list(manifest.get("referenced"))
    duplicate_count = _integer(manifest.get("duplicate_observations_suppressed"))
    previous = manifest.get("current")

    current_record = _record(current)
    if isinstance(previous, dict):
        if previous.get("fingerprint") == current_record["fingerprint"]:
            duplicate_count += 1
        else:
            reference = _archive_observation(root, previous)
            references = [
                reference,
                *[
                    item
                    for item in references
                    if item.get("evidence_id") != reference["evidence_id"]
                ],
            ][:MAX_REFERENCES]

    lifecycle = {
        "schema_version": OBSERVATION_SCHEMA_VERSION,
        "current": current_record,
        "current_retained_reasons": _retained_reasons(current_record),
        "referenced": references,
        "superseded_count": len(references),
        "duplicate_observations_suppressed": duplicate_count,
        "referenced_chars_avoided": sum(_integer(item.get("size_chars")) for item in references),
        "expansion_command": "ai-dev explain <observation-evidence-id> --tail 100",
    }
    _atomic_write(path, lifecycle)
    return lifecycle, path


def _record(value: dict[str, object]) -> dict[str, object]:
    clean = _json_object(mask_text(json.dumps(value, sort_keys=True, default=str)))
    encoded = json.dumps(clean, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    fingerprint = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
    return {
        "evidence_id": f"observation:{fingerprint[:12]}",
        "fingerprint": f"sha256:{fingerprint}",
        "size_chars": len(encoded),
        **clean,
    }


def _archive_observation(root: Path, record: dict[str, object]) -> dict[str, object]:
    evidence_id = str(record.get("evidence_id", ""))
    if re.fullmatch(r"observation:[0-9a-f]{12}", evidence_id) is None:
        record = _record({key: value for key, value in record.items() if key != "evidence_id"})
        evidence_id = str(record["evidence_id"])
    suffix = evidence_id.partition(":")[2]
    archive = root / ".ai" / "cache" / "evidence" / f"observation-{suffix}.json"
    _atomic_write(archive, record)
    return {
        "evidence_id": evidence_id,
        "fingerprint": record.get("fingerprint"),
        "size_chars": _integer(record.get("size_chars")),
        "status": record.get("status"),
        "failure_signatures": record.get("failure_signatures", []),
        "retrieval_command": f"ai-dev explain {evidence_id} --tail 100",
        "reason_code": "SUPERSEDED_OBSERVATION_REFERENCED",
    }


def _retained_reasons(record: dict[str, object]) -> list[str]:
    status = str(record.get("status", ""))
    reasons: list[str] = []
    if status == "failed" or record.get("failure_signatures"):
        reasons.append("current_failure")
    if status in {"partial", "warning"} or record.get("unresolved_warnings"):
        reasons.append("unresolved_warning")
    if status == "success":
        reasons.append("final_verification")
    return reasons or ["current_observation"]


def _load_manifest(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict) or payload.get("schema_version") != OBSERVATION_SCHEMA_VERSION:
        return {}
    return payload


def _atomic_write(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        mask_text(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"),
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _manifest_path(root: Path) -> Path:
    return root / ".ai" / "cache" / "observations.json"


def _json_object(text: str) -> dict[str, object]:
    payload = json.loads(text)
    return payload if isinstance(payload, dict) else {}


def _dict_list(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _integer(value: object) -> int:
    return value if isinstance(value, int) else 0
