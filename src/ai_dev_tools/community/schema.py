from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from typing import Any, TypedDict

COMMUNITY_SCHEMA_VERSION = 1
MAX_PAYLOAD_BYTES = 32_768  # 32 KB

OS_FAMILIES = {"windows", "linux", "macos", "other"}

COMMAND_NAMES = {
    "doctor",
    "scan",
    "bootstrap",
    "environment",
    "run",
    "stop",
    "map",
    "check",
    "cache",
    "index",
    "semantic",
    "policy",
    "sarif",
    "test",
    "logs",
    "context",
    "git",
    "completion",
    "watch",
    "feedback",
    "session",
    "agents",
    "baseline",
    "benchmark",
    "performance",
    "explain",
    "mcp",
    "integrations",
    "dashboard",
    "telemetry",
    "diagnostics",
    "capabilities",
    "plan",
    "task",
    "finish",
    "other",
}

COMMAND_CATEGORIES = {
    "analysis",
    "execution",
    "quality",
    "context",
    "benchmark",
    "telemetry",
    "agent",
    "runtime",
    "other",
}

COMMAND_OUTCOMES = {"success", "partial", "failure"}

AI_CLIENTS = {"codex", "claude", "cursor", "gemini", "other", "unknown"}

TASK_KINDS = {
    "bugfix",
    "feature",
    "refactor",
    "test",
    "documentation",
    "performance",
    "security",
    "investigation",
    "other",
    "unknown",
}

VALIDATION_OUTCOMES = {"passed", "failed", "unknown"}
TASK_OUTCOMES = {"success", "failure", "unknown"}

KNOWN_REASON_CODES = {
    "NONE",
    "INVALID_ARGUMENTS",
    "INVALID_CONFIGURATION",
    "TIMEOUT",
    "EXECUTION_FAILED",
    "NOT_A_GIT_REPOSITORY",
    "INVALID_TELEMETRY",
    "TELEMETRY_ALERT",
    "TOKEN_BUDGET_EXCEEDED",
    "CONTEXT_BUDGET_TRUNCATED",
    "CONTEXT_MANIFEST_NOT_FOUND",
    "INVALID_CONTEXT_ID",
    "POLICY_VIOLATION",
    "UNKNOWN",
}

KNOWN_PUBLIC_MODELS = {
    "gpt-4o",
    "gpt-4o-mini",
    "o1",
    "o1-mini",
    "o1-preview",
    "o3",
    "o3-mini",
    "claude-3-5-sonnet",
    "claude-3-5-haiku",
    "claude-3-7-sonnet",
    "claude-3-opus",
    "claude-3-sonnet",
    "claude-3-haiku",
    "gemini-1.5-pro",
    "gemini-1.5-flash",
    "gemini-2.0-flash",
    "gemini-2.0-pro",
    "gemini-2.5-pro",
    "gemini-2.5-flash",
}

KNOWN_LANGUAGES = {
    "python",
    "typescript",
    "javascript",
    "rust",
    "go",
    "c",
    "cpp",
    "csharp",
    "java",
    "kotlin",
    "ruby",
    "php",
    "swift",
    "shell",
    "html",
    "css",
    "sql",
    "markdown",
    "yaml",
    "toml",
    "json",
}

RETRIEVAL_REASONS = {
    "always_requested",
    "never_requested",
    "explicit_includes",
    "high_confidence_task",
    "low_confidence_fallback",
    "heuristic_fallback",
    "unknown",
}


def sanitize_model_name(raw_model: str | None) -> str:
    if not raw_model:
        return "unknown"
    normalized = raw_model.strip().lower()
    for prefix in ("openai/", "anthropic/", "google/", "gemini/"):
        if normalized.startswith(prefix):
            normalized = normalized[len(prefix) :]
    if normalized in KNOWN_PUBLIC_MODELS:
        return normalized
    for known in KNOWN_PUBLIC_MODELS:
        if known in normalized:
            return known
    if any(local_kw in normalized for local_kw in ("local", "ollama", "vllm", "llama", "mistral")):
        return "local"
    return "other"


def sanitize_task_kind(raw_task: str | None) -> str:
    if not raw_task:
        return "unknown"
    normalized = raw_task.strip().lower()
    return normalized if normalized in TASK_KINDS else "unknown"


def sanitize_reason_code(raw_code: str | None) -> str | None:
    if not raw_code:
        return None
    normalized = raw_code.strip().upper()
    return normalized if normalized in KNOWN_REASON_CODES else "UNKNOWN"


def duration_bucket(seconds: float | None) -> str:
    if seconds is None or seconds < 0:
        return "unknown"
    if seconds < 0.1:
        return "<100ms"
    if seconds < 0.5:
        return "100ms-500ms"
    if seconds < 1.0:
        return "500ms-1s"
    if seconds < 5.0:
        return "1s-5s"
    if seconds < 30.0:
        return "5s-30s"
    if seconds < 120.0:
        return "30s-120s"
    return "120s+"


def repo_files_bucket(count: int | None) -> str:
    if count is None or count < 0:
        return "unknown"
    if count <= 50:
        return "1-50"
    if count <= 200:
        return "51-200"
    if count <= 1000:
        return "201-1000"
    if count <= 5000:
        return "1001-5000"
    return "5000+"


def repo_size_bucket(size_bytes: int | None) -> str:
    if size_bytes is None or size_bytes < 0:
        return "unknown"
    mb = size_bytes / (1024 * 1024)
    if mb < 1.0:
        return "<1MB"
    if mb <= 10.0:
        return "1-10MB"
    if mb <= 50.0:
        return "10-50MB"
    if mb <= 250.0:
        return "50-250MB"
    return "250MB+"


def get_os_family() -> str:
    platform = sys.platform
    if platform == "win32":
        return "windows"
    if platform == "darwin":
        return "macos"
    if platform.startswith("linux"):
        return "linux"
    return "other"


def get_python_version() -> str:
    return f"{sys.version_info.major}.{sys.version_info.minor}"


def get_utc_hour_timestamp(dt: datetime | None = None) -> str:
    target = dt if dt is not None else datetime.now(UTC)
    truncated = target.replace(minute=0, second=0, microsecond=0)
    return truncated.strftime("%Y-%m-%dT%H:00:00Z")


BASIC_PAYLOAD_KEYS = {
    "schema_version",
    "event_id",
    "event_type",
    "telemetry_level",
    "ai_dev_version",
    "os_family",
    "python_version",
    "command_name",
    "command_category",
    "command_outcome",
    "reason_code",
    "duration_bucket",
    "duration_seconds",
    "cache_hit",
    "timestamp_hour",
}

RESEARCH_ADDITIONAL_KEYS = {
    "ai_client",
    "model",
    "task_kind",
    "language_families",
    "repo_files_bucket",
    "repo_size_bucket",
    "context_candidate_tokens",
    "context_delivered_tokens",
    "context_budget",
    "input_tokens",
    "cached_input_tokens",
    "output_tokens",
    "reasoning_tokens",
    "total_tokens",
    "tool_call_count",
    "files_considered",
    "files_selected",
    "files_omitted",
    "cache_hit_ratio",
    "semantic_cache_reuse",
    "local_overhead_seconds",
    "total_wall_time_seconds",
    "validation_result",
    "task_outcome",
    "retrieval_reason_code",
    "selection_reason_codes",
}

RESEARCH_PAYLOAD_KEYS = BASIC_PAYLOAD_KEYS | RESEARCH_ADDITIONAL_KEYS


class BasicCommunityPayload(TypedDict, total=True):
    schema_version: int
    event_id: str
    event_type: str
    telemetry_level: str
    ai_dev_version: str
    os_family: str
    python_version: str
    command_name: str
    command_category: str
    command_outcome: str
    reason_code: str | None
    duration_bucket: str
    duration_seconds: float | None
    cache_hit: bool | None
    timestamp_hour: str


class ResearchCommunityPayload(BasicCommunityPayload, total=False):
    ai_client: str
    model: str
    task_kind: str
    language_families: list[str]
    repo_files_bucket: str
    repo_size_bucket: str
    context_candidate_tokens: int | None
    context_delivered_tokens: int | None
    context_budget: int | None
    input_tokens: int | None
    cached_input_tokens: int | None
    output_tokens: int | None
    reasoning_tokens: int | None
    total_tokens: int | None
    tool_call_count: int | None
    files_considered: int | None
    files_selected: int | None
    files_omitted: int | None
    cache_hit_ratio: float | None
    semantic_cache_reuse: float | None
    local_overhead_seconds: float | None
    total_wall_time_seconds: float | None
    validation_result: str
    task_outcome: str
    retrieval_reason_code: str | None
    selection_reason_codes: list[str] | None


def validate_community_payload(payload: dict[str, Any]) -> None:
    if not isinstance(payload, dict):
        raise ValueError("Payload must be a dictionary")

    level = payload.get("telemetry_level")
    if level == "basic":
        allowed_keys = BASIC_PAYLOAD_KEYS
    elif level == "research":
        allowed_keys = RESEARCH_PAYLOAD_KEYS
    else:
        raise ValueError(f"Invalid telemetry_level in payload: '{level}'")

    actual_keys = set(payload.keys())
    unexpected = actual_keys - allowed_keys
    if unexpected:
        raise ValueError(f"Unexpected keys in {level} payload: {sorted(unexpected)}")

    missing = BASIC_PAYLOAD_KEYS - actual_keys
    if missing:
        raise ValueError(f"Missing required basic keys in payload: {sorted(missing)}")

    if level == "research":
        missing_research = RESEARCH_PAYLOAD_KEYS - actual_keys
        if missing_research:
            missing_sorted = sorted(missing_research)
            raise ValueError(f"Missing required research keys in payload: {missing_sorted}")

    if payload["schema_version"] != COMMUNITY_SCHEMA_VERSION:
        raise ValueError(f"Unsupported schema_version: {payload['schema_version']}")

    if payload["os_family"] not in OS_FAMILIES:
        raise ValueError(f"Invalid os_family: {payload['os_family']}")

    if payload["command_outcome"] not in COMMAND_OUTCOMES:
        raise ValueError(f"Invalid command_outcome: {payload['command_outcome']}")

    if level == "research":
        if payload["ai_client"] not in AI_CLIENTS:
            raise ValueError(f"Invalid ai_client: {payload['ai_client']}")
        if payload["task_kind"] not in TASK_KINDS:
            raise ValueError(f"Invalid task_kind: {payload['task_kind']}")
        if payload["validation_result"] not in VALIDATION_OUTCOMES:
            raise ValueError(f"Invalid validation_result: {payload['validation_result']}")
        if payload["task_outcome"] not in TASK_OUTCOMES:
            raise ValueError(f"Invalid task_outcome: {payload['task_outcome']}")
        if not isinstance(payload["language_families"], list):
            raise ValueError("language_families must be a list")
        for lang in payload["language_families"]:
            if not isinstance(lang, str) or lang not in KNOWN_LANGUAGES:
                raise ValueError(f"Invalid language family: {lang}")

    serialized = json.dumps(payload, ensure_ascii=False)
    payload_len = len(serialized.encode("utf-8"))
    if payload_len > MAX_PAYLOAD_BYTES:
        raise ValueError(
            f"Payload size ({payload_len} bytes) exceeds limit of {MAX_PAYLOAD_BYTES} bytes"
        )
