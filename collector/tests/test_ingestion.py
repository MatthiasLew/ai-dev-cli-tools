from __future__ import annotations

import json
from typing import Any

from fastapi.testclient import TestClient

from ai_dev_tools.community.builder import build_community_payload, build_provider_usage_payload


def test_health_endpoint(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "schema_version": 1}
    assert response.headers.get("X-Content-Type-Options") == "nosniff"


def test_ingest_valid_basic_command_run(client: TestClient) -> None:
    payload = build_community_payload("basic", sample=True)
    response = client.post("/v1/events", json=payload)
    assert response.status_code == 202
    assert response.json() == {"status": "accepted", "duplicate": False}
    assert response.headers.get("X-Content-Type-Options") == "nosniff"


def test_ingest_valid_research_command_run(client: TestClient) -> None:
    payload = build_community_payload("research", sample=True)
    response = client.post("/v1/events", json=payload)
    assert response.status_code == 202
    assert response.json() == {"status": "accepted", "duplicate": False}


def test_ingest_valid_provider_usage_mcp(client: TestClient) -> None:
    payload = build_provider_usage_payload(
        client="cursor",
        model="gpt-4o",
        input_tokens=1500,
        cached_input_tokens=500,
        output_tokens=300,
        origin="mcp",
    )
    response = client.post("/v1/events", json=payload)
    assert response.status_code == 202
    assert response.json() == {"status": "accepted", "duplicate": False}


def test_ingest_valid_provider_usage_import(client: TestClient) -> None:
    payload = build_provider_usage_payload(
        client="claude",
        model="claude-3-5-sonnet",
        input_tokens=2000,
        output_tokens=400,
        origin="import",
    )
    response = client.post("/v1/events", json=payload)
    assert response.status_code == 202
    assert response.json() == {"status": "accepted", "duplicate": False}


def test_ingest_invalid_content_type(client: TestClient) -> None:
    payload = build_community_payload("basic", sample=True)
    response = client.post(
        "/v1/events",
        content=json.dumps(payload),
        headers={"Content-Type": "text/plain"},
    )
    assert response.status_code == 415
    assert response.json() == {"status": "rejected", "error": "unsupported_media_type"}


def test_ingest_malformed_json(client: TestClient) -> None:
    response = client.post(
        "/v1/events",
        content="not-json{{{",
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 400
    assert response.json() == {"status": "rejected", "error": "validation_failed"}


def test_ingest_payload_too_large(client: TestClient) -> None:
    base = build_community_payload("research", sample=True)
    # Bloat selection_reason_codes or custom invalid oversized string
    large_payload = {**base, "selection_reason_codes": ["CHANGED_FILE"] * 3000}
    raw = json.dumps(large_payload).encode("utf-8")
    assert len(raw) > 32768

    response = client.post(
        "/v1/events",
        content=raw,
        headers={"Content-Type": "application/json", "Content-Length": str(len(raw))},
    )
    assert response.status_code == 413
    assert response.json() == {"status": "rejected", "error": "payload_too_large"}


def test_ingest_invalid_payload_cases(client: TestClient) -> None:
    valid_mcp = build_provider_usage_payload(
        client="cursor",
        model="gpt-4o",
        input_tokens=100,
        output_tokens=50,
        origin="mcp",
    )
    valid_cmd = build_community_payload("research", sample=True)

    cases: list[tuple[str, dict[str, Any]]] = [
        ("provider_usage with basic level", {**valid_mcp, "telemetry_level": "basic"}),
        ("provider_usage with origin=None", {**valid_mcp, "origin": None}),
        ("command_run research with origin='mcp'", {**valid_cmd, "origin": "mcp"}),
        ("invalid event_id not uuid", {**valid_cmd, "event_id": "bad-id"}),
        ("invalid schema_version 2", {**valid_cmd, "schema_version": 2}),
        ("extra unknown field injected", {**valid_cmd, "unknown_field": "leak"}),
        ("missing required field", {k: v for k, v in valid_cmd.items() if k != "os_family"}),
        ("arbitrary secret model", {**valid_mcp, "model": "internal-secret-model-v9"}),
        ("negative input_tokens", {**valid_mcp, "input_tokens": -50}),
        ("bool disguised as tokens", {**valid_mcp, "input_tokens": True}),
        ("NaN duration_seconds", {**valid_mcp, "duration_seconds": float("nan")}),
        ("Infinity duration_seconds", {**valid_mcp, "duration_seconds": float("inf")}),
        ("invalid non-UTC timestamp", {**valid_cmd, "timestamp_hour": "2026-09-14 12:00:00"}),
        ("invalid version format", {**valid_cmd, "ai_dev_version": "SecretBuildTag"}),
        (
            "mcp origin with mismatched command_name git",
            {**valid_mcp, "command_name": "git"},
        ),
        (
            "import origin with mismatched command_name scan",
            {**valid_mcp, "origin": "import", "command_name": "scan"},
        ),
        (
            "token contradiction total < input",
            {**valid_mcp, "input_tokens": 500, "output_tokens": 200, "total_tokens": 400},
        ),
        (
            "cached tokens exceed input tokens",
            {**valid_mcp, "input_tokens": 100, "cached_input_tokens": 300},
        ),
    ]

    for label, payload in cases:
        raw = json.dumps(payload, allow_nan=True)
        response = client.post(
            "/v1/events",
            content=raw,
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 400, (
            f"Expected 400 for case: {label}, got {response.status_code}"
        )
        assert response.json() == {"status": "rejected", "error": "validation_failed"}
