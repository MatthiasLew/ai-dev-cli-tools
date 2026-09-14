from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Header, Request, Response, status
from fastapi.responses import JSONResponse

from collector.app.config import settings
from collector.app.rate_limit import TokenBucketRateLimiter
from collector.app.storage import check_db_health, init_db, insert_telemetry_event
from collector.app.validation import ValidationError, validate_ingest_payload

# Configure minimal privacy-preserving application logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [collector] %(message)s",
)
logger = logging.getLogger("collector.app")

rate_limiter = TokenBucketRateLimiter(rate_per_minute=settings.rate_limit_per_minute)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Initialize DB schema on startup
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
    # 1. Enforce payload size limit at transport layer
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


def _extract_transient_ip(request: Request) -> str:
    """Extract client IP for transient in-memory rate limiting only (never stored or logged)."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        # Take the first untrusted client IP in the chain
        return forwarded.split(",")[0].strip()
    if request.client:
        return request.client.host
    return "127.0.0.1"


@app.get("/health")
async def health_check() -> JSONResponse:
    is_healthy = check_db_health()
    if not is_healthy:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"status": "degraded", "error": "database_unavailable"},
        )
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={"status": "ok", "schema_version": 1},
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
    client_ip = _extract_transient_ip(request)
    allowed, retry_after = rate_limiter.is_allowed(client_ip)
    if not allowed:
        return JSONResponse(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            content={"status": "rejected", "error": "rate_limited"},
            headers={"Retry-After": str(retry_after)},
        )

    # 3. Read body with strict size check
    body = await request.body()
    if len(body) > settings.max_payload_bytes:
        return JSONResponse(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            content={"status": "rejected", "error": "payload_too_large"},
        )

    # 4. Parse JSON
    try:
        payload = json.loads(body.decode("utf-8"))
    except Exception:
        logger.info("Rejected event: malformed_json")
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"status": "rejected", "error": "validation_failed"},
        )

    # 5. Strict Server-side Schema & Invariant Validation
    try:
        validated = validate_ingest_payload(payload)
    except ValidationError as exc:
        logger.info("Rejected event validation failure: %s", exc.category)
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"status": "rejected", "error": "validation_failed"},
        )
    except Exception:
        logger.info("Rejected event validation failure: unexpected_validation_error")
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"status": "rejected", "error": "validation_failed"},
        )

    # 6. Idempotent storage insert
    try:
        success, is_duplicate = insert_telemetry_event(validated)
    except Exception as exc:
        logger.error("Storage error during ingestion: %s", type(exc).__name__)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"status": "rejected", "error": "storage_error"},
        )

    if not success:
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"status": "rejected", "error": "storage_error"},
        )

    if is_duplicate:
        logger.info("Accepted event (duplicate)")
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={"status": "accepted", "duplicate": True},
        )

    logger.info("Accepted event (new)")
    return JSONResponse(
        status_code=status.HTTP_202_ACCEPTED,
        content={"status": "accepted"},
    )
