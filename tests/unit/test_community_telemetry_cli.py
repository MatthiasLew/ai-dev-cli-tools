from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from threading import Thread
from typing import Any

import pytest

from ai_dev_tools.cli import main
from ai_dev_tools.community import enqueue_event
from ai_dev_tools.community.builder import build_community_payload
from ai_dev_tools.community.config import save_community_config
from ai_dev_tools.community.queue import queue_size


class MockCollectorHandler(BaseHTTPRequestHandler):
    received_payloads: list[dict[str, Any]] = []

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        data = json.loads(body.decode("utf-8"))
        MockCollectorHandler.received_payloads.append(data)
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"status":"accepted"}')

    def log_message(self, format: str, *args: Any) -> None:
        pass


@pytest.fixture(autouse=True)
def isolate_telemetry_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_dir = tmp_path / "config"
    data_dir = tmp_path / "data"
    monkeypatch.setenv("AI_DEV_COMMUNITY_TELEMETRY_CONFIG_DIR", str(config_dir))
    monkeypatch.setenv("AI_DEV_COMMUNITY_TELEMETRY_DATA_DIR", str(data_dir))
    monkeypatch.delenv("AI_DEV_COMMUNITY_TELEMETRY_ENDPOINT", raising=False)
    monkeypatch.setenv("AI_DEV_COMMUNITY_TELEMETRY_NO_AUTO_FLUSH", "1")
    MockCollectorHandler.received_payloads = []


def test_cli_telemetry_sharing_status(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main(["telemetry", "sharing", "status"])
    assert exit_code == 0
    captured = capsys.readouterr().out
    assert "Community telemetry: OFF" in captured
    assert "Endpoint: not configured" in captured
    assert "Queued events: 0" in captured


def test_cli_telemetry_sharing_enable_and_disable(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main(["telemetry", "sharing", "enable", "basic"])
    assert exit_code == 0
    captured = capsys.readouterr().out
    assert "COMMUNITY_TELEMETRY: BASIC" in captured

    exit_code = main(["telemetry", "sharing", "status"])
    assert exit_code == 0
    captured = capsys.readouterr().out
    assert "Community telemetry: BASIC" in captured

    exit_code = main(["telemetry", "sharing", "enable", "research"])
    assert exit_code == 0
    captured = capsys.readouterr().out
    assert "COMMUNITY_TELEMETRY: RESEARCH" in captured

    exit_code = main(["telemetry", "sharing", "disable"])
    assert exit_code == 0
    captured = capsys.readouterr().out
    assert "COMMUNITY_TELEMETRY: OFF" in captured


def test_cli_telemetry_sharing_preview_json(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main(["--json", "telemetry", "sharing", "preview", "--level", "basic"])
    assert exit_code == 0
    captured = capsys.readouterr().out
    payload = json.loads(captured)
    assert payload["telemetry_level"] == "basic"
    assert "event_id" in payload

    exit_code = main(["--json", "telemetry", "sharing", "preview", "--level", "research"])
    assert exit_code == 0
    captured = capsys.readouterr().out
    payload_research = json.loads(captured)
    assert payload_research["telemetry_level"] == "research"
    assert "ai_client" in payload_research


def test_cli_telemetry_sharing_flush_with_mock_collector(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Set up local HTTP mock server
    server = HTTPServer(("127.0.0.1", 0), MockCollectorHandler)
    port = server.server_port
    endpoint = f"http://127.0.0.1:{port}/events"

    server_thread = Thread(target=server.handle_request)
    server_thread.daemon = True
    server_thread.start()

    save_community_config("basic", endpoint=endpoint)
    payload = build_community_payload("basic", sample=True)
    enqueue_event(payload)
    assert queue_size() == 1

    exit_code = main(["telemetry", "sharing", "flush"])
    assert exit_code == 0
    captured = capsys.readouterr().out
    assert "Successfully flushed 1 event(s)" in captured
    assert queue_size() == 0

    assert len(MockCollectorHandler.received_payloads) == 1
    received = MockCollectorHandler.received_payloads[0]
    assert received["event_id"] == payload["event_id"]
    server.server_close()
