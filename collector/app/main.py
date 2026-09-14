from __future__ import annotations

import ipaddress
import json
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Header, Request, Response, status
from fastapi.responses import JSONResponse

from collector.app.config import settings
from collector.app.rate_limit import TokenBucketRateLimiter
from collector.app.storage import check_db_health, init_db, insert_telemetry_event
from collector.app.validation import ValidationError, validate_ingest_payload

logger = logging.getLogger("collector.api")

rate_limiter = TokenBucketRateLimiter(
    rate_per_minute=settings.rate_limit_per_minute,
    max_burst=settings.rate_limit_per_minute,
    max_entries=settings.rate_limit_max_entries,
)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    # Production relies on explicit Alembic migrations; dev/test can auto-initialize
    if settings.environment != "production":
        init_db()
    logger.info("Collector initialized successfully in %s mode", settings.environment)
    yield
    logger.info("Collector shutting down")


app = FastAPI(
    title="ai-dev Community Telemetry Collector",
    version="1.0.0",
    docs_url=None,  # Disabled in production for minimal attack surface
    redoc_url=None,
    openapi_url=None,
    lifespan=lifespan,
)


@app.middleware("http")
async def security_headers_and_body_guard(request: Request, call_next: Any) -> Response:
    # 1. Fast transport-layer check if Content-Length header is present
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > settings.max_payload_bytes:
                return JSONResponse(
                    status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                    content={"status": "rejected", "error": "payload_too_large"},
                    headers={"X-Content-Type-Options": "nosniff"},
                )
        except ValueError:
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={"status": "rejected", "error": "validation_failed"},
                headers={"X-Content-Type-Options": "nosniff"},
            )

    response: Response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


def extract_transient_ip(request: Request) -> str:
    """
    Extract client IP for transient in-memory rate limiting only (never stored or logged).
    Strict trusted proxy model:
    - Default: ignores X-Forwarded-For and uses request.client.host.
    - Only trusts X-Forwarded-For if TRUST_PROXY_HEADERS=true and the immediate peer
      matches TRUSTED_PROXY_IPS networks.
    """
    peer_ip = request.client.host if request.client else "127.0.0.1"
    if not settings.trust_proxy_headers:
        return peer_ip

    if not settings.is_trusted_peer(peer_ip):
        return peer_ip

    forwarded = request.headers.get("x-forwarded-for")
    if not forwarded:
        return peer_ip

    # Leftmost token represents the originating client IP in a standard proxy chain
    candidate_ip = forwarded.split(",")[0].strip()
    if not candidate_ip:
        return peer_ip

    try:
        ipaddress.ip_address(candidate_ip)
        return candidate_ip
    except ValueError:
        # Malformed X-Forwarded-For -> fallback to peer IP
        return peer_ip


@app.get("/health")
async def health_check() -> JSONResponse:
    """Liveness probe: confirms process is alive and responsive."""
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={"status": "ok", "schema_version": 1},
    )


@app.get("/ready")
async def readiness_check() -> JSONResponse:
    """Readiness probe: confirms database is reachable."""
    is_healthy = check_db_health()
    if not is_healthy:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"status": "degraded", "error": "database_unavailable"},
        )
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={"status": "ready", "database": "connected"},
    )


@app.post("/v1/events")
async def ingest_event(
    request: Request,
    content_type: str | None = Header(None),
) -> JSONResponse:
    # 1. Content-Type verification
    if not content_type or "application/json" not in content_type.lower():
        return JSONResponse(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            content={"status": "rejected", "error": "unsupported_media_type"},
        )

    # 2. Transient in-memory rate limit check
    client_ip = extract_transient_ip(request)
    allowed, retry_after = rate_limiter.is_allowed(client_ip)
    if not allowed:
        return JSONResponse(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            content={"status": "rejected", "error": "rate_limited"},
            headers={"Retry-After": str(retry_after)},
        )

    # 3. Read body with streaming size check (hard protection against unbounded chunked payloads)
    chunks: list[bytes] = []
    total_bytes = 0
    async for chunk in request.stream():
        total_bytes += len(chunk)
        if total_bytes > settings.max_payload_bytes:
            return JSONResponse(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                content={"status": "rejected", "error": "payload_too_large"},
            )
        chunks.append(chunk)
    body = b"".join(chunks)

    # 4. Parse JSON
    try:
        payload = json.loads(body.decode("utf-8"))
    except Exception:
        logger.info("Rejected event: malformed_json")
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"status": "rejected", "error": "validation_failed"},
        )

    if not isinstance(payload, dict):
        logger.info("Rejected event: top-level payload not a JSON object")
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"status": "rejected", "error": "validation_failed"},
        )

    # 5. Fail-closed schema & invariant validation
    try:
        validate_ingest_payload(payload)
    except ValidationError as err:
        logger.info("Rejected event validation failure [%s]: %s", err.category, err.message)
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"status": "rejected", "error": "validation_failed"},
        )

    # 6. Atomic deduplication & persistence
    try:
        success, is_duplicate = insert_telemetry_event(payload)
    except Exception as exc:
        logger.error("Failed to store telemetry event: %s", exc)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"status": "error", "error": "storage_failed"},
        )

    if not success:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"status": "rejected", "error": "validation_failed"},
        )

    if is_duplicate:
        # Acknowledged as duplicate: HTTP 200 OK
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={"status": "accepted", "duplicate": True},
        )

    # Successfully ingested new event: HTTP 202 Accepted
    return JSONResponse(
        status_code=status.HTTP_202_ACCEPTED,
        content={"status": "accepted", "duplicate": False},
    )
