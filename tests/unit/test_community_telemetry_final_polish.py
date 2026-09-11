from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ai_dev_tools.community.builder import (
    build_community_payload,
    build_provider_usage_payload,
)
from ai_dev_tools.community.config import save_community_config
from ai_dev_tools.community.queue import (
    clear_queue,
    enqueue_event,
    list_queued_events,
    queue_size,
)
from ai_dev_tools.community.schema import (
    ALLOWED_MODELS,
    EVENT_TYPES,
    PROVIDER_USAGE_ORIGINS,
    validate_community_payload,
)
from ai_dev_tools.community.service import (
    enable_telemetry,
    start_background_autoflush,
    wait_for_autoflush,
)
from ai_dev_tools.community.transport import send_event
from ai_dev_tools.mcp_server import LocalMcpServer
from ai_dev_tools.telemetry import import_usage


@pytest.fixture(autouse=True)
def isolate_telemetry_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_dir = tmp_path / "config"
    data_dir = tmp_path / "data"
    monkeypatch.setenv("AI_DEV_COMMUNITY_TELEMETRY_CONFIG_DIR", str(config_dir))
    monkeypatch.setenv("AI_DEV_COMMUNITY_TELEMETRY_DATA_DIR", str(data_dir))
    monkeypatch.delenv("AI_DEV_COMMUNITY_TELEMETRY_ENDPOINT", raising=False)


def test_smuggling_attempts_rejected_fail_closed_zero_network() -> None:
    base = build_community_payload("research", sample=True)

    smuggling_cases: list[tuple[str, dict[str, object]]] = [
        ("invalid uuid4", {**base, "event_id": "not-a-uuid"}),
        ("python version secret leak", {**base, "python_version": "3.12.7 secret"}),
        ("non-hour timestamp", {**base, "timestamp_hour": "arbitrary text"}),
        (
            "unrecognized private model",
            {**base, "model": "private-company-model-customer-123"},
        ),
        ("negative input_tokens", {**base, "input_tokens": -1}),
        ("bool disguised as input_tokens", {**base, "input_tokens": True}),
        ("cache_hit_ratio > 1.0", {**base, "cache_hit_ratio": 1.5}),
        ("NaN duration_seconds", {**base, "duration_seconds": float("nan")}),
        ("infinity duration_seconds", {**base, "duration_seconds": float("inf")}),
        ("absurdly long ai_dev_version", {**base, "ai_dev_version": "v" * 100}),
        (
            "selection_reason_codes > 100 items",
            {**base, "selection_reason_codes": ["CHANGED_FILE"] * 105},
        ),
        ("invalid origin", {**base, "origin": "unauthorized_origin"}),
        (
            "token contradiction total < input",
            {**base, "input_tokens": 100, "output_tokens": 50, "total_tokens": 90},
        ),
        (
            "cached input exceeds input tokens",
            {**base, "input_tokens": 100, "cached_input_tokens": 150},
        ),
    ]

    for label, payload in smuggling_cases:
        with pytest.raises(ValueError) as excinfo:
            validate_community_payload(payload)
        assert len(str(excinfo.value)) > 0, f"Expected validation error for: {label}"

        with patch("urllib.request.urlopen") as mock_urlopen:
            result = send_event("https://collector.example.com/events", payload)
            assert not result.success, f"send_event succeeded for invalid payload: {label}"
            assert result.retryable is False
            assert "validation failed" in result.message.lower()
            mock_urlopen.assert_not_called()


def test_cli_import_vs_mcp_controlled_origin(tmp_path: Path) -> None:
    enable_telemetry("research")
    clear_queue()

    # 1. CLI telemetry import
    import_file = tmp_path / "imported_usage.json"
    import_file.write_text(
        json.dumps({
            "usage": {
                "input_tokens": 800,
                "input_tokens_details": {"cached_tokens": 200},
                "output_tokens": 150,
            },
            "model": "gpt-4o",
            "id": "secret-request-id-999",
        }),
        encoding="utf-8",
    )

    report = import_usage(tmp_path, import_file, client="cursor", format_name="openai")
    assert report.status == "success"

    queued = list_queued_events()
    assert len(queued) == 1
    _, event = queued[0]

    assert event["event_type"] == "provider_usage"
    assert event["origin"] == "import"
    assert event["command_name"] == "telemetry"
    assert event["model"] == "gpt-4o"
    assert event["input_tokens"] == 800
    assert event["cached_input_tokens"] == 200
    assert event["output_tokens"] == 150
    assert event["total_tokens"] == 950

    serialized = json.dumps(event)
    assert "secret-request-id-999" not in serialized
    assert "imported_usage.json" not in serialized
    assert "import:openai" not in serialized
    assert "request_id" not in event
    assert "source_id" not in event
    assert "phase" not in event
    assert "tool_name" not in event

    # 2. MCP record_usage
    clear_queue()
    server = LocalMcpServer(tmp_path)
    rpc_response = server.handle({
        "jsonrpc": "2.0",
        "id": "req-1",
        "method": "tools/call",
        "params": {
            "name": "record_usage",
            "arguments": {
                "client": "claude",
                "input_tokens": 1200,
                "cached_input_tokens": 400,
                "output_tokens": 300,
                "model": "claude-3-5-sonnet",
            },
        },
    })
    assert rpc_response is not None
    assert "result" in rpc_response
    assert rpc_response["result"]["isError"] is False
    assert rpc_response["result"]["structuredContent"]["status"] == "success"

    queued = list_queued_events()
    assert len(queued) == 1
    _, mcp_event = queued[0]

    assert mcp_event["event_type"] == "provider_usage"
    assert mcp_event["origin"] == "mcp"
    assert mcp_event["command_name"] == "mcp"
    assert mcp_event["model"] == "claude-3-5-sonnet"
    assert mcp_event["input_tokens"] == 1200
    assert mcp_event["cached_input_tokens"] == 400
    assert mcp_event["output_tokens"] == 300
    assert mcp_event["total_tokens"] == 1500


def test_mcp_delivery_workflow_autoflush(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    save_community_config("research", endpoint="http://127.0.0.1:9999/events")
    clear_queue()

    # Pre-populate a valid event in the queue
    valid_event = build_provider_usage_payload(
        client="cursor",
        model="gpt-4o",
        input_tokens=100,
        output_tokens=50,
        origin="mcp",
    )
    enqueue_event(valid_event)
    assert queue_size() == 1

    flushed_urls: list[str] = []

    def mock_send(
        endpoint: str,
        payload: dict[str, object],
        timeout: float = 2.0,
        retries: int = 1,
    ) -> MagicMock:
        flushed_urls.append(endpoint)
        mock_res = MagicMock()
        mock_res.success = True
        mock_res.retryable = False
        return mock_res

    monkeypatch.setattr("ai_dev_tools.community.service.send_event", mock_send)

    server = LocalMcpServer(tmp_path)
    # Record another usage
    server.handle({
        "jsonrpc": "2.0",
        "id": "req-2",
        "method": "tools/call",
        "params": {
            "name": "record_usage",
            "arguments": {
                "client": "cursor",
                "input_tokens": 200,
                "output_tokens": 100,
            },
        },
    })

    wait_for_autoflush(timeout=0.5)
    assert len(flushed_urls) >= 1
    assert "http://127.0.0.1:9999/events" in flushed_urls


def test_mcp_telemetry_off_and_missing_endpoint_guards(tmp_path: Path) -> None:
    # 1. Telemetry OFF -> 0 events queued, 0 autoflush
    save_community_config("off", endpoint="http://127.0.0.1:9999/events")
    clear_queue()

    server = LocalMcpServer(tmp_path)
    server.handle({
        "jsonrpc": "2.0",
        "id": "req-off",
        "method": "tools/call",
        "params": {
            "name": "record_usage",
            "arguments": {"client": "cursor", "input_tokens": 100, "output_tokens": 50},
        },
    })
    assert queue_size() == 0

    thread = start_background_autoflush()
    assert thread is None

    # 2. Endpoint missing -> events queued locally, but 0 flush
    save_community_config("research", endpoint="")
    clear_queue()

    server.handle({
        "jsonrpc": "2.0",
        "id": "req-no-endpoint",
        "method": "tools/call",
        "params": {
            "name": "record_usage",
            "arguments": {"client": "cursor", "input_tokens": 100, "output_tokens": 50},
        },
    })
    assert queue_size() == 1
    thread_missing = start_background_autoflush()
    assert thread_missing is None


def test_mcp_network_failure_isolation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    save_community_config("research", endpoint="http://127.0.0.1:9999/events")
    clear_queue()

    def failing_send(*args: object, **kwargs: object) -> MagicMock:
        raise OSError("Connection refused / simulated collector down")

    monkeypatch.setattr("ai_dev_tools.community.service.send_event", failing_send)

    server = LocalMcpServer(tmp_path)
    resp = server.handle({
        "jsonrpc": "2.0",
        "id": "req-fail-safe",
        "method": "tools/call",
        "params": {
            "name": "record_usage",
            "arguments": {"client": "cursor", "input_tokens": 50, "output_tokens": 25},
        },
    })
    assert resp is not None
    assert "result" in resp
    assert resp["result"]["isError"] is False
    assert resp["result"]["structuredContent"]["status"] == "success"

    wait_for_autoflush(timeout=0.1)


def test_docs_and_schema_contract_consistency() -> None:
    assert {"command_run", "provider_usage"} == EVENT_TYPES
    assert {"mcp", "import", "unknown"} == PROVIDER_USAGE_ORIGINS
    assert "claude-3-5-sonnet" in ALLOWED_MODELS
    assert "gpt-4o" in ALLOWED_MODELS
    assert "local" in ALLOWED_MODELS
    assert "other" in ALLOWED_MODELS
    assert "unknown" in ALLOWED_MODELS

    docs_dir = Path(__file__).resolve().parents[2] / "docs"
    community_doc = (docs_dir / "community-telemetry.md").read_text(encoding="utf-8")
    collector_doc = (docs_dir / "community-telemetry-collector.md").read_text(encoding="utf-8")

    for doc in (community_doc, collector_doc):
        assert "command_run" in doc
        assert "provider_usage" in doc
        assert "32 KB" in doc or "32,768" in doc
        assert "UUIDv4" in doc or "uuid4" in doc.lower()
        assert "completely anonymous" not in doc.lower()

    assert "wait_for_autoflush(0.05)" in community_doc or "50 ms" in community_doc
    assert "origin" in community_doc
