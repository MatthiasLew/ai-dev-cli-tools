from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from ai_dev_tools.cache.graph import related_tests
from ai_dev_tools.cache.repository import update_repository_index
from ai_dev_tools.models.report import Report
from ai_dev_tools.security.secrets import mask_text
from ai_dev_tools.source_symbols import extract_source_symbols

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
            "searched": [".ai/reports", ".ai/context", ".ai/cache/evidence"],
        }
        return report
    report.summary = {
        "evidence_id": reference,
        "source_report": str(source),
        "evidence": _bounded_evidence(root, match, max(tail, 0)),
    }
    return report


def run_explain_symbol(project_root: Path, reference: str, tail: int = 100) -> Report:
    root = project_root.resolve()
    report = Report(command=f"explain --symbol {reference}", project_root=root)
    relative, separator, symbol_name = reference.replace("\\", "/").partition("#")
    if not separator or not relative or not symbol_name:
        report.status = "invalid_configuration"
        report.summary = {
            "reason_code": "INVALID_SYMBOL_REFERENCE",
            "expected": "project/relative/path.ext#qualified.symbol",
        }
        return report.finish()
    path = (root / relative).resolve()
    try:
        path.relative_to(root)
    except ValueError:
        report.status = "failed"
        report.summary = {"reason_code": "SYMBOL_PATH_OUTSIDE_PROJECT", "path": relative}
        return report.finish()
    try:
        if not path.is_file() or path.stat().st_size > 2_000_000:
            raise OSError
        source = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        report.status = "failed"
        report.summary = {"reason_code": "SYMBOL_FILE_UNAVAILABLE", "path": relative}
        return report.finish()
    symbols = extract_source_symbols(source, path.suffix)
    if symbols is None:
        report.status = "failed"
        report.summary = {"reason_code": "SYMBOL_PARSE_UNAVAILABLE", "path": relative}
        return report.finish()
    match = next((item for item in symbols if item.name == symbol_name), None)
    if match is None:
        report.status = "failed"
        report.summary = {
            "reason_code": "SYMBOL_NOT_FOUND",
            "path": relative,
            "symbol": symbol_name,
            "available_symbols": [item.name for item in symbols[:100]],
        }
        return report.finish()
    lines = source.splitlines()
    selected = lines[match.start_line - 1 : match.end_line]
    limit = max(tail, 0)
    truncated = limit < len(selected)
    if truncated:
        selected = selected[:limit]
    index = update_repository_index(root)
    tests = related_tests(index.get("graph"), [relative])
    report.summary = {
        "reason_code": "SYMBOL_EXPANDED",
        "path": relative,
        "symbol": match.name,
        "kind": match.kind,
        "start_line": match.start_line,
        "end_line": match.end_line,
        "content": mask_text("\n".join(selected)),
        "expanded_line_count": len(selected),
        "total_line_count": match.end_line - match.start_line + 1,
        "truncated": truncated,
        "related_tests": tests,
    }
    return report.finish()


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
        *sorted((root / ".ai" / "cache" / "evidence").glob("observation-*.json")),
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
    if (
        evidence.get("budget_reason_code") == "GLOBAL_CONTEXT_BUDGET"
        and isinstance(artifact_path, str)
    ):
        path = (root / artifact_path).resolve()
        try:
            path.relative_to(root)
            if not path.is_file() or path.stat().st_size > 2_000_000:
                return result
            content = mask_text(path.read_text(encoding="utf-8", errors="replace"))
        except (OSError, ValueError):
            return result
        lines = content.splitlines()
        expected = evidence.get("omitted_content_sha256")
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        result["expanded_content"] = lines[:tail] if tail else []
        result["expanded_line_count"] = min(len(lines), tail)
        result["total_line_count"] = len(lines)
        result["evidence_state"] = "unchanged" if expected == digest else "recomputed"
        return result
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
