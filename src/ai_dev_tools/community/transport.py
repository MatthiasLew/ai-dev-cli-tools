from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

from ai_dev_tools import __version__
from ai_dev_tools.community.schema import COMMUNITY_SCHEMA_VERSION, MAX_PAYLOAD_BYTES

DEFAULT_TIMEOUT_SECONDS = 3.0
MAX_RETRIES = 2


@dataclass(slots=True, frozen=True)
class UploadResult:
    success: bool
    status_code: int = 0
    message: str = ""
    retryable: bool = False


def validate_endpoint_url(endpoint: str) -> None:
    if not endpoint:
        raise ValueError("Endpoint URL is empty")
    parsed = urllib.parse.urlparse(endpoint)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError(
            f"Invalid URL scheme '{parsed.scheme}': must be https (or http for localhost)"
        )

    # Allow http ONLY for local testing
    if parsed.scheme == "http":
        host = parsed.hostname or ""
        if host not in {"localhost", "127.0.0.1", "::1"}:
            raise ValueError(
                "Production telemetry endpoint must use HTTPS. "
                f"Insecure HTTP is only permitted for localhost (got '{endpoint}')"
            )


def send_event(
    endpoint: str,
    payload: dict[str, Any],
    *,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    retries: int = MAX_RETRIES,
) -> UploadResult:
    try:
        validate_endpoint_url(endpoint)
    except ValueError as exc:
        return UploadResult(success=False, status_code=0, message=str(exc), retryable=False)

    try:
        raw_body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        return UploadResult(
            success=False,
            status_code=0,
            message=f"Payload serialization failed: {exc}",
            retryable=False,
        )

    if len(raw_body) > MAX_PAYLOAD_BYTES:
        return UploadResult(
            success=False,
            status_code=0,
            message=f"Payload exceeds {MAX_PAYLOAD_BYTES} bytes limit",
            retryable=False,
        )

    headers = {
        "Content-Type": "application/json",
        "User-Agent": f"ai-dev/{__version__}",
        "X-Schema-Version": str(COMMUNITY_SCHEMA_VERSION),
    }

    last_error = ""
    for attempt in range(max(1, retries)):
        try:
            req = urllib.request.Request(
                endpoint,
                data=raw_body,
                headers=headers,
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=timeout) as response:
                status = response.status
                if 200 <= status < 300:
                    return UploadResult(success=True, status_code=status, message="Delivered")
                else:
                    return UploadResult(
                        success=False,
                        status_code=status,
                        message=f"Unexpected status: {status}",
                        retryable=500 <= status < 600,
                    )
        except urllib.error.HTTPError as exc:
            status = exc.code
            # 4xx client errors (e.g. 400 bad request, 403 forbidden) are not retryable
            # 5xx server errors or 429 rate limit may be retryable
            retryable = status == 429 or 500 <= status < 600
            last_error = f"HTTP {status}: {exc.reason}"
            if not retryable or attempt == retries - 1:
                return UploadResult(
                    success=False,
                    status_code=status,
                    message=last_error,
                    retryable=retryable,
                )
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_error = f"Network error: {exc}"
            if attempt == retries - 1:
                return UploadResult(
                    success=False,
                    status_code=0,
                    message=last_error,
                    retryable=True,
                )

        time.sleep(0.1 * (attempt + 1))

    return UploadResult(success=False, status_code=0, message=last_error, retryable=True)
