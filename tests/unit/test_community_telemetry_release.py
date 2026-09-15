from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from ai_dev_tools.cli import main
from ai_dev_tools.community import clear_queue, queue_size
from ai_dev_tools.community.builder import build_community_payload, build_provider_usage_payload
from ai_dev_tools.community.config import (
    CONFIG_FILENAME,
    DEFAULT_COMMUNITY_ENDPOINT,
    DEFAULT_LEVEL,
    load_community_config,
    save_community_config,
)
from ai_dev_tools.community.schema import (
    COMMUNITY_SCHEMA_VERSION,
    validate_community_payload,
)
from ai_dev_tools.community.service import (
    disable_telemetry,
    enable_telemetry,
    get_telemetry_status,
    record_command_event,
)
from ai_dev_tools.models.report import Report


@pytest.fixture(autouse=True)
def isolate_telemetry_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_dir = tmp_path / "config"
    data_dir = tmp_path / "data"
    monkeypatch.setenv("AI_DEV_COMMUNITY_TELEMETRY_CONFIG_DIR", str(config_dir))
    monkeypatch.setenv("AI_DEV_COMMUNITY_TELEMETRY_DATA_DIR", str(data_dir))
    monkeypatch.delenv("AI_DEV_COMMUNITY_TELEMETRY_ENDPOINT", raising=False)
    monkeypatch.setenv("AI_DEV_COMMUNITY_TELEMETRY_NO_AUTO_FLUSH", "1")
    clear_queue()


# --------------------------------------------------------------------------
# Section 12: DEFAULT_COMMUNITY_ENDPOINT Contract
# --------------------------------------------------------------------------
def test_default_community_endpoint_contract() -> None:
    expected = "https://35.209.177.185.sslip.io/v1/events"
    assert expected == DEFAULT_COMMUNITY_ENDPOINT, (
        f"DEFAULT_COMMUNITY_ENDPOINT must match {expected!r}, "
        f"got {DEFAULT_COMMUNITY_ENDPOINT!r}"
    )
    assert DEFAULT_COMMUNITY_ENDPOINT.startswith("https://"), (
        "Production DEFAULT_COMMUNITY_ENDPOINT must enforce HTTPS"
    )
    assert not DEFAULT_COMMUNITY_ENDPOINT.startswith("http://"), (
        "Insecure HTTP is strictly forbidden for production telemetry endpoint"
    )
    assert DEFAULT_LEVEL == "off", "Default telemetry level MUST be 'off'"


# --------------------------------------------------------------------------
# Section 4: Legacy Config Migration & Precedence
# --------------------------------------------------------------------------
def test_case_a_no_config_uses_off_and_production_default() -> None:
    cfg = load_community_config()
    assert cfg.telemetry_level == "off"
    assert not cfg.is_enabled
    assert cfg.endpoint == DEFAULT_COMMUNITY_ENDPOINT


def test_case_b_legacy_empty_endpoint_uses_production_default(tmp_path: Path) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    legacy_file = config_dir / CONFIG_FILENAME
    legacy_file.write_text(
        json.dumps({"telemetry_level": "basic", "endpoint": ""}),
        encoding="utf-8",
    )
    cfg = load_community_config()
    assert cfg.telemetry_level == "basic"
    assert cfg.is_enabled
    # Empty string in legacy config must NOT block new package default endpoint
    assert cfg.endpoint == DEFAULT_COMMUNITY_ENDPOINT


def test_case_c_endpoint_override_custom_wins(tmp_path: Path) -> None:
    custom_url = "https://custom-telemetry.example.org/v1/events"
    save_community_config("basic", endpoint=custom_url)
    cfg = load_community_config()
    assert cfg.telemetry_level == "basic"
    assert cfg.endpoint == custom_url
    assert cfg.endpoint_override == custom_url


def test_case_d_env_var_wins_over_everything(monkeypatch: pytest.MonkeyPatch) -> None:
    env_url = "https://env-telemetry.example.net/v1/events"
    monkeypatch.setenv("AI_DEV_COMMUNITY_TELEMETRY_ENDPOINT", env_url)

    # Even with explicit custom override in file
    save_community_config("research", endpoint="https://override.example.com/events")
    cfg = load_community_config()
    assert cfg.endpoint == env_url


def test_case_e_disable_clears_queue_and_produces_no_network(tmp_path: Path) -> None:
    save_community_config("basic")
    # Simulate an event in queue
    event = build_community_payload("basic", sample=True)
    from ai_dev_tools.community.queue import enqueue_event
    enqueue_event(event)
    assert queue_size() == 1

    disable_res = disable_telemetry()
    assert disable_res.status == "success"
    cfg = load_community_config()
    assert cfg.telemetry_level == "off"
    assert not cfg.is_enabled
    assert queue_size() == 0

    with patch("urllib.request.urlopen") as mock_http:
        report = Report(command="scan", project_root=tmp_path).finish()
        record_command_event(report, 0.5, tmp_path)
        assert mock_http.call_count == 0
        assert queue_size() == 0


def test_case_f_enable_basic_without_endpoint_uses_production_default() -> None:
    res = enable_telemetry("basic")
    assert res.status == "success"
    cfg = load_community_config()
    assert cfg.telemetry_level == "basic"
    assert cfg.is_enabled
    assert cfg.endpoint_override is None
    assert cfg.endpoint == DEFAULT_COMMUNITY_ENDPOINT


def test_case_g_enable_research_without_endpoint_uses_production_default() -> None:
    res = enable_telemetry("research")
    assert res.status == "success"
    cfg = load_community_config()
    assert cfg.telemetry_level == "research"
    assert cfg.is_enabled
    assert cfg.endpoint_override is None
    assert cfg.endpoint == DEFAULT_COMMUNITY_ENDPOINT


# --------------------------------------------------------------------------
# Section 5: Default OFF Guarantees
# --------------------------------------------------------------------------
def test_fresh_install_zero_telemetry_guarantee(tmp_path: Path) -> None:
    status = get_telemetry_status()
    assert status.summary["community_telemetry"] == "OFF"
    assert status.summary["queued_events"] == 0

    cfg = load_community_config()
    assert cfg.telemetry_level == "off"
    assert not cfg.is_enabled

    with patch("urllib.request.urlopen") as mock_urlopen:
        # Run normal CLI command
        exit_code = main(["--project", str(tmp_path), "capabilities", "--json"])
        assert exit_code == 0
        assert mock_urlopen.call_count == 0
        assert queue_size() == 0


# --------------------------------------------------------------------------
# Section 13: Schema Version & Compatibility
# --------------------------------------------------------------------------
def test_schema_version_and_payload_compatibility() -> None:
    assert COMMUNITY_SCHEMA_VERSION == 1

    basic_payload = build_community_payload("basic", sample=True)
    assert basic_payload["schema_version"] == 1
    assert basic_payload["telemetry_level"] == "basic"
    validate_community_payload(basic_payload)

    research_payload = build_community_payload("research", sample=True)
    assert research_payload["schema_version"] == 1
    assert research_payload["telemetry_level"] == "research"
    validate_community_payload(research_payload)

    mcp_usage_payload = build_provider_usage_payload(
        client="claude",
        model="claude-3-5-sonnet",
        input_tokens=1000,
        cached_input_tokens=300,
        output_tokens=200,
        origin="mcp",
    )
    assert mcp_usage_payload["schema_version"] == 1
    assert mcp_usage_payload["telemetry_level"] == "research"
    assert mcp_usage_payload["event_type"] == "provider_usage"
    validate_community_payload(mcp_usage_payload)
