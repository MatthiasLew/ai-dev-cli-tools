from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from ai_dev_tools.models.report import Report

_COLLECTION_KINDS = {
    "artifacts": "artifact",
    "diffs": "diff",
    "executed": "check",
    "issues": "issue",
    "plan": "check",
    "planned_commands": "check",
    "rejected_files": "file",
    "results": "check",
    "selected_checks": "check",
    "selected_files": "file",
    "snippets": "snippet",
    "workspaces": "workspace",
}


def add_progressive_metadata(payload: dict[str, Any]) -> dict[str, Any]:
    references: list[str] = []
    _annotate(payload.get("issues"), "issue", references)
    _annotate(payload.get("artifacts"), "artifact", references)
    summary = payload.get("summary")
    if isinstance(summary, dict):
        _walk_summary(summary, references)
    metadata = payload.setdefault("metadata", {})
    if isinstance(metadata, dict):
        metadata["progressive"] = {
            "expandable_evidence": len(references),
            "references": references,
            "command_template": "ai-dev explain <evidence-id> --tail 100",
        }
    return payload


def run_explain(project_root: Path, reference: str, tail: int = 100) -> Report:
    root = project_root.resolve()
    report = Report(command=f"explain {reference}", project_root=root)
    match, source = _find_reference(root, reference)
    if match is None:
        report.status = "failed"
        report.exit_code = 1
        report.summary = {
            "message": f"Evidence reference was not found: {reference}",
            "reason_code": "EVIDENCE_NOT_FOUND",
            "searched": [".ai/reports", ".ai/context"],
        }
        return report
    report.summary = {
        "evidence_id": reference,
        "source_report": str(source),
        "evidence": _bounded_evidence(root, match, max(tail, 0)),
    }
    return report


def _walk_summary(value: object, references: list[str], key: str = "") -> None:
    if isinstance(value, dict):
        for child_key, child in value.items():
            if child_key == "progressive":
                continue
            if isinstance(child, list) and child_key in _COLLECTION_KINDS:
                _annotate(child, _COLLECTION_KINDS[child_key], references)
            else:
                _walk_summary(child, references, child_key)
    elif isinstance(value, list):
        for child in value:
            _walk_summary(child, references, key)


def _annotate(value: object, kind: str, references: list[str]) -> None:
    if not isinstance(value, list):
        return
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            continue
        evidence_id = str(item.get("evidence_id") or _evidence_id(kind, item, index))
        item["evidence_id"] = evidence_id
        references.append(evidence_id)
        for child_key, child in item.items():
            if isinstance(child, list) and child_key in _COLLECTION_KINDS:
                _annotate(child, _COLLECTION_KINDS[child_key], references)


def _evidence_id(kind: str, item: dict[str, object], index: int) -> str:
    identity_keys = (
        "path",
        "file",
        "name",
        "signature",
        "failure_signature",
        "code",
        "command",
        "workspace",
        "start_line",
    )
    identity = {key: item[key] for key in identity_keys if item.get(key) not in (None, "", [])}
    if not identity:
        identity = {"index": index, "value": item}
    encoded = json.dumps(identity, sort_keys=True, default=str, separators=(",", ":"))
    digest = hashlib.sha256(f"{kind}:{encoded}".encode()).hexdigest()[:12]
    return f"{kind}:{digest}"


def _find_reference(root: Path, reference: str) -> tuple[dict[str, object] | None, Path | None]:
    candidates = [
        *sorted((root / ".ai" / "reports").glob("*latest.json")),
        *sorted((root / ".ai" / "context").glob("*latest.json")),
    ]
    for path in reversed(candidates):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        match = _find_in_value(payload, reference)
        if match is not None:
            return match, path
    return None, None


def _find_in_value(value: object, reference: str) -> dict[str, object] | None:
    if isinstance(value, dict):
        if value.get("evidence_id") == reference:
            return value
        for child in value.values():
            match = _find_in_value(child, reference)
            if match is not None:
                return match
    elif isinstance(value, list):
        for child in value:
            match = _find_in_value(child, reference)
            if match is not None:
                return match
    return None


def _bounded_evidence(root: Path, evidence: dict[str, object], tail: int) -> dict[str, object]:
    result = dict(evidence)
    artifact_path = evidence.get("path")
    if evidence.get("kind") and isinstance(artifact_path, str):
        path = Path(artifact_path)
        path = path if path.is_absolute() else root / path
        try:
            path.resolve().relative_to(root)
        except ValueError:
            return result
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return result
        result["expanded_content"] = lines[-tail:] if tail else []
        result["expanded_line_count"] = min(len(lines), tail)
        result["total_line_count"] = len(lines)
    return result
