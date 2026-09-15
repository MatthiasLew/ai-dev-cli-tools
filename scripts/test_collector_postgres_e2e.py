#!/usr/bin/env python3
"""
Full Docker + PostgreSQL Ingestion E2E Test Suite for Community Telemetry Collector.

Runs in CI against a live PostgreSQL 16 container and a running production Docker collector.
Can also be executed locally:
    python scripts/test_collector_postgres_e2e.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker

from ai_dev_tools.community.builder import build_community_payload
from ai_dev_tools.community.config import save_community_config
from ai_dev_tools.community.queue import clear_queue, enqueue_event, queue_size
from ai_dev_tools.community.service import flush_telemetry
from ai_dev_tools.mcp_server import LocalMcpServer
from ai_dev_tools.telemetry import import_usage
from collector.app.models import TelemetryEvent

# 1. Configuration & URLs
COLLECTOR_URL = os.getenv("COLLECTOR_URL", "http://127.0.0.1:8000").rstrip("/")
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg://telemetry_user:test_ci_password_123@localhost:5432/telemetry",
)
EVENTS_ENDPOINT = f"{COLLECTOR_URL}/v1/events"


def _http_request(
    method: str,
    url: str,
    payload: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[int, dict[str, Any]]:
    req_headers = headers.copy() if headers else {}
    body_bytes = None
    if payload is not None:
        body_bytes = json.dumps(payload).encode("utf-8")
        req_headers.setdefault("Content-Type", "application/json")

    req = urllib.request.Request(url, data=body_bytes, headers=req_headers, method=method)
    try:
        with urllib.request.urlopen(req) as resp:
            data = resp.read().decode("utf-8")
            return resp.status, json.loads(data) if data else {}
    except urllib.error.HTTPError as err:
        data = err.read().decode("utf-8")
        return err.code, json.loads(data) if data else {}


def main() -> int:
    tmp_dir = Path(tempfile.mkdtemp(prefix="ai_dev_e2e_"))
    os.environ["AI_DEV_COMMUNITY_TELEMETRY_CONFIG_DIR"] = str(tmp_dir / "client_config")
    os.environ["AI_DEV_COMMUNITY_TELEMETRY_DATA_DIR"] = str(tmp_dir / "client_data")

    print("[*] Starting Collector + PostgreSQL Ingestion E2E Test Suite")
    print(f"[*] Collector Endpoint: {EVENTS_ENDPOINT}")
    clean_db = DATABASE_URL.split("@")[-1] if "@" in DATABASE_URL else DATABASE_URL
    print(f"[*] Database URL: {clean_db}")

    # Set up DB connection & session factory
    engine = create_engine(DATABASE_URL)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    # --------------------------------------------------------------------------
    # Step 1: Health & Readiness Probes
    # --------------------------------------------------------------------------
    print("\n[Step 1] Verifying /health and /ready endpoints...")
    status, body = _http_request("GET", f"{COLLECTOR_URL}/health")
    assert status == 200, f"/health returned status {status}: {body}"
    assert body.get("status") == "ok", f"Unexpected /health body: {body}"
    print("  -> /health (liveness): 200 OK")

    status, body = _http_request("GET", f"{COLLECTOR_URL}/ready")
    assert status == 200, f"/ready returned status {status}: {body}"
    assert body.get("status") == "ready", f"Unexpected /ready body: {body}"
    assert body.get("database") == "connected", f"Database not connected in /ready: {body}"
    print("  -> /ready (readiness with DB check): 200 OK")

    # --------------------------------------------------------------------------
    # Step 2: Ingest Valid BASIC Event
    # --------------------------------------------------------------------------
    print("\n[Step 2] Ingesting valid BASIC event...")
    basic_payload = build_community_payload("basic", sample=True)
    basic_id = basic_payload["event_id"]

    status, body = _http_request("POST", EVENTS_ENDPOINT, payload=basic_payload)
    assert status == 202, f"Expected 202 Accepted, got {status}: {body}"
    assert body == {"status": "accepted", "duplicate": False}, f"Unexpected body: {body}"
    print(f"  -> Successfully accepted basic event (event_id={basic_id})")

    # Verify directly in PostgreSQL
    with session_factory() as session:
        stored = session.get(TelemetryEvent, basic_id)
        assert stored is not None, f"Event {basic_id} not found in PostgreSQL!"
        assert stored.event_type == "command_run"
        assert stored.telemetry_level == "basic"
        assert stored.command_name == basic_payload["command_name"]
        assert stored.received_at is not None
    print("  -> Verified in PostgreSQL: 1 record present with expected schema.")

    # --------------------------------------------------------------------------
    # Step 3: Duplicate BASIC Event (Idempotency)
    # --------------------------------------------------------------------------
    print("\n[Step 3] Submitting duplicate BASIC event...")
    status, body = _http_request("POST", EVENTS_ENDPOINT, payload=basic_payload)
    assert status == 200, f"Expected 200 OK for duplicate, got {status}: {body}"
    assert body == {"status": "accepted", "duplicate": True}, f"Unexpected body: {body}"
    print("  -> Duplicate successfully acknowledged as duplicate=true")

    with session_factory() as session:
        stmt = (
            select(text("COUNT(*)"))
            .select_from(TelemetryEvent)
            .where(TelemetryEvent.event_id == basic_id)
        )
        count = session.scalar(stmt)
        assert count == 1, f"Expected exactly 1 row for {basic_id}, got {count}!"
    print("  -> Verified in PostgreSQL: row count is still exactly 1.")

    # --------------------------------------------------------------------------
    # Step 4: Invalid Payload / Forbidden Field
    # --------------------------------------------------------------------------
    print("\n[Step 4] Submitting payload with forbidden field ('prompt': 'secret')...")
    invalid_payload = build_community_payload("basic", sample=True)
    invalid_id = invalid_payload["event_id"]
    invalid_payload["prompt"] = "super_secret_user_prompt"

    status, body = _http_request("POST", EVENTS_ENDPOINT, payload=invalid_payload)
    assert status == 400, f"Expected 400 Bad Request, got {status}: {body}"
    assert body == {"status": "rejected", "error": "validation_failed"}, f"Unexpected body: {body}"
    print("  -> Correctly rejected with 400 validation_failed")

    with session_factory() as session:
        stored = session.get(TelemetryEvent, invalid_id)
        assert stored is None, f"Invalid event {invalid_id} was unexpectedly saved to DB!"
    print("  -> Verified in PostgreSQL: zero records created for invalid payload.")

    # --------------------------------------------------------------------------
    # Step 5: Research provider_usage Event
    # --------------------------------------------------------------------------
    print("\n[Step 5] Ingesting valid RESEARCH provider_usage event...")
    research_payload = {
        "schema_version": 1,
        "event_id": "b0000000-0000-4000-8000-000000000002",
        "event_type": "provider_usage",
        "telemetry_level": "research",
        "timestamp_hour": "2026-09-14T20:00:00Z",
        "os_family": "linux",
        "python_version": "3.13",
        "ai_dev_version": "1.2.2",
        "command_name": "mcp",
        "command_category": "telemetry",
        "command_outcome": "success",
        "duration_bucket": "0_to_1s",
        "origin": "mcp",
        "ai_client": "claude",
        "model": "claude-3-5-sonnet",
        "input_tokens": 1200,
        "cached_input_tokens": 400,
        "output_tokens": 300,
        "total_tokens": 1500,
        "tool_call_count": 5,
    }
    research_id = research_payload["event_id"]

    status, body = _http_request("POST", EVENTS_ENDPOINT, payload=research_payload)
    assert status == 202, f"Expected 202 Accepted, got {status}: {body}"
    assert body == {"status": "accepted", "duplicate": False}, f"Unexpected body: {body}"
    print(f"  -> Accepted research provider_usage event (event_id={research_id})")

    with session_factory() as session:
        stored = session.get(TelemetryEvent, research_id)
        assert stored is not None, f"Event {research_id} not found in DB!"
        assert stored.event_type == "provider_usage"
        assert stored.origin == "mcp"
        assert stored.model == "claude-3-5-sonnet"
        assert stored.input_tokens == 1200
        assert stored.cached_input_tokens == 400
        assert stored.output_tokens == 300
        assert stored.total_tokens == 1500
        assert stored.tool_call_count == 5
    print("  -> Verified in PostgreSQL: provider_usage fields stored accurately.")

    # --------------------------------------------------------------------------
    # Step 6: Duplicate Research provider_usage Retry
    # --------------------------------------------------------------------------
    print("\n[Step 6] Submitting duplicate research provider_usage event...")
    status, body = _http_request("POST", EVENTS_ENDPOINT, payload=research_payload)
    assert status == 200, f"Expected 200 OK for duplicate, got {status}: {body}"
    assert body == {"status": "accepted", "duplicate": True}
    with session_factory() as session:
        stmt = (
            select(text("COUNT(*)"))
            .select_from(TelemetryEvent)
            .where(TelemetryEvent.event_id == research_id)
        )
        count = session.scalar(stmt)
        assert count == 1, f"Expected 1 row for {research_id}, got {count}"
    print("  -> Verified in PostgreSQL: row count is still exactly 1.")

    # --------------------------------------------------------------------------
    # Step 7: Client Library BASIC -> Docker Collector -> PostgreSQL
    # --------------------------------------------------------------------------
    print("\n[Step 7] Testing Client Library (BASIC) -> Docker Collector -> PostgreSQL...")
    save_community_config("basic", endpoint=EVENTS_ENDPOINT)
    clear_queue()
    assert queue_size() == 0

    client_basic_event = build_community_payload("basic", sample=True)
    client_basic_id = client_basic_event["event_id"]
    enqueue_event(client_basic_event)
    assert queue_size() == 1

    report = flush_telemetry()
    assert report.status == "success", f"Flush failed: {report}"
    assert report.summary.get("delivered") == 1, f"Expected delivered=1: {report.summary}"
    assert queue_size() == 0
    print("  -> Client flush successful, queue is empty.")

    with session_factory() as session:
        stored = session.get(TelemetryEvent, client_basic_id)
        assert stored is not None, f"Client basic event {client_basic_id} not found in DB!"
    print(f"  -> Verified client basic event in PostgreSQL (event_id={client_basic_id}).")

    # --------------------------------------------------------------------------
    # Step 8: Client Library RESEARCH (MCP & Import) -> Docker Collector -> PostgreSQL
    # --------------------------------------------------------------------------
    print("\n[Step 8] Testing Client Library (RESEARCH MCP) -> Docker Collector -> PostgreSQL...")
    save_community_config("research", endpoint=EVENTS_ENDPOINT)
    clear_queue()

    # MCP Usage Record
    mcp_server = LocalMcpServer()
    rpc_res = mcp_server._handle_tool_call(
        {
            "jsonrpc": "2.0",
            "id": "req-mcp-e2e-pg",
            "method": "tools/call",
            "params": {
                "name": "record_usage",
                "arguments": {
                    "client": "claude",
                    "model": "claude-3-5-sonnet",
                    "input_tokens": 2000,
                    "cached_input_tokens": 800,
                    "output_tokens": 450,
                },
            },
        }
    )
    assert rpc_res is not None
    assert rpc_res.get("result", {}).get("structuredContent", {}).get("status") == "success"

    report_mcp = flush_telemetry()
    assert report_mcp.status == "success", f"MCP flush failed: {report_mcp}"
    assert queue_size() == 0

    with session_factory() as session:
        mcp_events = list(
            session.scalars(
                select(TelemetryEvent).where(
                    TelemetryEvent.event_type == "provider_usage",
                    TelemetryEvent.origin == "mcp",
                    TelemetryEvent.input_tokens == 2000,
                )
            ).all()
        )
        assert len(mcp_events) >= 1, "MCP provider_usage event not found in PostgreSQL!"
        ev = mcp_events[-1]
        assert ev.cached_input_tokens == 800
        assert ev.output_tokens == 450
        assert ev.total_tokens == 2450
    print("  -> Verified client MCP provider_usage event in PostgreSQL.")

    # CLI Import Usage Record
    print("\n[Step 9] Testing Client Library (RESEARCH Import) -> Collector -> PostgreSQL...")
    import_file = tmp_dir / "import_usage.json"
    import_file.write_text(
        json.dumps(
            {
                "usage": {"input_tokens": 1500, "output_tokens": 500},
                "model": "gpt-4o",
                "id": "secret-request-id-e2e-pg",
            }
        ),
        encoding="utf-8",
    )
    import_report = import_usage(tmp_dir, import_file, client="cursor", format_name="openai")
    assert import_report.status == "success", f"Import usage failed: {import_report}"

    report_import = flush_telemetry()
    assert report_import.status == "success", f"Import flush failed: {report_import}"
    assert queue_size() == 0

    with session_factory() as session:
        import_events = list(
            session.scalars(
                select(TelemetryEvent).where(
                    TelemetryEvent.event_type == "provider_usage",
                    TelemetryEvent.origin == "import",
                    TelemetryEvent.input_tokens == 1500,
                )
            ).all()
        )
        assert len(import_events) >= 1, "Import provider_usage event not found in PostgreSQL!"
        ev = import_events[-1]
        assert ev.model == "gpt-4o"
        assert ev.output_tokens == 500
        assert ev.total_tokens == 2000
    print("  -> Verified client Import provider_usage event in PostgreSQL.")

    # --------------------------------------------------------------------------
    # Step 10: Total Integrity & Row Count Verification
    # --------------------------------------------------------------------------
    print("\n[Step 10] Final Database Integrity & Column Audit...")
    with session_factory() as session:
        total_rows = session.scalar(select(text("COUNT(*)")).select_from(TelemetryEvent))
        print(f"  -> Total valid records in PostgreSQL: {total_rows}")
        assert total_rows is not None and total_rows >= 5, (
            f"Expected at least 5 events stored, got {total_rows}"
        )

    print("\n" + "=" * 70)
    print("ALL COLLECTOR + POSTGRESQL E2E CHECKS PASSED SUCCESSFULLY!")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
