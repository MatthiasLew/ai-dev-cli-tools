from __future__ import annotations

import json
import os
import time
from pathlib import Path
from threading import Thread
from typing import Any
from unittest.mock import patch

import pytest

from ai_dev_tools.cli import main
from ai_dev_tools.community.builder import build_community_payload
from ai_dev_tools.community.config import (
    CONFIG_FILENAME,
    get_user_config_dir,
    load_community_config,
    save_community_config,
)
from ai_dev_tools.community.queue import (
    MAX_QUEUE_ITEMS,
    enqueue_event,
    get_queue_dir,
    list_queued_events,
    prune_queue,
    queue_size,
)
from ai_dev_tools.community.schema import (
    BASIC_PAYLOAD_KEYS,
    RESEARCH_PAYLOAD_KEYS,
    validate_community_payload,
)
from ai_dev_tools.community.service import (
    disable_telemetry,
    enable_telemetry,
    get_telemetry_status,
    preview_telemetry,
    record_command_event,
)
from ai_dev_tools.community.transport import send_event, validate_endpoint_url
from ai_dev_tools.models.report import Report


@pytest.fixture(autouse=True)
def isolate_telemetry_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_dir = tmp_path / "config"
    data_dir = tmp_path / "data"
    monkeypatch.setenv("AI_DEV_COMMUNITY_TELEMETRY_CONFIG_DIR", str(config_dir))
    monkeypatch.setenv("AI_DEV_COMMUNITY_TELEMETRY_DATA_DIR", str(data_dir))
    monkeypatch.delenv("AI_DEV_COMMUNITY_TELEMETRY_ENDPOINT", raising=False)
    monkeypatch.setenv("AI_DEV_COMMUNITY_TELEMETRY_NO_AUTO_FLUSH", "1")


# 1. Default = OFF
def test_1_default_state_is_off() -> None:
    cfg = load_community_config()
    assert cfg.telemetry_level == "off"
    assert not cfg.is_enabled
    status_report = get_telemetry_status()
    assert status_report.summary["community_telemetry"] == "OFF"
    assert status_report.summary["queued_events"] == 0


# 2. OFF: zero network calls, zero queue files
def test_2_off_records_zero_queue_files_and_zero_network(tmp_path: Path) -> None:
    report = Report(command="scan", project_root=tmp_path)
    report.status = "success"

    with patch("urllib.request.urlopen") as mock_urlopen:
        record_command_event(report, duration_seconds=0.1, project_root=tmp_path)
        assert mock_urlopen.call_count == 0
        assert queue_size() == 0
        assert not get_queue_dir().exists()


# 3. Enable basic: status BASIC, payload contains only BASIC fields
def test_3_enable_basic_status_and_payload_fields(tmp_path: Path) -> None:
    res = enable_telemetry("basic")
    assert res.status == "success"
    assert res.summary["community_telemetry"] == "BASIC"

    status = get_telemetry_status()
    assert status.summary["community_telemetry"] == "BASIC"

    payload = build_community_payload("basic", sample=True)
    assert payload["telemetry_level"] == "basic"
    assert set(payload.keys()) == BASIC_PAYLOAD_KEYS


# 4. Enable research: status RESEARCH, payload contains research fields
def test_4_enable_research_status_and_payload_fields() -> None:
    res = enable_telemetry("research")
    assert res.status == "success"
    assert res.summary["community_telemetry"] == "RESEARCH"

    status = get_telemetry_status()
    assert status.summary["community_telemetry"] == "RESEARCH"

    payload = build_community_payload("research", sample=True)
    assert payload["telemetry_level"] == "research"
    assert set(payload.keys()) == RESEARCH_PAYLOAD_KEYS
    assert "language_families" in payload
    assert "repo_files_bucket" in payload


# 5. Disable: immediately stops new events, deletes queued events
def test_5_disable_clears_queue_and_stops_new_events(tmp_path: Path) -> None:
    enable_telemetry("basic")
    report = Report(command="scan", project_root=tmp_path)
    record_command_event(report, 0.2, tmp_path)
    assert queue_size() == 1

    disable_res = disable_telemetry()
    assert disable_res.status == "success"
    assert disable_res.summary["community_telemetry"] == "OFF"
    assert queue_size() == 0

    # New command event should not be recorded
    record_command_event(report, 0.2, tmp_path)
    assert queue_size() == 0


# 6. Preview: zero network calls, exact same serializer as sender
def test_6_preview_uses_exact_serializer_and_makes_no_network_calls() -> None:
    with patch("urllib.request.urlopen") as mock_urlopen:
        preview_basic = preview_telemetry("basic")
        preview_research = preview_telemetry("research")
        assert mock_urlopen.call_count == 0

    assert preview_basic.status == "success"
    assert preview_research.status == "success"

    payload_basic = preview_basic.summary["payload"]
    payload_research = preview_research.summary["payload"]

    validate_community_payload(payload_basic)
    validate_community_payload(payload_research)

    assert payload_basic["telemetry_level"] == "basic"
    assert payload_research["telemetry_level"] == "research"


# 7. Network failure: main command still succeeds, event queued, no exception
def test_7_network_failure_does_not_break_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("AI_DEV_COMMUNITY_TELEMETRY_NO_AUTO_FLUSH", raising=False)
    save_community_config(
        "basic", endpoint="https://non-existent-telemetry.example.invalid/events"
    )

    # Running main CLI command
    exit_code = main(["--project", str(tmp_path), "capabilities"])
    assert exit_code == 0
    # The event is safely in queue
    assert queue_size() >= 1


# 8. Malformed endpoint response handled gracefully
def test_8_malformed_endpoint_response_handled() -> None:
    class MockBadResponse:
        status = 502
        def __enter__(self) -> MockBadResponse:
            return self
        def __exit__(self, *args: Any) -> None:
            pass

    with patch("urllib.request.urlopen", return_value=MockBadResponse()):
        payload = build_community_payload("basic", sample=True)
        res = send_event("http://127.0.0.1:9999/events", payload, retries=1)
        assert not res.success
        assert res.status_code == 502
        assert res.retryable is True


# 9. Endpoint timeout handled gracefully
def test_9_endpoint_timeout_handled() -> None:
    with patch("urllib.request.urlopen", side_effect=TimeoutError("Connection timed out")):
        payload = build_community_payload("basic", sample=True)
        res = send_event("http://127.0.0.1:9999/events", payload, timeout=0.1, retries=1)
        assert not res.success
        assert "timed out" in res.message.lower()
        assert res.retryable is True


# 10. Queue limit: bounded to max items, oldest pruned
def test_10_queue_limit_bounded() -> None:
    enable_telemetry("basic")
    queue_dir = get_queue_dir()
    queue_dir.mkdir(parents=True, exist_ok=True)

    # Insert 1005 mock events
    now_ns = time.time_ns()
    payload = build_community_payload("basic", sample=True)
    serialized = json.dumps(payload).encode("utf-8")

    for i in range(1005):
        filename = f"{now_ns + i}_{payload['event_id']}.json"
        (queue_dir / filename).write_bytes(serialized)

    assert len(list(queue_dir.glob("*.json"))) == 1005

    # Enqueue one more; prune_queue should cap it under MAX_QUEUE_ITEMS
    enqueue_event(payload)
    assert queue_size() <= MAX_QUEUE_ITEMS


# 11. Queue expiration: events > 7 days old pruned
def test_11_queue_expiration_prunes_old_events() -> None:
    queue_dir = get_queue_dir()
    queue_dir.mkdir(parents=True, exist_ok=True)

    payload = build_community_payload("basic", sample=True)
    serialized = json.dumps(payload).encode("utf-8")

    old_file = queue_dir / "old_event.json"
    old_file.write_bytes(serialized)

    # Set mtime to 10 days ago
    ten_days_ago = time.time() - (10 * 86400)
    os.utime(old_file, (ten_days_ago, ten_days_ago))

    # New file
    new_file = queue_dir / "new_event.json"
    new_file.write_bytes(serialized)

    prune_queue()

    assert not old_file.exists()
    assert new_file.exists()


# 12. Concurrent writes to queue are safe
def test_12_concurrent_writes_to_queue() -> None:
    enable_telemetry("basic")
    payload = build_community_payload("basic", sample=True)

    def worker() -> None:
        for _ in range(10):
            enqueue_event(payload)

    threads = [Thread(target=worker) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # All 50 events should be successfully queued without corruption
    events = list_queued_events()
    assert len(events) == 50


# 13. Corrupted queue file handled safely
def test_13_corrupted_queue_file_ignored_and_deleted() -> None:
    queue_dir = get_queue_dir()
    queue_dir.mkdir(parents=True, exist_ok=True)

    corrupt = queue_dir / "corrupted.json"
    corrupt.write_text("{ incomplete json ...", encoding="utf-8")

    payload = build_community_payload("basic", sample=True)
    valid_path = enqueue_event(payload)
    assert valid_path is not None

    events = list_queued_events()
    assert len(events) == 1
    assert not corrupt.exists()


# 14. Unknown telemetry level handled safely
def test_14_unknown_telemetry_level_fails_cleanly(tmp_path: Path) -> None:
    res = enable_telemetry("unsupported_level")
    assert res.status == "failed"

    with pytest.raises(ValueError, match="Invalid telemetry level"):
        save_community_config("invalid_level")

    # If corrupted directly in file, load_community_config falls back to 'off'
    cfg_file = get_user_config_dir() / CONFIG_FILENAME
    cfg_file.parent.mkdir(parents=True, exist_ok=True)
    cfg_file.write_text(json.dumps({"telemetry_level": "hacked"}), encoding="utf-8")

    loaded = load_community_config()
    assert loaded.telemetry_level == "off"


# 15. Production endpoint must use HTTPS
def test_15_production_endpoint_requires_https() -> None:
    with pytest.raises(ValueError, match="must use HTTPS"):
        validate_endpoint_url("http://telemetry.ai-dev.org/events")

    with pytest.raises(ValueError, match="must use HTTPS"):
        validate_endpoint_url("http://192.168.1.50:8080/events")

    # HTTPS is allowed
    validate_endpoint_url("https://telemetry.ai-dev.org/events")


# 16. Localhost/http allowed only for dev/test
def test_16_localhost_http_allowed_for_dev_and_test() -> None:
    validate_endpoint_url("http://localhost:8080/events")
    validate_endpoint_url("http://127.0.0.1:8000/events")
    validate_endpoint_url("http://[::1]:8000/events")


# 17. Privacy allowlist validation
def test_17_privacy_allowlist_validation() -> None:
    payload = build_community_payload("basic", sample=True)
    payload["unknown_metric"] = 42
    with pytest.raises(ValueError, match="Unexpected keys in basic payload"):
        validate_community_payload(payload)


# 18. No persistent identifier across sessions
def test_18_no_persistent_identifier_across_sessions() -> None:
    p1 = build_community_payload("basic", sample=True)
    p2 = build_community_payload("basic", sample=True)
    assert p1["event_id"] != p2["event_id"]
    for key in ("user_id", "installation_id", "machine_id", "device_id"):
        assert key not in p1
        assert key not in p2


# 19. Event ID changes across events
def test_19_event_id_changes_across_events() -> None:
    ids = {build_community_payload("basic", sample=True)["event_id"] for _ in range(20)}
    assert len(ids) == 20


# 20. No hidden enable through unrelated config
def test_20_no_hidden_enable_through_unrelated_config(tmp_path: Path) -> None:
    repo_config = tmp_path / ".ai-dev-tools.toml"
    repo_config.write_text(
        """
[project]
name = "test"

[telemetry]
enabled = true
level = "research"
""",
        encoding="utf-8",
    )

    cfg = load_community_config()
    assert cfg.telemetry_level == "off"
    assert not cfg.is_enabled
