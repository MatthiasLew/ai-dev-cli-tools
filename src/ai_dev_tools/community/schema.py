from __future__ import annotations

import json
import math
import re
import sys
import uuid
from datetime import UTC, datetime
from typing import Any, TypedDict

COMMUNITY_SCHEMA_VERSION = 1
MAX_PAYLOAD_BYTES = 32_768  # 32 KB

TIMESTAMP_HOUR_REGEX = re.compile(
    r"^\d{4}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01])T(?:[01]\d|2[0-3]):00:00Z$"
)
PYTHON_VERSION_REGEX = re.compile(r"^3\.\d+$")
AI_DEV_VERSION_REGEX = re.compile(r"^[\w\.\-\+]+$")

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

ALLOWED_MODELS = KNOWN_PUBLIC_MODELS | {"local", "other", "unknown"}
PROVIDER_USAGE_ORIGINS = frozenset({"mcp", "import", "unknown"})

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

EVENT_TYPES = {"command_run", "provider_usage"}

SELECTION_REASON_CODES = {
    "USER_INCLUDE",
    "CHANGED_FILE",
    "RELATED_TEST",
    "DETECTED_ENTRYPOINT",
    "ENTRYPOINT",
    "IMPORTANT_FILE",
    "TEST_FILE",
    "CI_WORKFLOW",
    "DOCUMENTATION",
    "HIERARCHICAL_REFINEMENT",
    "PYTHON_DEPENDENCY",
    "JS_TS_DEPENDENCY",
    "RUST_DEPENDENCY",
    "JAVA_DEPENDENCY",
    "PHP_DEPENDENCY",
    "DEPENDENCY",
    "SELECTED_FILE",
    "TASK_SYMBOL_MATCH",
    "PUBLIC_SYMBOL",
    "UNKNOWN",
}

DURATION_BUCKETS = {
    "<100ms",
    "100ms-500ms",
    "500ms-1s",
    "1s-5s",
    "5s-30s",
    "30s-120s",
    "120s+",
    "unknown",
}

REPO_FILES_BUCKETS = {
    "1-50",
    "51-200",
    "201-1000",
    "1001-5000",
    "5000+",
    "unknown",
}

REPO_SIZE_BUCKETS = {
    "<1MB",
    "1-10MB",
    "10-50MB",
    "50-250MB",
    "250MB+",
    "unknown",
}


def sanitize_selection_reason_code(raw_code: str | None) -> str:
    if not raw_code:
        return "UNKNOWN"
    normalized = raw_code.strip().upper()
    return normalized if normalized in SELECTION_REASON_CODES else "UNKNOWN"


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
    "origin",
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
    origin: str | None


def _is_valid_uuid4(val: Any) -> bool:
    if not isinstance(val, str) or len(val) != 36:
        return False
    try:
        parsed = uuid.UUID(val, version=4)
        return str(parsed).lower() == val.lower()
    except (ValueError, AttributeError):
        return False


def _validate_non_negative_int(val: Any, field_name: str, max_val: int) -> None:
    if val is None:
        return
    if isinstance(val, bool) or not isinstance(val, int):
        raise ValueError(f"{field_name} must be an integer or None (got {type(val).__name__})")
    if val < 0 or val > max_val:
        raise ValueError(f"{field_name} must be between 0 and {max_val} (got {val})")


def _validate_ratio(val: Any, field_name: str) -> None:
    if val is None:
        return
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise ValueError(f"{field_name} must be a number or None")
    f_val = float(val)
    if not math.isfinite(f_val) or f_val < 0.0 or f_val > 1.0:
        raise ValueError(f"{field_name} must be a finite number between 0.0 and 1.0 (got {val})")


def _validate_duration(val: Any, field_name: str, max_seconds: float = 604800.0) -> None:
    if val is None:
        return
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise ValueError(f"{field_name} must be a number or None")
    f_val = float(val)
    if not math.isfinite(f_val) or f_val < 0.0 or f_val > max_seconds:
        raise ValueError(
            f"{field_name} must be a finite number between 0.0 and {max_seconds} (got {val})"
        )


def validate_community_payload(payload: dict[str, Any]) -> None:
    if not isinstance(payload, dict):
        raise ValueError("Payload must be a dictionary")

    try:
        serialized = json.dumps(payload, ensure_ascii=False)
        payload_len = len(serialized.encode("utf-8"))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Payload serialization failed: {exc}") from exc

    if payload_len > MAX_PAYLOAD_BYTES:
        raise ValueError(
            f"Payload size ({payload_len} bytes) exceeds limit of {MAX_PAYLOAD_BYTES} bytes"
        )

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

    if not _is_valid_uuid4(payload.get("event_id")):
        raise ValueError(f"event_id must be a valid UUIDv4 string, got '{payload.get('event_id')}'")

    if payload["event_type"] not in EVENT_TYPES:
        raise ValueError(f"Invalid event_type: {payload['event_type']}")

    if (
        not isinstance(payload["ai_dev_version"], str)
        or not 1 <= len(payload["ai_dev_version"]) <= 32
        or not AI_DEV_VERSION_REGEX.match(payload["ai_dev_version"])
    ):
        raise ValueError(f"Invalid ai_dev_version: '{payload.get('ai_dev_version')}'")

    if payload["os_family"] not in OS_FAMILIES:
        raise ValueError(f"Invalid os_family: {payload['os_family']}")

    if not isinstance(payload["python_version"], str) or not PYTHON_VERSION_REGEX.match(
        payload["python_version"]
    ):
        py_ver = payload.get("python_version")
        raise ValueError(
            f"python_version must be in major.minor format (e.g. '3.11'), got '{py_ver}'"
        )

    if payload["command_name"] not in COMMAND_NAMES:
        raise ValueError(f"Invalid command_name: {payload['command_name']}")

    if payload["command_category"] not in COMMAND_CATEGORIES:
        raise ValueError(f"Invalid command_category: {payload['command_category']}")

    if payload["command_outcome"] not in COMMAND_OUTCOMES:
        raise ValueError(f"Invalid command_outcome: {payload['command_outcome']}")

    if payload["reason_code"] is not None and payload["reason_code"] not in KNOWN_REASON_CODES:
        raise ValueError(f"Invalid reason_code: {payload['reason_code']}")

    if payload["duration_bucket"] not in DURATION_BUCKETS:
        raise ValueError(f"Invalid duration_bucket: {payload['duration_bucket']}")

    _validate_duration(payload["duration_seconds"], "duration_seconds", max_seconds=604800.0)

    if payload["cache_hit"] is not None and not isinstance(payload["cache_hit"], bool):
        raise ValueError(
            f"cache_hit must be a boolean or None, got {type(payload['cache_hit']).__name__}"
        )

    if not isinstance(payload["timestamp_hour"], str) or not TIMESTAMP_HOUR_REGEX.match(
        payload["timestamp_hour"]
    ):
        ts_hour = payload.get("timestamp_hour")
        raise ValueError(
            f"timestamp_hour must match format 'YYYY-MM-DDTHH:00:00Z', got '{ts_hour}'"
        )

    if level == "research":
        if payload["ai_client"] not in AI_CLIENTS:
            raise ValueError(f"Invalid ai_client: {payload['ai_client']}")
        if payload["model"] not in ALLOWED_MODELS:
            raise ValueError(
                f"Invalid model: '{payload['model']}'. "
                "Must be a sanitized known model, 'local', 'other', or 'unknown'"
            )
        if payload["task_kind"] not in TASK_KINDS:
            raise ValueError(f"Invalid task_kind: {payload['task_kind']}")
        if payload["validation_result"] not in VALIDATION_OUTCOMES:
            raise ValueError(f"Invalid validation_result: {payload['validation_result']}")
        if payload["task_outcome"] not in TASK_OUTCOMES:
            raise ValueError(f"Invalid task_outcome: {payload['task_outcome']}")
        if payload["repo_files_bucket"] not in REPO_FILES_BUCKETS:
            raise ValueError(f"Invalid repo_files_bucket: {payload['repo_files_bucket']}")
        if payload["repo_size_bucket"] not in REPO_SIZE_BUCKETS:
            raise ValueError(f"Invalid repo_size_bucket: {payload['repo_size_bucket']}")

        if not isinstance(payload["language_families"], list):
            raise ValueError("language_families must be a list")
        if len(payload["language_families"]) > 50:
            count = len(payload["language_families"])
            raise ValueError(f"language_families exceeds maximum length of 50 (got {count})")
        for lang in payload["language_families"]:
            if not isinstance(lang, str) or lang not in KNOWN_LANGUAGES:
                raise ValueError(f"Invalid language family: {lang}")

        if (
            payload["retrieval_reason_code"] is not None
            and payload["retrieval_reason_code"] not in RETRIEVAL_REASONS
        ):
            raise ValueError(f"Invalid retrieval_reason_code: {payload['retrieval_reason_code']}")

        if payload["selection_reason_codes"] is not None:
            if not isinstance(payload["selection_reason_codes"], list):
                raise ValueError("selection_reason_codes must be a list or None")
            if len(payload["selection_reason_codes"]) > 100:
                sc_count = len(payload["selection_reason_codes"])
                raise ValueError(
                    f"selection_reason_codes exceeds maximum length of 100 (got {sc_count})"
                )
            for code in payload["selection_reason_codes"]:
                if not isinstance(code, str) or code not in SELECTION_REASON_CODES:
                    raise ValueError(f"Invalid selection_reason_code: {code}")

        if payload["origin"] is not None and payload["origin"] not in PROVIDER_USAGE_ORIGINS:
            allowed_origins = sorted(PROVIDER_USAGE_ORIGINS)
            raise ValueError(
                f"Invalid origin: '{payload['origin']}'. Must be None or one of {allowed_origins}"
            )

        # Numeric and token bounds
        for tok_field in (
            "context_candidate_tokens",
            "context_delivered_tokens",
            "context_budget",
            "input_tokens",
            "cached_input_tokens",
            "output_tokens",
            "reasoning_tokens",
            "total_tokens",
        ):
            _validate_non_negative_int(payload[tok_field], tok_field, max_val=100_000_000)

        _validate_non_negative_int(payload["tool_call_count"], "tool_call_count", max_val=100_000)
        for file_field in ("files_considered", "files_selected", "files_omitted"):
            _validate_non_negative_int(payload[file_field], file_field, max_val=1_000_000)

        _validate_ratio(payload["cache_hit_ratio"], "cache_hit_ratio")
        _validate_ratio(payload["semantic_cache_reuse"], "semantic_cache_reuse")

        _validate_duration(
            payload["local_overhead_seconds"], "local_overhead_seconds", max_seconds=86400.0
        )
        _validate_duration(
            payload["total_wall_time_seconds"], "total_wall_time_seconds", max_seconds=604800.0
        )

        # Token consistency validation
        in_tok = payload["input_tokens"]
        out_tok = payload["output_tokens"]
        cached_tok = payload["cached_input_tokens"]
        tot_tok = payload["total_tokens"]

        if in_tok is not None and cached_tok is not None and cached_tok > in_tok:
            raise ValueError(
                f"cached_input_tokens ({cached_tok}) cannot exceed input_tokens ({in_tok})"
            )
        if tot_tok is not None and in_tok is not None and tot_tok < in_tok:
            raise ValueError(
                f"total_tokens ({tot_tok}) cannot be less than input_tokens ({in_tok})"
            )
        if tot_tok is not None and out_tok is not None and tot_tok < out_tok:
            raise ValueError(
                f"total_tokens ({tot_tok}) cannot be less than output_tokens ({out_tok})"
            )
        if (
            tot_tok is not None
            and in_tok is not None
            and out_tok is not None
            and tot_tok < in_tok + out_tok
        ):
            expected_min = in_tok + out_tok
            raise ValueError(
                f"total_tokens ({tot_tok}) cannot be less than input + output ({expected_min})"
            )
