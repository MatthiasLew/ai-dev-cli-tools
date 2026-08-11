from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

_PROSE_SUFFIXES = {".md", ".markdown", ".rst", ".txt", ".adoc"}
_LOG_SUFFIXES = {".log"}
_PROTECTED_SUFFIXES = {
    ".py",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".java",
    ".rs",
    ".php",
    ".json",
    ".jsonl",
    ".toml",
    ".yaml",
    ".yml",
    ".xml",
    ".ini",
    ".cfg",
    ".sh",
    ".ps1",
    ".bat",
    ".cmd",
    ".diff",
    ".patch",
    ".sql",
}


def apply_safe_compression(summary: dict[str, Any], mode: str) -> dict[str, Any]:
    if mode not in {"off", "conservative"}:
        raise ValueError(f"unknown compression mode: {mode}")
    protected_before = _protected_fingerprint(summary)
    considered = 0
    compressed: list[dict[str, object]] = []
    skipped: list[dict[str, str]] = []
    if mode == "conservative":
        selected = summary.get("selected_files")
        if isinstance(selected, list):
            for item in selected:
                if not isinstance(item, dict):
                    continue
                path = str(item.get("path", ""))
                suffix = Path(path).suffix.lower()
                content = item.get("content")
                if not isinstance(content, str):
                    continue
                if suffix in _PROTECTED_SUFFIXES or suffix not in _PROSE_SUFFIXES | _LOG_SUFFIXES:
                    skipped.append({"path": path, "reason_code": "EXACT_CONTENT_PROTECTED"})
                    continue
                considered += 1
                compact = (
                    _compress_log(content) if suffix in _LOG_SUFFIXES else _compress_prose(content)
                )
                if len(compact) >= len(content):
                    skipped.append({"path": path, "reason_code": "NO_SAFE_REPETITION"})
                    continue
                item["content"] = compact
                item["chars"] = len(compact)
                item["semantic_compressed"] = True
                item["compression_method"] = (
                    "consecutive-natural-line-dedup"
                    if suffix in _LOG_SUFFIXES
                    else "exact-paragraph-dedup"
                )
                item["original_sha256"] = hashlib.sha256(content.encode("utf-8")).hexdigest()
                item["original_chars"] = len(content)
                compressed.append(
                    {
                        "path": path,
                        "original_chars": len(content),
                        "final_chars": len(compact),
                        "chars_saved": len(content) - len(compact),
                        "reason_code": "SAFE_NATURAL_LANGUAGE_DEDUP",
                    }
                )
    protected_after = _protected_fingerprint(summary)
    if protected_before != protected_after:
        raise RuntimeError("compression modified protected evidence")
    return {
        "mode": mode,
        "enabled": mode != "off",
        "considered_files": considered,
        "compressed_files": compressed,
        "compressed_count": len(compressed),
        "chars_saved": _saved_chars(compressed),
        "skipped_files": skipped[:100],
        "protected_fingerprint": protected_after,
        "protected_integrity": True,
        "preserved_categories": [
            "code",
            "json",
            "diffs",
            "commands",
            "locations",
            "hashes",
            "verification_evidence",
        ],
    }


def _saved_chars(items: list[dict[str, object]]) -> int:
    return sum(value for item in items if isinstance((value := item.get("chars_saved")), int))


def _compress_prose(text: str) -> str:
    parts = re.split(r"(```[\s\S]*?```|~~~[\s\S]*?~~~)", text)
    seen: set[str] = set()
    result: list[str] = []
    for index, part in enumerate(parts):
        if index % 2 == 1:
            result.append(part)
            continue
        paragraphs = re.split(r"(\n\s*\n)", part)
        for paragraph in paragraphs:
            key = " ".join(paragraph.split())
            if not key or re.fullmatch(r"\n\s*\n", paragraph):
                result.append(paragraph)
            elif key in seen:
                continue
            else:
                seen.add(key)
                result.append(paragraph)
    return "".join(result)


def _compress_log(text: str) -> str:
    lines = text.splitlines(keepends=True)
    result: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        count = 1
        while index + count < len(lines) and lines[index + count] == line:
            count += 1
        clean = line.rstrip("\r\n")
        if count > 1 and _safe_natural_line(clean):
            ending = "\r\n" if line.endswith("\r\n") else "\n" if line.endswith("\n") else ""
            result.append(f"{clean} [repeated {count} times]{ending}")
        else:
            result.extend(lines[index : index + count])
        index += count
    return "".join(result)


def _safe_natural_line(line: str) -> bool:
    if len(line.split()) < 3:
        return False
    if re.search(r"(?:[\\/][\w.-]+)+:\d+|\b[0-9a-f]{7,64}\b", line, re.IGNORECASE):
        return False
    if line.lstrip().startswith(("{", "[", "$ ", "> ", "Traceback", "at ", 'File "')):
        return False
    return not any(token in line for token in ("::", "=>", "==", "!=", "();", "{}"))


def _protected_fingerprint(summary: dict[str, Any]) -> str:
    selected = summary.get("selected_files", [])
    protected_files = (
        [
            {"path": item.get("path"), "content": item.get("content")}
            for item in selected
            if isinstance(item, dict)
            and Path(str(item.get("path", ""))).suffix.lower() in _PROTECTED_SUFFIXES
        ]
        if isinstance(selected, list)
        else []
    )
    protected = {
        "files": protected_files,
        "diffs": summary.get("diffs", []),
        "validation_plan": summary.get("validation_plan", []),
        "latest_errors": summary.get("latest_errors", []),
        "changed_symbols": summary.get("changed_symbols", []),
        "recent_commits": summary.get("recent_commits", []),
    }
    encoded = json.dumps(protected, sort_keys=True, default=str, ensure_ascii=False)
    return "sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()
