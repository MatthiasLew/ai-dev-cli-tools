from __future__ import annotations

import json
import math
import re
import uuid
from typing import Any

from ai_dev_tools.community.schema import (
    AI_CLIENTS,
    AI_DEV_VERSION_REGEX,
    ALLOWED_MODELS,
    BASIC_PAYLOAD_KEYS,
    COMMAND_CATEGORIES,
    COMMAND_NAMES,
    COMMAND_OUTCOMES,
    COMMUNITY_SCHEMA_VERSION,
    DURATION_BUCKETS,
    EVENT_TYPES,
    KNOWN_LANGUAGES,
    KNOWN_REASON_CODES,
    MAX_PAYLOAD_BYTES,
    OS_FAMILIES,
    PROVIDER_USAGE_ORIGINS,
    REPO_FILES_BUCKETS,
    REPO_SIZE_BUCKETS,
    RESEARCH_ADDITIONAL_KEYS,
    RESEARCH_PAYLOAD_KEYS,
    RETRIEVAL_REASONS,
    SELECTION_REASON_CODES,
    TASK_KINDS,
    TASK_OUTCOMES,
    TIMESTAMP_HOUR_REGEX,
    VALIDATION_OUTCOMES,
)

PYTHON_VERSION_REGEX = re.compile(r"^3\.\d+$")

__all__ = [
    "AI_CLIENTS",
    "AI_DEV_VERSION_REGEX",
    "ALLOWED_MODELS",
    "BASIC_PAYLOAD_KEYS",
    "COMMAND_CATEGORIES",
    "COMMAND_NAMES",
    "COMMAND_OUTCOMES",
    "COMMUNITY_SCHEMA_VERSION",
    "DURATION_BUCKETS",
    "EVENT_TYPES",
    "KNOWN_LANGUAGES",
    "KNOWN_REASON_CODES",
    "MAX_PAYLOAD_BYTES",
    "OS_FAMILIES",
    "PROVIDER_USAGE_ORIGINS",
    "PYTHON_VERSION_REGEX",
    "REPO_FILES_BUCKETS",
    "REPO_SIZE_BUCKETS",
    "RESEARCH_ADDITIONAL_KEYS",
    "RESEARCH_PAYLOAD_KEYS",
    "RETRIEVAL_REASONS",
    "SELECTION_REASON_CODES",
    "TASK_KINDS",
    "TASK_OUTCOMES",
    "TIMESTAMP_HOUR_REGEX",
    "VALIDATION_OUTCOMES",
    "ValidationError",
    "validate_ingest_payload",
]


class ValidationError(ValueError):
    """Raised when server-side validation rejects an incoming payload."""

    def __init__(self, message: str, category: str = "validation_failed") -> None:
        super().__init__(message)
        self.message = message
        self.category = category


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
        raise ValidationError(
            f"{field_name} must be an integer or None (got {type(val).__name__})",
            category="invalid_type",
        )
    if val < 0 or val > max_val:
        raise ValidationError(
            f"{field_name} must be between 0 and {max_val} (got {val})",
            category="numeric_out_of_bounds",
        )


def _validate_ratio(val: Any, field_name: str) -> None:
    if val is None:
        return
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise ValidationError(f"{field_name} must be a number or None", category="invalid_type")
    f_val = float(val)
    if not math.isfinite(f_val) or f_val < 0.0 or f_val > 1.0:
        raise ValidationError(
            f"{field_name} must be a finite number between 0.0 and 1.0 (got {val})",
            category="numeric_out_of_bounds",
        )


def _validate_duration(val: Any, field_name: str, max_seconds: float = 604800.0) -> None:
    if val is None:
        return
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise ValidationError(f"{field_name} must be a number or None", category="invalid_type")
    f_val = float(val)
    if not math.isfinite(f_val) or f_val < 0.0 or f_val > max_seconds:
        raise ValidationError(
            f"{field_name} must be a finite number between 0.0 and {max_seconds} (got {val})",
            category="numeric_out_of_bounds",
        )


def validate_ingest_payload(payload: Any) -> dict[str, Any]:
    """Strict, fail-closed server-side validation for Community Telemetry events."""
    if not isinstance(payload, dict):
        raise ValidationError("Payload must be a JSON object", category="invalid_payload")

    # Serialize to check size limit
    try:
        serialized = json.dumps(payload, ensure_ascii=False)
        payload_bytes = len(serialized.encode("utf-8"))
    except (TypeError, ValueError) as exc:
        raise ValidationError(
            f"Serialization failed: {exc}", category="serialization_failed"
        ) from exc

    if payload_bytes > MAX_PAYLOAD_BYTES:
        raise ValidationError(
            f"Payload size ({payload_bytes} bytes) exceeds limit of {MAX_PAYLOAD_BYTES} bytes",
            category="payload_too_large",
        )

    # 1. Level check
    level = payload.get("telemetry_level")
    if level == "basic":
        allowed_keys = BASIC_PAYLOAD_KEYS
    elif level == "research":
        allowed_keys = RESEARCH_PAYLOAD_KEYS
    else:
        raise ValidationError(
            f"Invalid telemetry_level: '{level}'", category="invalid_telemetry_level"
        )

    # 2. Event type check
    event_type = payload.get("event_type")
    if event_type not in EVENT_TYPES:
        raise ValidationError(f"Invalid event_type: '{event_type}'", category="invalid_event_type")

    if event_type == "provider_usage" and level != "research":
        raise ValidationError(
            "provider_usage event is only allowed with telemetry_level='research'",
            category="invalid_event_type_level",
        )

    # 3. Exact allowlist (no extra fields, no missing fields)
    actual_keys = set(payload.keys())
    unexpected = actual_keys - allowed_keys
    if unexpected:
        raise ValidationError(
            f"Unexpected keys in {level} payload: {sorted(unexpected)}",
            category="unexpected_keys",
        )

    missing = allowed_keys - actual_keys
    if missing:
        raise ValidationError(
            f"Missing required {level} keys in payload: {sorted(missing)}",
            category="missing_keys",
        )

    # 4. Schema version
    if (
        isinstance(payload["schema_version"], bool)
        or payload["schema_version"] != COMMUNITY_SCHEMA_VERSION
    ):
        raise ValidationError(
            f"Unsupported schema_version: {payload.get('schema_version')}",
            category="unsupported_schema_version",
        )

    # 5. Identity & Formats
    if not _is_valid_uuid4(payload.get("event_id")):
        raise ValidationError(
            f"event_id must be a valid UUIDv4 string, got '{payload.get('event_id')}'",
            category="invalid_event_id",
        )

    # 6. Event Type Invariants
    if event_type == "command_run":
        if level == "research" and payload.get("origin") is not None:
            raise ValidationError(
                f"command_run event must have origin=None, got '{payload.get('origin')}'",
                category="invalid_origin",
            )
    elif event_type == "provider_usage":
        origin = payload.get("origin")
        if origin is None:
            raise ValidationError(
                "provider_usage event requires origin to be set, got None",
                category="invalid_origin",
            )
        if origin not in PROVIDER_USAGE_ORIGINS:
            allowed_origins = sorted(PROVIDER_USAGE_ORIGINS)
            raise ValidationError(
                f"provider_usage origin must be one of {allowed_origins}, got '{origin}'",
                category="invalid_origin",
            )

        cmd_name = payload.get("command_name")
        if origin == "mcp" and cmd_name != "mcp":
            raise ValidationError(
                f"provider_usage with origin='mcp' must have command_name='mcp', got '{cmd_name}'",
                category="invalid_command_name",
            )
        if origin == "import" and cmd_name != "telemetry":
            raise ValidationError(
                "provider_usage with origin='import' must have command_name='telemetry', "
                f"got '{cmd_name}'",
                category="invalid_command_name",
            )
        if origin == "unknown" and cmd_name != "mcp":
            raise ValidationError(
                "provider_usage with origin='unknown' must have command_name='mcp', "
                f"got '{cmd_name}'",
                category="invalid_command_name",
            )

        cmd_cat = payload.get("command_category")
        if cmd_cat != "telemetry":
            raise ValidationError(
                f"provider_usage event must have command_category='telemetry', got '{cmd_cat}'",
                category="invalid_command_category",
            )

    # 7. Basic fields validation
    ai_dev_ver = payload.get("ai_dev_version")
    if (
        not isinstance(ai_dev_ver, str)
        or not (1 <= len(ai_dev_ver) <= 32)
        or not AI_DEV_VERSION_REGEX.match(ai_dev_ver)
    ):
        raise ValidationError(f"Invalid ai_dev_version: '{ai_dev_ver}'", category="invalid_version")

    if payload["os_family"] not in OS_FAMILIES:
        raise ValidationError(
            f"Invalid os_family: '{payload['os_family']}'", category="invalid_enum"
        )

    py_ver = payload.get("python_version")
    if not isinstance(py_ver, str) or not PYTHON_VERSION_REGEX.match(py_ver):
        raise ValidationError(
            f"python_version must be in major.minor format (e.g. '3.11'), got '{py_ver}'",
            category="invalid_python_version",
        )

    if payload["command_name"] not in COMMAND_NAMES:
        raise ValidationError(
            f"Invalid command_name: '{payload['command_name']}'", category="invalid_enum"
        )

    if payload["command_category"] not in COMMAND_CATEGORIES:
        raise ValidationError(
            f"Invalid command_category: '{payload['command_category']}'", category="invalid_enum"
        )

    if payload["command_outcome"] not in COMMAND_OUTCOMES:
        raise ValidationError(
            f"Invalid command_outcome: '{payload['command_outcome']}'", category="invalid_enum"
        )

    if payload["reason_code"] is not None and payload["reason_code"] not in KNOWN_REASON_CODES:
        raise ValidationError(
            f"Invalid reason_code: '{payload['reason_code']}'", category="invalid_enum"
        )

    if payload["duration_bucket"] not in DURATION_BUCKETS:
        raise ValidationError(
            f"Invalid duration_bucket: '{payload['duration_bucket']}'", category="invalid_enum"
        )

    _validate_duration(payload["duration_seconds"], "duration_seconds", max_seconds=604800.0)

    if payload["cache_hit"] is not None and not isinstance(payload["cache_hit"], bool):
        raise ValidationError(
            f"cache_hit must be a boolean or None, got {type(payload['cache_hit']).__name__}",
            category="invalid_type",
        )

    ts_hour = payload.get("timestamp_hour")
    if not isinstance(ts_hour, str) or not TIMESTAMP_HOUR_REGEX.match(ts_hour):
        raise ValidationError(
            f"timestamp_hour must match format 'YYYY-MM-DDTHH:00:00Z', got '{ts_hour}'",
            category="invalid_timestamp",
        )

    # 8. Research fields validation
    if level == "research":
        if payload["ai_client"] not in AI_CLIENTS:
            raise ValidationError(
                f"Invalid ai_client: '{payload['ai_client']}'", category="invalid_enum"
            )
        if payload["model"] not in ALLOWED_MODELS:
            raise ValidationError(
                f"Invalid model: '{payload['model']}'. "
                "Must be a sanitized known model, 'local', 'other', or 'unknown'",
                category="invalid_model",
            )
        if payload["task_kind"] not in TASK_KINDS:
            raise ValidationError(
                f"Invalid task_kind: '{payload['task_kind']}'", category="invalid_enum"
            )
        if payload["validation_result"] not in VALIDATION_OUTCOMES:
            raise ValidationError(
                f"Invalid validation_result: '{payload['validation_result']}'",
                category="invalid_enum",
            )
        if payload["task_outcome"] not in TASK_OUTCOMES:
            raise ValidationError(
                f"Invalid task_outcome: '{payload['task_outcome']}'", category="invalid_enum"
            )
        if payload["repo_files_bucket"] not in REPO_FILES_BUCKETS:
            raise ValidationError(
                f"Invalid repo_files_bucket: '{payload['repo_files_bucket']}'",
                category="invalid_enum",
            )
        if payload["repo_size_bucket"] not in REPO_SIZE_BUCKETS:
            raise ValidationError(
                f"Invalid repo_size_bucket: '{payload['repo_size_bucket']}'",
                category="invalid_enum",
            )

        if not isinstance(payload["language_families"], list):
            raise ValidationError("language_families must be a list", category="invalid_type")
        if len(payload["language_families"]) > 50:
            count = len(payload["language_families"])
            raise ValidationError(
                f"language_families exceeds maximum length of 50 (got {count})",
                category="list_limit_exceeded",
            )
        for lang in payload["language_families"]:
            if not isinstance(lang, str) or lang not in KNOWN_LANGUAGES:
                raise ValidationError(f"Invalid language family: '{lang}'", category="invalid_enum")

        if (
            payload["retrieval_reason_code"] is not None
            and payload["retrieval_reason_code"] not in RETRIEVAL_REASONS
        ):
            raise ValidationError(
                f"Invalid retrieval_reason_code: '{payload['retrieval_reason_code']}'",
                category="invalid_enum",
            )

        if payload["selection_reason_codes"] is not None:
            if not isinstance(payload["selection_reason_codes"], list):
                raise ValidationError(
                    "selection_reason_codes must be a list or None", category="invalid_type"
                )
            if len(payload["selection_reason_codes"]) > 100:
                sc_count = len(payload["selection_reason_codes"])
                raise ValidationError(
                    f"selection_reason_codes exceeds maximum length of 100 (got {sc_count})",
                    category="list_limit_exceeded",
                )
            for code in payload["selection_reason_codes"]:
                if not isinstance(code, str) or code not in SELECTION_REASON_CODES:
                    raise ValidationError(
                        f"Invalid selection_reason_code: '{code}'", category="invalid_enum"
                    )

        # Numeric bounds
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

        # Token consistency
        in_tok = payload["input_tokens"]
        out_tok = payload["output_tokens"]
        cached_tok = payload["cached_input_tokens"]
        tot_tok = payload["total_tokens"]

        if in_tok is not None and cached_tok is not None and cached_tok > in_tok:
            raise ValidationError(
                f"cached_input_tokens ({cached_tok}) cannot exceed input_tokens ({in_tok})",
                category="token_inconsistency",
            )
        if tot_tok is not None and in_tok is not None and tot_tok < in_tok:
            raise ValidationError(
                f"total_tokens ({tot_tok}) cannot be less than input_tokens ({in_tok})",
                category="token_inconsistency",
            )
        if tot_tok is not None and out_tok is not None and tot_tok < out_tok:
            raise ValidationError(
                f"total_tokens ({tot_tok}) cannot be less than output_tokens ({out_tok})",
                category="token_inconsistency",
            )
        if (
            tot_tok is not None
            and in_tok is not None
            and out_tok is not None
            and tot_tok < in_tok + out_tok
        ):
            expected_min = in_tok + out_tok
            raise ValidationError(
                f"total_tokens ({tot_tok}) cannot be less than input + output ({expected_min})",
                category="token_inconsistency",
            )

    return payload
