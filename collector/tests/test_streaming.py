import json
from collections.abc import AsyncGenerator

import httpx
import pytest
from fastapi.testclient import TestClient

from ai_dev_tools.community.builder import build_community_payload
from collector.app.main import app


def test_payload_under_or_equal_to_limit_accepted(client: TestClient) -> None:
    payload = build_community_payload("basic", sample=True)
    body_bytes = json.dumps(payload).encode("utf-8")
    assert len(body_bytes) <= 32768

    resp = client.post(
        "/v1/events",
        content=body_bytes,
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 202
    assert resp.json() == {"status": "accepted", "duplicate": False}


def test_oversized_payload_rejected_by_transport_guard(client: TestClient) -> None:
    # 32769 bytes with explicit Content-Length header
    oversized_data = b"x" * 32769
    resp = client.post(
        "/v1/events",
        content=oversized_data,
        headers={
            "Content-Type": "application/json",
            "Content-Length": str(len(oversized_data)),
        },
    )
    assert resp.status_code == 413
    assert resp.json() == {"status": "rejected", "error": "payload_too_large"}


@pytest.mark.anyio
async def test_chunked_stream_without_content_length_exceeding_limit() -> None:
    # Emulate a chunked HTTP stream without Content-Length
    async def chunk_generator() -> AsyncGenerator[bytes, None]:
        for _ in range(35):
            yield b"a" * 1024  # 35 KB total > 32768 bytes

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as async_client:
        response = await async_client.post(
            "/v1/events",
            content=chunk_generator(),
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 413
        assert response.json() == {"status": "rejected", "error": "payload_too_large"}


@pytest.mark.anyio
async def test_spoofed_small_content_length_with_larger_stream() -> None:
    # Emulate request claiming small Content-Length but streaming > 32KB
    async def chunk_generator() -> AsyncGenerator[bytes, None]:
        for _ in range(35):
            yield b"b" * 1024

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as async_client:
        response = await async_client.post(
            "/v1/events",
            content=chunk_generator(),
            headers={
                "Content-Type": "application/json",
                # Note: ASGITransport uses generator content
            },
        )
        assert response.status_code == 413
        assert response.json() == {"status": "rejected", "error": "payload_too_large"}
