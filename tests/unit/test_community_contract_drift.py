from __future__ import annotations

from ai_dev_tools.community import schema as client_schema
from collector.app import validation as server_validation


def test_contract_drift_constants_and_keys() -> None:
    """Ensure client schema definitions and server ingestion rules stay 100% in sync."""
    # Schema version
    assert client_schema.COMMUNITY_SCHEMA_VERSION == 1
    assert server_validation.COMMUNITY_SCHEMA_VERSION == 1

    # Payload size limit
    assert client_schema.MAX_PAYLOAD_BYTES == 32_768
    assert server_validation.MAX_PAYLOAD_BYTES == 32_768

    # Keys allowlist
    assert client_schema.BASIC_PAYLOAD_KEYS == server_validation.BASIC_PAYLOAD_KEYS
    assert client_schema.RESEARCH_ADDITIONAL_KEYS == server_validation.RESEARCH_ADDITIONAL_KEYS
    assert client_schema.RESEARCH_PAYLOAD_KEYS == server_validation.RESEARCH_PAYLOAD_KEYS

    # Enums & closed sets
    assert client_schema.EVENT_TYPES == server_validation.EVENT_TYPES
    assert client_schema.OS_FAMILIES == server_validation.OS_FAMILIES
    assert client_schema.COMMAND_NAMES == server_validation.COMMAND_NAMES
    assert client_schema.COMMAND_CATEGORIES == server_validation.COMMAND_CATEGORIES
    assert client_schema.COMMAND_OUTCOMES == server_validation.COMMAND_OUTCOMES
    assert client_schema.AI_CLIENTS == server_validation.AI_CLIENTS
    assert client_schema.TASK_KINDS == server_validation.TASK_KINDS
    assert client_schema.VALIDATION_OUTCOMES == server_validation.VALIDATION_OUTCOMES
    assert client_schema.TASK_OUTCOMES == server_validation.TASK_OUTCOMES
    assert client_schema.DURATION_BUCKETS == server_validation.DURATION_BUCKETS
    assert client_schema.REPO_FILES_BUCKETS == server_validation.REPO_FILES_BUCKETS
    assert client_schema.REPO_SIZE_BUCKETS == server_validation.REPO_SIZE_BUCKETS
    assert client_schema.KNOWN_LANGUAGES == server_validation.KNOWN_LANGUAGES
    assert client_schema.ALLOWED_MODELS == server_validation.ALLOWED_MODELS
    assert client_schema.PROVIDER_USAGE_ORIGINS == server_validation.PROVIDER_USAGE_ORIGINS

    # Regexes
    assert (
        client_schema.TIMESTAMP_HOUR_REGEX.pattern == server_validation.TIMESTAMP_HOUR_REGEX.pattern
    )
    assert (
        client_schema.PYTHON_VERSION_REGEX.pattern == server_validation.PYTHON_VERSION_REGEX.pattern
    )
    assert (
        client_schema.AI_DEV_VERSION_REGEX.pattern == server_validation.AI_DEV_VERSION_REGEX.pattern
    )
