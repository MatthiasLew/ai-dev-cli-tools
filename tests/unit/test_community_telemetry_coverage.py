import json
import os
import sys
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from ai_dev_tools.community.builder import (
    build_community_payload,
    compute_repo_buckets,
    detect_language_families,
)
from ai_dev_tools.community.config import (
    CONFIG_FILENAME,
    get_user_config_dir,
    get_user_data_dir,
    load_community_config,
    save_community_config,
)
from ai_dev_tools.community.queue import (
    clear_queue,
    enqueue_event,
    get_queue_dir,
    list_queued_events,
    prune_queue,
    queue_size,
    remove_event,
)
from ai_dev_tools.community.schema import (
    MAX_PAYLOAD_BYTES,
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
from ai_dev_tools.community.service import (
    _opportunistic_flush,
    flush_telemetry,
    preview_telemetry,
    record_command_event,
)
from ai_dev_tools.community.transport import (
    UploadResult,
    send_event,
    validate_endpoint_url,
)
from ai_dev_tools.models.report import Issue, Report


@pytest.fixture(autouse=True)
def isolate_telemetry_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_dir = tmp_path / "config"
    data_dir = tmp_path / "data"
    monkeypatch.setenv("AI_DEV_COMMUNITY_TELEMETRY_CONFIG_DIR", str(config_dir))
    monkeypatch.setenv("AI_DEV_COMMUNITY_TELEMETRY_DATA_DIR", str(data_dir))
    monkeypatch.delenv("AI_DEV_COMMUNITY_TELEMETRY_ENDPOINT", raising=False)
    monkeypatch.setenv("AI_DEV_COMMUNITY_TELEMETRY_NO_AUTO_FLUSH", "1")


def test_schema_bucketing_and_helpers() -> None:
    # duration_bucket
    assert duration_bucket(None) == "unknown"
    assert duration_bucket(-1.0) == "unknown"
    assert duration_bucket(0.05) == "<100ms"
    assert duration_bucket(0.2) == "100ms-500ms"
    assert duration_bucket(0.8) == "500ms-1s"
    assert duration_bucket(3.0) == "1s-5s"
    assert duration_bucket(15.0) == "5s-30s"
    assert duration_bucket(60.0) == "30s-120s"
    assert duration_bucket(150.0) == "120s+"

    # repo_files_bucket
    assert repo_files_bucket(None) == "unknown"
    assert repo_files_bucket(-5) == "unknown"
    assert repo_files_bucket(25) == "1-50"
    assert repo_files_bucket(100) == "51-200"
    assert repo_files_bucket(500) == "201-1000"
    assert repo_files_bucket(2500) == "1001-5000"
    assert repo_files_bucket(9000) == "5000+"

    # repo_size_bucket
    assert repo_size_bucket(None) == "unknown"
    assert repo_size_bucket(-10) == "unknown"
    assert repo_size_bucket(500 * 1024) == "<1MB"
    assert repo_size_bucket(5 * 1024 * 1024) == "1-10MB"
    assert repo_size_bucket(25 * 1024 * 1024) == "10-50MB"
    assert repo_size_bucket(100 * 1024 * 1024) == "50-250MB"
    assert repo_size_bucket(500 * 1024 * 1024) == "250MB+"

    # sanitize_model_name
    assert sanitize_model_name(None) == "unknown"
    assert sanitize_model_name("") == "unknown"
    assert sanitize_model_name("openai/gpt-4o") == "gpt-4o"
    assert sanitize_model_name("claude-3-5-sonnet-20241022") == "claude-3-5-sonnet"
    assert sanitize_model_name("my-ollama-llama3") == "local"
    assert sanitize_model_name("completely-custom-private-model") == "other"

    # sanitize_task_kind
    assert sanitize_task_kind(None) == "unknown"
    assert sanitize_task_kind("") == "unknown"
    assert sanitize_task_kind("BUGFIX") == "bugfix"
    assert sanitize_task_kind("nonexistent_kind") == "unknown"

    # sanitize_reason_code
    assert sanitize_reason_code(None) is None
    assert sanitize_reason_code("") is None
    assert sanitize_reason_code("none") == "NONE"
    assert sanitize_reason_code("unknown_reason") == "UNKNOWN"

    # get_os_family & python version
    assert get_os_family() in {"windows", "linux", "macos", "other"}
    assert "." in get_python_version()
    assert get_utc_hour_timestamp().endswith("00:00Z")


def test_schema_validation_failures() -> None:
    with pytest.raises(ValueError, match="must be a dictionary"):
        validate_community_payload("not_a_dict")  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="Invalid telemetry_level"):
        validate_community_payload({"telemetry_level": "ultra"})

    valid_basic = build_community_payload("basic", sample=True)

    # Missing required basic key
    incomplete = dict(valid_basic)
    del incomplete["event_id"]
    with pytest.raises(ValueError, match="Missing required basic keys"):
        validate_community_payload(incomplete)

    # Unsupported schema version
    bad_ver = dict(valid_basic)
    bad_ver["schema_version"] = 99
    with pytest.raises(ValueError, match="Unsupported schema_version"):
        validate_community_payload(bad_ver)

    # Invalid os family
    bad_os = dict(valid_basic)
    bad_os["os_family"] = "beos"
    with pytest.raises(ValueError, match="Invalid os_family"):
        validate_community_payload(bad_os)

    # Invalid outcome
    bad_out = dict(valid_basic)
    bad_out["command_outcome"] = "catastrophic"
    with pytest.raises(ValueError, match="Invalid command_outcome"):
        validate_community_payload(bad_out)

    # Research validation failures
    valid_research = build_community_payload("research", sample=True)

    # Missing research key
    inc_res = dict(valid_research)
    del inc_res["ai_client"]
    with pytest.raises(ValueError, match="Missing required research keys"):
        validate_community_payload(inc_res)

    # Invalid ai client
    bad_client = dict(valid_research)
    bad_client["ai_client"] = "unknown_bot"
    with pytest.raises(ValueError, match="Invalid ai_client"):
        validate_community_payload(bad_client)

    # Invalid task kind
    bad_task = dict(valid_research)
    bad_task["task_kind"] = "dancing"
    with pytest.raises(ValueError, match="Invalid task_kind"):
        validate_community_payload(bad_task)

    # Invalid validation result
    bad_val = dict(valid_research)
    bad_val["validation_result"] = "maybe"
    with pytest.raises(ValueError, match="Invalid validation_result"):
        validate_community_payload(bad_val)

    # Invalid task outcome
    bad_to = dict(valid_research)
    bad_to["task_outcome"] = "halfway"
    with pytest.raises(ValueError, match="Invalid task_outcome"):
        validate_community_payload(bad_to)

    # Invalid language families type or item
    bad_lang_type = dict(valid_research)
    bad_lang_type["language_families"] = "python"
    with pytest.raises(ValueError, match="must be a list"):
        validate_community_payload(bad_lang_type)

    bad_lang_item = dict(valid_research)
    bad_lang_item["language_families"] = ["klingon"]
    with pytest.raises(ValueError, match="Invalid language family"):
        validate_community_payload(bad_lang_item)


def test_config_platform_paths(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("AI_DEV_COMMUNITY_TELEMETRY_CONFIG_DIR", raising=False)
    monkeypatch.delenv("AI_DEV_COMMUNITY_TELEMETRY_DATA_DIR", raising=False)

    # Darwin
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    cfg_dir = get_user_config_dir()
    data_dir = get_user_data_dir()
    assert "Application Support" in str(cfg_dir)
    assert "Application Support" in str(data_dir)

    # Linux with XDG
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "custom_xdg"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "custom_data"))
    cfg_dir_linux = get_user_config_dir()
    data_dir_linux = get_user_data_dir()
    assert "custom_xdg" in str(cfg_dir_linux)
    assert "custom_data" in str(data_dir_linux)

    # Linux without XDG (fallback)
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    assert ".config" in str(get_user_config_dir())
    assert ".local" in str(get_user_data_dir())


def test_config_corrupted_file_recovery(tmp_path: Path) -> None:
    cfg_path = get_user_config_dir() / CONFIG_FILENAME
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text("{ corrupt json", encoding="utf-8")
    cfg = load_community_config()
    assert cfg.telemetry_level == "off"


def test_builder_with_complex_report(tmp_path: Path) -> None:
    # Create test directory with various language files
    (tmp_path / "main.py").write_text("print('hello')", encoding="utf-8")
    (tmp_path / "app.ts").write_text("console.log('hi')", encoding="utf-8")
    (tmp_path / "lib.rs").write_text("fn main() {}", encoding="utf-8")
    (tmp_path / "style.css").write_text("body {}", encoding="utf-8")

    langs = detect_language_families(tmp_path)
    assert "python" in langs
    assert "typescript" in langs
    assert "rust" in langs

    fb, sb = compute_repo_buckets(tmp_path)
    assert fb in {"1-50", "51-200"}
    assert sb in {"<1MB", "1-10MB"}

    # Compute buckets on non-existent path
    assert compute_repo_buckets(tmp_path / "nonexistent") == ("unknown", "unknown")
    assert detect_language_families(tmp_path / "nonexistent") == []

    # Build report with rich metrics
    report = Report(command="check", project_root=tmp_path)
    report.status = "warning"
    report.issues.append(Issue("warning", "Budget warning", code="TOKEN_BUDGET_EXCEEDED"))
    report.summary = {
        "client": "claude",
        "model": "claude-3-5-haiku",
        "task_kind": "bugfix",
        "token_accounting": {
            "categories": {
                "source": {"tokens": 500},
                "diff": {"tokens": 100},
            }
        },
        "receipt": {
            "original_context_chars": 2000,
            "delivered_context_chars": 800,
        },
        "budget": {"max_chars": 4000},
        "character_budget": {"chars_avoided": 1200},
        "selected_files": [
            {"path": "main.py", "reason_code": "ENTRYPOINT"},
            {"path": "app.ts", "reason_code": "DEPENDENCY"},
        ],
        "rejected_files": [
            {"path": "lib.rs", "reason_code": "UNRELATED"},
        ],
        "retrieval": {"reason_code": "explicit_includes"},
        "input_tokens": 600,
        "cached_input_tokens": 200,
        "output_tokens": 100,
        "reasoning_tokens": 20,
        "total_tokens": 700,
        "performance": {
            "stages_seconds": {
                "scan": 0.015,
                "check": 0.085,
            }
        },
        "cache": {"hit": True},
        "task_complete": True,
    }

    payload = build_community_payload("research", report=report, project_root=tmp_path)
    assert payload["command_name"] == "check"
    assert payload["command_category"] == "quality"
    assert payload["command_outcome"] == "partial"  # warning maps to partial
    assert payload["reason_code"] == "TOKEN_BUDGET_EXCEEDED"
    assert payload["ai_client"] == "claude"
    assert payload["model"] == "claude-3-5-haiku"
    assert payload["task_kind"] == "bugfix"
    assert payload["context_candidate_tokens"] == 600
    assert payload["context_delivered_tokens"] == 200
    assert payload["context_budget"] == 1000
    assert payload["files_considered"] == 3
    assert payload["files_selected"] == 2
    assert payload["files_omitted"] == 1
    assert payload["retrieval_reason_code"] == "explicit_includes"
    assert payload["selection_reason_codes"] == ["DEPENDENCY", "ENTRYPOINT"]
    assert payload["input_tokens"] == 600
    assert payload["local_overhead_seconds"] == 0.1
    assert payload["task_outcome"] == "success"
    assert payload["validation_result"] == "failed"  # warning status

    # Invalid telemetry level in builder
    with pytest.raises(ValueError, match="Unsupported telemetry level"):
        build_community_payload("super_secret")


def test_queue_edge_cases(tmp_path: Path) -> None:
    # Enqueue oversized payload
    oversized = build_community_payload("basic", sample=True)
    oversized["reason_code"] = "X" * (MAX_PAYLOAD_BYTES + 100)
    with pytest.raises(ValueError, match="exceeds limit"):
        enqueue_event(oversized)

    # Clear empty queue
    assert clear_queue() == 0

    # Prune empty queue
    assert prune_queue() == 0

    # Remove nonexistent event
    remove_event(tmp_path / "nonexistent.json")


def test_transport_edge_cases() -> None:
    with pytest.raises(ValueError, match="Endpoint URL is empty"):
        validate_endpoint_url("")

    with pytest.raises(ValueError, match="Invalid URL scheme"):
        validate_endpoint_url("ftp://server.example.com/events")

    # Send with empty endpoint
    res = send_event("", {"foo": "bar"})
    assert not res.success
    assert "empty" in res.message

    # Send with un-serializable payload
    res_unserializable = send_event("http://127.0.0.1:8000/events", {"bad": object()})
    assert not res_unserializable.success
    assert "failed" in res_unserializable.message

    # Send with oversized payload
    oversized = {"data": "X" * (MAX_PAYLOAD_BYTES + 10)}
    res = send_event("http://127.0.0.1:8000/events", oversized)
    assert not res.success
    assert "exceeds" in res.message

    # Send with HTTPError 400 (non-retryable) and 500 (retryable)
    from urllib.error import HTTPError
    err400 = HTTPError("http://127.0.0.1:8000/events", 400, "Bad Request", {}, None)  # type: ignore[arg-type]
    with patch("urllib.request.urlopen", side_effect=err400):
        r400 = send_event("http://127.0.0.1:8000/events", {"test": 1}, retries=1)
        assert not r400.success
        assert r400.status_code == 400
        assert not r400.retryable

    err500 = HTTPError("http://127.0.0.1:8000/events", 500, "Server Error", {}, None)  # type: ignore[arg-type]
    with patch("urllib.request.urlopen", side_effect=err500):
        r500 = send_event("http://127.0.0.1:8000/events", {"test": 1}, retries=1)
        assert not r500.success
        assert r500.status_code == 500
        assert r500.retryable


def test_service_edge_cases(tmp_path: Path) -> None:
    # flush_telemetry when not configured
    save_community_config("basic", endpoint="")
    r_flush = flush_telemetry(tmp_path)
    assert r_flush.status == "warning"
    assert "No community telemetry endpoint configured" in r_flush.summary["message"]

    # flush_telemetry with empty queue
    save_community_config("basic", endpoint="https://collector.example.com/events")
    r_empty = flush_telemetry(tmp_path)
    assert r_empty.status == "success"
    assert "Queue is empty" in r_empty.summary["message"]

    # record_command_event avoids recording telemetry sharing commands
    sharing_report = Report(command="telemetry sharing preview", project_root=tmp_path)
    record_command_event(sharing_report, 0.1, tmp_path)
    assert queue_size() == 0

    # preview_telemetry with default basic fallback when off
    save_community_config("off")
    p_off = preview_telemetry(None, tmp_path)
    assert p_off.summary["telemetry_level"] == "BASIC"

    # task_failed coverage in builder
    fail_report = Report(command="check", project_root=tmp_path)
    fail_report.summary = {"task_failed": True}
    p_failed = build_community_payload("research", report=fail_report, project_root=tmp_path)
    assert p_failed["task_outcome"] == "failure"

    # flush_telemetry with failures
    p = build_community_payload("basic", sample=True)
    enqueue_event(p)
    mock_res_500 = UploadResult(success=False, status_code=500, message="Fail", retryable=True)
    with patch("ai_dev_tools.community.service.send_event", return_value=mock_res_500):
        r_all_failed = flush_telemetry(tmp_path)
        assert r_all_failed.status == "partial"
        assert "Failed to flush" in r_all_failed.summary["message"]

    # flush_telemetry with non-retryable failure (should remove event)
    mock_res_400 = UploadResult(success=False, status_code=400, message="Perm", retryable=False)
    with patch("ai_dev_tools.community.service.send_event", return_value=mock_res_400):
        flush_telemetry(tmp_path)
        assert queue_size() == 0

    # opportunistic flush error handling
    _opportunistic_flush("http://127.0.0.1:1/nonexistent")


def test_queue_list_and_prune_filters(tmp_path: Path) -> None:
    queue_dir = get_queue_dir()
    queue_dir.mkdir(parents=True, exist_ok=True)

    # Old tmp file
    old_tmp = queue_dir / "test.tmp"
    old_tmp.write_text("temp", encoding="utf-8")
    two_hours_ago = time.time() - 7200
    os.utime(old_tmp, (two_hours_ago, two_hours_ago))

    # Expired json file in list_queued_events
    expired_json = queue_dir / "expired.json"
    raw_event = json.dumps(build_community_payload("basic", sample=True))
    expired_json.write_text(raw_event, encoding="utf-8")
    ten_days_ago = time.time() - (10 * 86400)
    os.utime(expired_json, (ten_days_ago, ten_days_ago))

    # Oversized json file in list_queued_events
    oversized_json = queue_dir / "huge.json"
    oversized_json.write_bytes(b"X" * (MAX_PAYLOAD_BYTES + 100))

    # Non-dict json file in list_queued_events
    nondict_json = queue_dir / "nondict.json"
    nondict_json.write_text("[1, 2, 3]", encoding="utf-8")

    # Valid event
    p = build_community_payload("basic", sample=True)
    enqueue_event(p)

    events = list_queued_events()
    assert len(events) == 1

    prune_queue()
    assert not old_tmp.exists()
