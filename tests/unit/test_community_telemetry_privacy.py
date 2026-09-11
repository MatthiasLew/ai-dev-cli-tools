from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest

from ai_dev_tools.community.builder import build_community_payload
from ai_dev_tools.community.config import (
    CommunityTelemetryConfig,
    load_community_config,
    save_community_config,
)
from ai_dev_tools.community.schema import (
    BASIC_PAYLOAD_KEYS,
    RESEARCH_PAYLOAD_KEYS,
    validate_community_payload,
)
from ai_dev_tools.models.report import Report


@pytest.fixture(autouse=True)
def isolate_telemetry_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_dir = tmp_path / "config"
    data_dir = tmp_path / "data"
    monkeypatch.setenv("AI_DEV_COMMUNITY_TELEMETRY_CONFIG_DIR", str(config_dir))
    monkeypatch.setenv("AI_DEV_COMMUNITY_TELEMETRY_DATA_DIR", str(data_dir))
    monkeypatch.delenv("AI_DEV_COMMUNITY_TELEMETRY_ENDPOINT", raising=False)


def test_basic_payload_exact_allowlisted_keys() -> None:
    payload = build_community_payload("basic", sample=True)
    assert set(payload.keys()) == BASIC_PAYLOAD_KEYS
    validate_community_payload(payload)


def test_research_payload_exact_allowlisted_keys() -> None:
    payload = build_community_payload("research", sample=True)
    assert set(payload.keys()) == RESEARCH_PAYLOAD_KEYS
    validate_community_payload(payload)


def test_extra_key_rejected_by_allowlist() -> None:
    payload = build_community_payload("basic", sample=True)
    payload["forbidden_extra_key"] = "leak"
    with pytest.raises(ValueError, match="Unexpected keys"):
        validate_community_payload(payload)


def test_deliberate_injection_of_sensitive_data_never_leaks(tmp_path: Path) -> None:
    sensitive_strings = [
        "/home/alice/secret-repo",
        "C:\\Users\\Bob\\SuperSecretProject",
        "https://github.com/my-org/private-repo.git",
        "git@github.com:my-org/private-repo.git",
        "developer@company.com",
        "sk-proj-abc1234567890abcdefghijklmnopqrstuvwxyz",
        "ghp_1234567890abcdefghijklmnopqrstuvwxyz",
        "SECRET_API_KEY=xyz987",
        "my-secret-hostname.internal.corp",
        "SELECT * FROM users WHERE password_hash = '123';",
        "def private_algorithm(): return 'secret'",
        "commit 4b825dc642cb6eb9a060e54bf8d69288fbee4904",
        "feature/secret-stealth-project",
        "Fix confidential bug in payment processing",
    ]

    # Create a report loaded with malicious/sensitive fields across all possible properties
    report = Report(command="context build", project_root=tmp_path)
    report.summary = {
        "client": "cursor",
        "model": "claude-3-5-sonnet",
        "task_kind": "feature",
        "raw_prompt": sensitive_strings[0],
        "system_prompt": sensitive_strings[1],
        "model_response": sensitive_strings[2],
        "user_email": sensitive_strings[4],
        "api_key": sensitive_strings[5],
        "env_vars": {"SECRET": sensitive_strings[7]},
        "hostname": sensitive_strings[8],
        "source_code": sensitive_strings[10],
        "git_remote": sensitive_strings[3],
        "branch": sensitive_strings[12],
        "commit_message": sensitive_strings[13],
        "selected_files": [
            {
                "path": "C:\\Users\\Bob\\SuperSecretProject\\secret.py",
                "name": "secret.py",
                "content": sensitive_strings[9],
                "reason_code": "IMPORT_DEPENDENCY",
            }
        ],
    }

    # Build both basic and research payloads
    basic_payload = build_community_payload("basic", report=report, project_root=tmp_path)
    research_payload = build_community_payload("research", report=report, project_root=tmp_path)

    basic_json = json.dumps(basic_payload)
    research_json = json.dumps(research_payload)

    for sensitive in sensitive_strings:
        assert sensitive not in basic_json, f"Sensitive string leaked in BASIC: {sensitive}"
        assert sensitive not in research_json, f"Sensitive string leaked in RESEARCH: {sensitive}"

    # Verify no file path substrings exist
    assert "SuperSecretProject" not in basic_json
    assert "SuperSecretProject" not in research_json
    assert "secret.py" not in basic_json
    assert "secret.py" not in research_json


def test_no_persistent_user_tracking_identifiers() -> None:
    # Generate 50 events and verify none share user_id, machine fingerprint, or install_id
    forbidden_identifier_keys = {
        "user_id",
        "userId",
        "installation_id",
        "install_id",
        "machine_id",
        "device_id",
        "fingerprint",
        "machine_fingerprint",
        "hardware_id",
        "mac_address",
        "hostname",
        "username",
        "ip",
        "ip_address",
    }

    event_ids: set[str] = set()
    for _ in range(50):
        payload = build_community_payload("research", sample=True)
        keys = set(payload.keys())
        for forbidden in forbidden_identifier_keys:
            assert forbidden not in keys

        event_id = payload["event_id"]
        # Verify it is a valid UUIDv4
        parsed = uuid.UUID(event_id, version=4)
        assert str(parsed) == event_id
        assert event_id not in event_ids
        event_ids.add(event_id)

    assert len(event_ids) == 50


def test_config_never_contains_tracking_identifiers(tmp_path: Path) -> None:
    save_community_config("basic", endpoint="https://telemetry.example.com/events")
    cfg = load_community_config()
    assert isinstance(cfg, CommunityTelemetryConfig)
    assert cfg.telemetry_level == "basic"
    assert cfg.endpoint == "https://telemetry.example.com/events"

    # Inspect the raw JSON on disk
    config_file = tmp_path / "config" / "community_telemetry.json"
    raw_content = json.loads(config_file.read_text(encoding="utf-8"))
    assert set(raw_content.keys()) == {"telemetry_level", "endpoint"}
