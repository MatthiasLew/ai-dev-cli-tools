from __future__ import annotations

import json
import socket
import threading
import time
from collections.abc import Generator
from pathlib import Path

import pytest
import uvicorn
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from ai_dev_tools.community.builder import build_community_payload
from ai_dev_tools.community.config import save_community_config
from ai_dev_tools.community.queue import clear_queue, enqueue_event, queue_size
from ai_dev_tools.community.service import flush_telemetry
from ai_dev_tools.mcp_server import LocalMcpServer
from ai_dev_tools.telemetry import import_usage
from collector.app.main import app, rate_limiter
from collector.app.models import Base, TelemetryEvent


@pytest.fixture(scope="module")
def live_collector() -> Generator[tuple[str, sessionmaker[Session]], None, None]:
    """Spin up a real live uvicorn collector server on a free localhost port."""
    import tempfile

    import collector.app.storage as storage_mod

    temp_dir = tempfile.mkdtemp(prefix="ai_dev_collector_e2e_")
    db_file = Path(temp_dir) / "e2e_telemetry.db"
    test_engine = create_engine(f"sqlite:///{db_file}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=test_engine)
    test_factory = sessionmaker(bind=test_engine, autoflush=False, autocommit=False)

    old_engine = storage_mod.engine
    old_factory = storage_mod.SessionFactory
    storage_mod.engine = test_engine
    storage_mod.SessionFactory = test_factory

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()

    rate_limiter.reset()

    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    while not server.started:
        time.sleep(0.01)

    endpoint = f"http://127.0.0.1:{port}/v1/events"
    yield endpoint, test_factory

    server.should_exit = True
    thread.join(timeout=3.0)

    storage_mod.engine = old_engine
    storage_mod.SessionFactory = old_factory


@pytest.fixture(autouse=True)
def isolate_client_telemetry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_dir = tmp_path / "client_config"
    data_dir = tmp_path / "client_data"
    monkeypatch.setenv("AI_DEV_COMMUNITY_TELEMETRY_CONFIG_DIR", str(config_dir))
    monkeypatch.setenv("AI_DEV_COMMUNITY_TELEMETRY_DATA_DIR", str(data_dir))
    monkeypatch.delenv("AI_DEV_COMMUNITY_TELEMETRY_ENDPOINT", raising=False)
    clear_queue()


def test_client_collector_e2e_basic_command_flow(
    live_collector: tuple[str, sessionmaker[Session]],
) -> None:
    endpoint, session_factory = live_collector
    save_community_config("basic", endpoint=endpoint)
    assert queue_size() == 0

    # 1. Client builds and queues a basic event
    basic_event = build_community_payload("basic", sample=True)
    event_id = basic_event["event_id"]
    enqueue_event(basic_event)
    assert queue_size() == 1

    # 2. Client flushes telemetry to live collector
    report = flush_telemetry()
    assert report.status == "success"
    assert report.summary.get("delivered") == 1
    assert queue_size() == 0

    # 3. Verify event is stored in collector database
    with session_factory() as session:
        stored = session.get(TelemetryEvent, event_id)
        assert stored is not None
        assert stored.event_id == event_id
        assert stored.telemetry_level == "basic"
        assert stored.event_type == "command_run"
        assert stored.command_name == basic_event["command_name"]
        assert stored.ai_client is None
        assert stored.input_tokens is None


def test_client_collector_e2e_research_mcp_and_import(
    tmp_path: Path,
    live_collector: tuple[str, sessionmaker[Session]],
) -> None:
    endpoint, session_factory = live_collector
    save_community_config("research", endpoint=endpoint)
    clear_queue()

    # 1. MCP record_usage creates an event
    server = LocalMcpServer(tmp_path)
    rpc_res = server.handle(
        {
            "jsonrpc": "2.0",
            "id": "req-mcp-e2e",
            "method": "tools/call",
            "params": {
                "name": "record_usage",
                "arguments": {
                    "client": "claude",
                    "model": "claude-3-5-sonnet",
                    "input_tokens": 1500,
                    "cached_input_tokens": 500,
                    "output_tokens": 350,
                },
            },
        }
    )
    assert rpc_res is not None
    assert rpc_res.get("result", {}).get("structuredContent", {}).get("status") == "success"

    # 2. Flush to collector
    report_mcp = flush_telemetry()
    assert report_mcp.status == "success"
    assert queue_size() == 0

    with session_factory() as session:
        mcp_events = list(
            session.scalars(
                select(TelemetryEvent).where(
                    TelemetryEvent.event_type == "provider_usage",
                    TelemetryEvent.origin == "mcp",
                )
            ).all()
        )
        assert len(mcp_events) >= 1
        latest_mcp = mcp_events[-1]
        assert latest_mcp.command_name == "mcp"
        assert latest_mcp.model == "claude-3-5-sonnet"
        assert latest_mcp.input_tokens == 1500
        assert latest_mcp.cached_input_tokens == 500
        assert latest_mcp.output_tokens == 350
        assert latest_mcp.total_tokens == 1850

    # 3. CLI telemetry import
    import_file = tmp_path / "usage_data.json"
    import_file.write_text(
        json.dumps(
            {
                "usage": {
                    "input_tokens": 900,
                    "output_tokens": 200,
                },
                "model": "gpt-4o",
                "id": "secret-request-id-123",
            }
        ),
        encoding="utf-8",
    )
    import_report = import_usage(tmp_path, import_file, client="cursor", format_name="openai")
    assert import_report.status == "success"

    # 4. Flush to collector
    report_import = flush_telemetry()
    assert report_import.status == "success"
    assert queue_size() == 0

    with session_factory() as session:
        import_events = list(
            session.scalars(
                select(TelemetryEvent).where(
                    TelemetryEvent.event_type == "provider_usage",
                    TelemetryEvent.origin == "import",
                )
            ).all()
        )
        assert len(import_events) >= 1
        latest_import = import_events[-1]
        assert latest_import.command_name == "telemetry"
        assert latest_import.model == "gpt-4o"
        assert latest_import.input_tokens == 900
        assert latest_import.output_tokens == 200
        assert latest_import.total_tokens == 1100


def test_client_collector_e2e_dedup_and_retry(
    live_collector: tuple[str, sessionmaker[Session]],
) -> None:
    endpoint, session_factory = live_collector
    save_community_config("basic", endpoint=endpoint)
    clear_queue()

    # 1. Enqueue and flush first time
    event = build_community_payload("basic", sample=True)
    event_id = event["event_id"]
    enqueue_event(event)
    assert queue_size() == 1

    report1 = flush_telemetry()
    assert report1.status == "success"
    assert queue_size() == 0

    # Verify 1 record in DB
    with session_factory() as session:
        count1 = len(
            list(
                session.scalars(
                    select(TelemetryEvent).where(TelemetryEvent.event_id == event_id)
                ).all()
            )
        )
        assert count1 == 1

    # 2. Simulate client duplicate / retry: re-enqueue the exact same event
    enqueue_event(event)
    assert queue_size() == 1

    # 3. Flush again
    report2 = flush_telemetry()
    assert report2.status == "success"
    assert queue_size() == 0

    # Verify DB still contains exactly 1 row (no duplicate)
    with session_factory() as session:
        count2 = len(
            list(
                session.scalars(
                    select(TelemetryEvent).where(TelemetryEvent.event_id == event_id)
                ).all()
            )
        )
        assert count2 == 1
