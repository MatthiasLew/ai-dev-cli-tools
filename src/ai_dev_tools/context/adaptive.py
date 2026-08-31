from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass, replace

from ai_dev_tools.context.models import (
    DEFAULT_MAX_CHARS,
    DEFAULT_MAX_DIFF_CHARS,
    DEFAULT_MAX_FILE_CHARS,
    DEFAULT_MAX_FILES,
    ContextOptions,
)

_WORDS = re.compile(r"[a-z0-9_./#-]+")
_BROAD = re.compile(
    r"\b(all|entire|full|whole|architecture|migrat(?:e|ion)|refactor|security|audit)\b",
    re.IGNORECASE,
)
_INTENTS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("debug", re.compile(r"\b(debug|fix|bug|error|fail|crash|exception|timeout)\b", re.I)),
    ("review", re.compile(r"\b(review|inspect|diff|pull request|pr|regression)\b", re.I)),
    (
        "docs",
        re.compile(r"\b(doc|docs|document|documentation|readme|changelog|guide|example)\b", re.I),
    ),
    ("maintenance", re.compile(r"\b(clean|rename|format|lint|upgrade|dependency)\b", re.I)),
    ("implement", re.compile(r"\b(add|build|create|implement|feature|extend)\b", re.I)),
)


@dataclass(frozen=True, slots=True)
class AdaptiveBudget:
    max_chars: int
    max_files: int
    max_file_chars: int
    max_diff_chars: int


_BUDGETS: dict[str, AdaptiveBudget] = {
    "debug": AdaptiveBudget(32_000, 18, 7_000, 12_000),
    "review": AdaptiveBudget(28_000, 18, 5_000, 14_000),
    "docs": AdaptiveBudget(24_000, 20, 7_000, 8_000),
    "maintenance": AdaptiveBudget(18_000, 12, 4_000, 6_000),
    "implement": AdaptiveBudget(42_000, 26, 8_000, 12_000),
    "unknown": AdaptiveBudget(30_000, 18, 6_000, 10_000),
}


def adaptive_task_scope(task: str) -> str:
    normalized = " ".join(_WORDS.findall(task.lower()))[:1000]
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]


def apply_adaptive_budget(
    options: ContextOptions,
    original: ContextOptions,
    *,
    changed_files: int,
    candidate_files: int,
    latest_errors: int,
) -> tuple[ContextOptions, dict[str, object]]:
    if not options.adaptive:
        return options, {"enabled": False}

    intent = _intent(options.task, latest_errors)
    base = _BUDGETS[intent]
    scale, scope, reasons = _scale(options.task, changed_files, candidate_files, latest_errors)
    proposed = AdaptiveBudget(
        max_chars=_scaled(base.max_chars, scale, 8_000),
        max_files=_scaled(base.max_files, scale, 6),
        max_file_chars=_scaled(base.max_file_chars, min(scale, 1.15), 2_000),
        max_diff_chars=_scaled(base.max_diff_chars, scale, 3_000),
    )
    explicit = {
        "max_chars": original.max_chars != DEFAULT_MAX_CHARS,
        "max_files": original.max_files != DEFAULT_MAX_FILES,
        "max_file_chars": original.max_file_chars != DEFAULT_MAX_FILE_CHARS,
        "max_diff_chars": original.max_diff_chars != DEFAULT_MAX_DIFF_CHARS,
    }

    def resolve(name: str, current: int, suggested: int) -> int:
        if explicit[name]:
            return current
        return min(current, suggested)

    resolved = replace(
        options,
        max_chars=resolve("max_chars", options.max_chars, proposed.max_chars),
        max_files=resolve("max_files", options.max_files, proposed.max_files),
        max_file_chars=resolve(
            "max_file_chars", options.max_file_chars, proposed.max_file_chars
        ),
        max_diff_chars=resolve("max_diff_chars", options.max_diff_chars, proposed.max_diff_chars),
    )
    decision = {
        "enabled": True,
        "intent": intent,
        "scope": scope,
        "reason_codes": reasons,
        "task_scope": adaptive_task_scope(options.task),
        "signals": {
            "changed_files": changed_files,
            "candidate_files": candidate_files,
            "latest_errors": latest_errors,
        },
        "explicit_overrides": [name for name, value in explicit.items() if value],
        "resolved_budget": {
            "max_chars": resolved.max_chars,
            "max_files": resolved.max_files,
            "max_file_chars": resolved.max_file_chars,
            "max_diff_chars": resolved.max_diff_chars,
            "estimated_token_ceiling": math.ceil(resolved.max_chars / 4),
        },
        "safety": "uncertainty broadens context; explicit limits always win",
    }
    return resolved, decision


def _intent(task: str, latest_errors: int) -> str:
    if latest_errors:
        return "debug"
    for name, pattern in _INTENTS:
        if pattern.search(task):
            return name
    return "unknown"


def _scale(
    task: str, changed_files: int, candidate_files: int, latest_errors: int
) -> tuple[float, str, list[str]]:
    if _BROAD.search(task) or changed_files > 10 or candidate_files > 80:
        return 1.35, "broad", ["BROAD_TASK_OR_REPOSITORY"]
    if latest_errors or 3 <= changed_files <= 10 or candidate_files > 30:
        return 1.0, "bounded", ["MULTI_FILE_OR_FAILURE_CONTEXT"]
    if 0 < changed_files <= 2 or 0 < candidate_files <= 12:
        return 0.7, "focused", ["FOCUSED_TASK_CONTEXT"]
    return 1.15, "uncertain", ["LOW_CONFIDENCE_BROADENED"]


def _scaled(value: int, scale: float, minimum: int) -> int:
    return max(minimum, int(round(value * scale)))
