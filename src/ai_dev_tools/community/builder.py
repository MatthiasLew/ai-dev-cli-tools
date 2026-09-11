from __future__ import annotations

import contextlib
import uuid
from pathlib import Path
from typing import Any

from ai_dev_tools import __version__
from ai_dev_tools.community.schema import (
    AI_CLIENTS,
    COMMAND_CATEGORIES,
    COMMAND_NAMES,
    COMMAND_OUTCOMES,
    COMMUNITY_SCHEMA_VERSION,
    KNOWN_LANGUAGES,
    RETRIEVAL_REASONS,
    duration_bucket,
    get_os_family,
    get_python_version,
    get_utc_hour_timestamp,
    repo_files_bucket,
    repo_size_bucket,
    sanitize_model_name,
    sanitize_reason_code,
    sanitize_task_kind,
    validate_community_payload,
)
from ai_dev_tools.models.report import Report

EXTENSION_LANGUAGE_MAP: dict[str, str] = {
    ".py": "python",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".rs": "rust",
    ".go": "go",
    ".c": "c",
    ".h": "c",
    ".cpp": "cpp",
    ".hpp": "cpp",
    ".cc": "cpp",
    ".cs": "csharp",
    ".java": "java",
    ".kt": "kotlin",
    ".rb": "ruby",
    ".php": "php",
    ".swift": "swift",
    ".sh": "shell",
    ".bash": "shell",
    ".html": "html",
    ".css": "css",
    ".sql": "sql",
    ".md": "markdown",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".toml": "toml",
    ".json": "json",
}

COMMAND_CATEGORY_MAP: dict[str, str] = {
    "doctor": "analysis",
    "scan": "analysis",
    "map": "analysis",
    "explain": "analysis",
    "diagnostics": "analysis",
    "capabilities": "analysis",
    "check": "quality",
    "test": "quality",
    "policy": "quality",
    "sarif": "quality",
    "logs": "quality",
    "run": "runtime",
    "stop": "runtime",
    "bootstrap": "runtime",
    "environment": "runtime",
    "watch": "runtime",
    "context": "context",
    "cache": "execution",
    "index": "execution",
    "semantic": "execution",
    "baseline": "benchmark",
    "benchmark": "benchmark",
    "performance": "benchmark",
    "telemetry": "telemetry",
    "agents": "agent",
    "session": "agent",
    "feedback": "agent",
    "plan": "agent",
    "task": "agent",
    "finish": "agent",
}


def detect_language_families(project_root: Path | None) -> list[str]:
    if project_root is None or not project_root.is_dir():
        return []
    languages: set[str] = set()
    ignored_dirs = {
        ".git",
        ".venv",
        "venv",
        "node_modules",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        "__pycache__",
        "dist",
        "build",
        ".ai",
    }
    try:
        count = 0
        for entry in project_root.rglob("*"):
            if count > 500:  # Sample at most 500 files to remain fast
                break
            if any(part in ignored_dirs for part in entry.parts):
                continue
            if entry.is_file():
                count += 1
                suffix = entry.suffix.lower()
                lang = EXTENSION_LANGUAGE_MAP.get(suffix)
                if lang and lang in KNOWN_LANGUAGES:
                    languages.add(lang)
    except OSError:
        pass
    return sorted(languages)


def compute_repo_buckets(project_root: Path | None) -> tuple[str, str]:
    if project_root is None or not project_root.is_dir():
        return "unknown", "unknown"
    ignored_dirs = {
        ".git",
        ".venv",
        "venv",
        "node_modules",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        "__pycache__",
        "dist",
        "build",
        ".ai",
    }
    total_files = 0
    total_bytes = 0
    try:
        for entry in project_root.rglob("*"):
            if any(part in ignored_dirs for part in entry.parts):
                continue
            if entry.is_file():
                total_files += 1
                with contextlib.suppress(OSError):
                    total_bytes += entry.stat().st_size
    except OSError:
        return "unknown", "unknown"
    return repo_files_bucket(total_files), repo_size_bucket(total_bytes)


def build_community_payload(
    level: str,
    report: Report | None = None,
    *,
    command_name: str | None = None,
    duration_seconds: float | None = None,
    project_root: Path | None = None,
    sample: bool = False,
) -> dict[str, Any]:
    normalized_level = level.strip().lower()
    if normalized_level not in {"basic", "research"}:
        raise ValueError(f"Unsupported telemetry level for payload: '{level}'")

    event_id = str(uuid.uuid4())
    event_type = "command_run"
    ai_dev_version = __version__
    os_family = get_os_family()
    python_ver = get_python_version()
    timestamp_hour = get_utc_hour_timestamp()

    # Determine command name and category
    cmd = command_name or (report.command if report else "")
    first_cmd = cmd.split()[0] if cmd else "preview"
    safe_cmd_name = first_cmd if first_cmd in COMMAND_NAMES else "other"
    cmd_category = COMMAND_CATEGORY_MAP.get(safe_cmd_name, "other")
    if cmd_category not in COMMAND_CATEGORIES:
        cmd_category = "other"

    # Outcome and reason code
    outcome = "success"
    reason_code: str | None = None
    if report is not None:
        status = report.status.lower()
        outcome = status if status in COMMAND_OUTCOMES else "partial"
        if isinstance(report.summary, dict):
            raw_reason = report.summary.get("reason_code")
            if isinstance(raw_reason, str):
                reason_code = sanitize_reason_code(raw_reason)
        if reason_code is None and report.issues:
            first_code = report.issues[0].code
            if first_code:
                reason_code = sanitize_reason_code(first_code)
    elif sample:
        outcome = "success"
        reason_code = "NONE"

    # Duration
    dur: float | None = None
    if duration_seconds is not None:
        dur = round(max(0.0, min(duration_seconds, 604800.0)), 3)
    elif report is not None and report.duration_seconds is not None:
        dur = round(max(0.0, min(report.duration_seconds, 604800.0)), 3)
    elif sample:
        dur = 0.350

    dur_bucket = duration_bucket(dur)

    # Cache hit
    cache_hit: bool | None = None
    if report is not None and isinstance(report.summary, dict):
        cache_data = report.summary.get("cache")
        if isinstance(cache_data, dict) and "hit" in cache_data:
            cache_hit = bool(cache_data["hit"])
        elif "cache_hit" in report.summary:
            cache_hit = bool(report.summary["cache_hit"])
    elif sample:
        cache_hit = True

    basic_payload: dict[str, Any] = {
        "schema_version": COMMUNITY_SCHEMA_VERSION,
        "event_id": event_id,
        "event_type": event_type,
        "telemetry_level": "basic" if normalized_level == "basic" else "research",
        "ai_dev_version": ai_dev_version,
        "os_family": os_family,
        "python_version": python_ver,
        "command_name": safe_cmd_name,
        "command_category": cmd_category,
        "command_outcome": outcome,
        "reason_code": reason_code,
        "duration_bucket": dur_bucket,
        "duration_seconds": dur,
        "cache_hit": cache_hit,
        "timestamp_hour": timestamp_hour,
    }

    if normalized_level == "basic":
        validate_community_payload(basic_payload)
        return basic_payload

    # RESEARCH LEVEL
    ai_client = "unknown"
    model = "unknown"
    task_kind = "unknown"
    context_candidate_tokens: int | None = None
    context_delivered_tokens: int | None = None
    context_budget: int | None = None
    input_tokens: int | None = None
    cached_input_tokens: int | None = None
    output_tokens: int | None = None
    reasoning_tokens: int | None = None
    total_tokens: int | None = None
    tool_call_count: int | None = None
    files_considered: int | None = None
    files_selected: int | None = None
    files_omitted: int | None = None
    cache_hit_ratio: float | None = None
    semantic_cache_reuse: float | None = None
    local_overhead_seconds: float | None = None
    total_wall_time_seconds: float | None = dur
    validation_result = "unknown"
    task_outcome = "unknown"
    retrieval_reason_code: str | None = None
    selection_reason_codes: list[str] | None = None

    summary = report.summary if report and isinstance(report.summary, dict) else {}

    # Check client from summary or sample
    raw_client = str(summary.get("client", "")).strip().lower()
    if raw_client in AI_CLIENTS:
        ai_client = raw_client
    elif sample:
        ai_client = "cursor"

    # Model
    raw_model = summary.get("model")
    if isinstance(raw_model, str):
        model = sanitize_model_name(raw_model)
    elif sample:
        model = "claude-3-5-sonnet"

    # Task kind
    raw_task_kind = summary.get("task_kind")
    if isinstance(raw_task_kind, str):
        task_kind = sanitize_task_kind(raw_task_kind)
    elif sample:
        task_kind = "feature"

    # Context & token efficiency metrics
    token_accounting = summary.get("token_accounting")
    if isinstance(token_accounting, dict):
        cat = token_accounting.get("categories", {})
        if isinstance(cat, dict):
            context_candidate_tokens = sum(
                item.get("tokens", 0) for item in cat.values() if isinstance(item, dict)
            ) or None
    receipt = summary.get("receipt")
    if isinstance(receipt, dict):
        cand = receipt.get("original_context_chars")
        deliv = receipt.get("delivered_context_chars")
        if isinstance(cand, int):
            context_candidate_tokens = context_candidate_tokens or (cand // 4)
        if isinstance(deliv, int):
            context_delivered_tokens = deliv // 4
    character_budget = summary.get("character_budget")
    if isinstance(character_budget, dict):
        budget_chars = summary.get("budget", {}).get("max_chars")
        if isinstance(budget_chars, int):
            context_budget = budget_chars // 4

    # File counts
    selected_files = summary.get("selected_files")
    if isinstance(selected_files, list):
        files_selected = len(selected_files)
    rejected_files = summary.get("rejected_files")
    if isinstance(rejected_files, list):
        files_omitted = len(rejected_files)
    if files_selected is not None or files_omitted is not None:
        files_considered = (files_selected or 0) + (files_omitted or 0)

    # Retrieval reason
    retrieval = summary.get("retrieval")
    if isinstance(retrieval, dict):
        r_code = str(retrieval.get("reason_code", "")).strip().lower()
        if r_code in RETRIEVAL_REASONS:
            retrieval_reason_code = r_code

    # Selection reason codes
    if isinstance(selected_files, list):
        reasons_found: set[str] = set()
        for sf in selected_files:
            if isinstance(sf, dict):
                code = sf.get("reason_code")
                if isinstance(code, str) and code:
                    reasons_found.add(code[:30])
        if reasons_found:
            selection_reason_codes = sorted(reasons_found)

    # Token counts from telemetry sessions or report
    for key, var in (
        ("input_tokens", "input_tokens"),
        ("cached_input_tokens", "cached_input_tokens"),
        ("output_tokens", "output_tokens"),
        ("reasoning_tokens", "reasoning_tokens"),
        ("total_tokens", "total_tokens"),
    ):
        val = summary.get(key)
        if isinstance(val, int) and not isinstance(val, bool) and val >= 0:
            if var == "input_tokens":
                input_tokens = val
            elif var == "cached_input_tokens":
                cached_input_tokens = val
            elif var == "output_tokens":
                output_tokens = val
            elif var == "reasoning_tokens":
                reasoning_tokens = val
            elif var == "total_tokens":
                total_tokens = val

    # Local overhead
    perf = summary.get("performance")
    if isinstance(perf, dict):
        stages = perf.get("stages_seconds")
        if isinstance(stages, dict):
            overhead = sum(
                float(v)
                for v in stages.values()
                if isinstance(v, (int, float)) and not isinstance(v, bool)
            )
            local_overhead_seconds = round(overhead, 3)

    # Validation and task outcome
    if safe_cmd_name in {"check", "test"}:
        validation_result = "passed" if outcome == "success" else "failed"
    if summary.get("task_complete") is True:
        task_outcome = "success"
    elif summary.get("task_failed") is True:
        task_outcome = "failure"

    # Sample fallbacks
    if sample:
        context_candidate_tokens = 4500
        context_delivered_tokens = 1200
        context_budget = 2000
        input_tokens = 1500
        cached_input_tokens = 800
        output_tokens = 250
        reasoning_tokens = 50
        total_tokens = 1750
        tool_call_count = 3
        files_considered = 15
        files_selected = 4
        files_omitted = 11
        cache_hit_ratio = 0.75
        semantic_cache_reuse = 0.50
        local_overhead_seconds = 0.045
        validation_result = "passed"
        task_outcome = "unknown"
        retrieval_reason_code = "high_confidence_task"
        selection_reason_codes = ["IMPORT_DEPENDENCY", "TASK_KEYWORD_MATCH"]

    # Language families and repository buckets
    lang_families = detect_language_families(project_root)
    r_files_bucket, r_size_bucket = compute_repo_buckets(project_root)
    if sample:
        if not lang_families:
            lang_families = ["python", "markdown"]
        if r_files_bucket == "unknown":
            r_files_bucket = "51-200"
        if r_size_bucket == "unknown":
            r_size_bucket = "1-10MB"

    research_payload: dict[str, Any] = {
        **basic_payload,
        "telemetry_level": "research",
        "ai_client": ai_client,
        "model": model,
        "task_kind": task_kind,
        "language_families": lang_families,
        "repo_files_bucket": r_files_bucket,
        "repo_size_bucket": r_size_bucket,
        "context_candidate_tokens": context_candidate_tokens,
        "context_delivered_tokens": context_delivered_tokens,
        "context_budget": context_budget,
        "input_tokens": input_tokens,
        "cached_input_tokens": cached_input_tokens,
        "output_tokens": output_tokens,
        "reasoning_tokens": reasoning_tokens,
        "total_tokens": total_tokens,
        "tool_call_count": tool_call_count,
        "files_considered": files_considered,
        "files_selected": files_selected,
        "files_omitted": files_omitted,
        "cache_hit_ratio": cache_hit_ratio,
        "semantic_cache_reuse": semantic_cache_reuse,
        "local_overhead_seconds": local_overhead_seconds,
        "total_wall_time_seconds": total_wall_time_seconds,
        "validation_result": validation_result,
        "task_outcome": task_outcome,
        "retrieval_reason_code": retrieval_reason_code,
        "selection_reason_codes": selection_reason_codes,
    }

    validate_community_payload(research_payload)
    return research_payload
