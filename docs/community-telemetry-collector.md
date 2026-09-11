# Community Telemetry Collector Specification

This document defines the contract, security requirements, and operational guidelines for the backend collector service receiving Community Telemetry events from `ai-dev`.

> [!NOTE]
> **Deployment Status**: Production collector still needs deployment.
> No production endpoint is currently hardcoded or hosted. For local development and testing, use the mock collector or override `AI_DEV_COMMUNITY_TELEMETRY_ENDPOINT`.

---

## 1. Collector Contract

### HTTP Endpoint
- **Method**: `POST`
- **Path**: e.g. `/telemetry/events` or root `/`
- **Content-Type**: `application/json`
- **Headers**:
  - `Content-Type: application/json`
  - `User-Agent: ai-dev/<version>`
  - `X-Schema-Version: 1`
- **Response**:
  - `200 OK` or `202 Accepted` on valid receipt: `{"status": "accepted"}`
  - `400 Bad Request` on invalid payload or unexpected schema: `{"status": "rejected", "error": "validation_failed"}`
  - `413 Payload Too Large` if payload exceeds size limit
  - `429 Too Many Requests` on rate limiting

---

## 2. Ingestion Constraints & Validation Rules

The collector must operate in a **strict fail-closed** manner. **Never trust client payloads without complete re-validation.**

1. **Payload Size & Body Parsing Limits**:
   - Maximum 32 KB (`32,768 bytes`) per event raw body.
   - Any request exceeding this limit must immediately return `413 Payload Too Large`.
   - Prevent unbounded JSON parsing memory allocation (limit parser buffer).

2. **No Schema Coercion**:
   - Do not coerce types (e.g. `true` must NOT be accepted as integer `1`, string `"120"` must NOT be accepted as integer `120`).
   - If a field is of an invalid type, return `400 Bad Request` with `validation_failed`.

3. **Strict Top-Level Key Allowlist**:
   - Payloads must contain only keys explicitly defined in `BASIC_PAYLOAD_KEYS` (for `basic`) or `RESEARCH_PAYLOAD_KEYS` (for `research`).
   - Any unknown, additional, or arbitrary top-level key must cause immediate rejection (`400 Bad Request`).

4. **Event Types**:
   - Supported values: `"command_run"` and `"provider_usage"`.
   - Both event types adhere to the same versioned allowlist structure (`command_run` for CLI commands, `provider_usage` for MCP / CLI import token sessions).

5. **Format & Identity Constraints**:
   - `schema_version`: Must strictly equal `1` (integer).
   - `event_id`: Must be a valid UUIDv4 string (`^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$`).
   - `timestamp_hour`: Must strictly match UTC hour format `YYYY-MM-DDTHH:00:00Z` (minutes, seconds, microseconds must be zero).
   - `python_version`: Must strictly match major.minor pattern `^3\.\d+$` (e.g. `3.11`, `3.12`, `3.14`).
   - `ai_dev_version`: PEP 440 / semver string starting with digits (`^\d+\.\d+(?:\.\d+)?(?:(?:a|b|rc|alpha|beta|dev|post)\d*|\.(?:dev|post)\d*|-(?:a|b|rc|alpha|beta|dev|post)\.?\d*)*(?:\+[a-zA-Z0-9._-]+)?$`), bounded between 1 and 32 characters.

6. **Event Type Invariants**:
   - `command_run`:
     - Allowed `telemetry_level`: `"basic"` or `"research"`.
     - In `research`, `origin` must strictly be `null` (`command_run` cannot pretend to be `provider_usage`).
   - `provider_usage`:
     - Allowed `telemetry_level`: `"research"` only. Any `provider_usage` with `telemetry_level="basic"` must be rejected (`400 Bad Request`).
     - `origin`: Must NOT be `null`. Must be one of `{"mcp", "import", "unknown"}`.
     - `command_name`: Must be `"mcp"` (for `"mcp"` or `"unknown"`) or `"telemetry"` (for `"import"`).
     - `command_category`: Must strictly be `"telemetry"`.

7. **Closed Enums**:
   - `telemetry_level`: `"basic"` or `"research"`.
   - `os_family`: `"windows"`, `"linux"`, `"macos"`, `"other"`.
   - `command_name`: closed set (`"check"`, `"scan"`, `"mcp"`, `"telemetry"`, etc.).
   - `command_category`: `"analysis"`, `"execution"`, `"quality"`, `"context"`, `"benchmark"`, `"telemetry"`, `"agent"`, `"runtime"`, `"other"`.
   - `command_outcome`: `"success"`, `"partial"`, `"failure"`.
   - `reason_code`: `null` or from `KNOWN_REASON_CODES`.
   - `duration_bucket`: `"<100ms"`, `"100ms-500ms"`, `"500ms-1s"`, `"1s-5s"`, `"5s-30s"`, `"30s-120s"`, `"120s+"`, `"unknown"`.
   - `ai_client`: `"codex"`, `"claude"`, `"cursor"`, `"gemini"`, `"other"`, `"unknown"`.
   - `model`: public known model, `"local"`, `"other"`, or `"unknown"`. Reject arbitrary model names!
   - `task_kind`: `"bugfix"`, `"feature"`, `"refactor"`, `"test"`, `"documentation"`, `"performance"`, `"security"`, `"investigation"`, `"other"`, `"unknown"`.
   - `validation_result`: `"passed"`, `"failed"`, `"unknown"`.
   - `task_outcome`: `"success"`, `"failure"`, `"unknown"`.
   - `repo_files_bucket`: `"1-50"`, `"51-200"`, `"201-1000"`, `"1001-5000"`, `"5000+"`, `"unknown"`.
   - `repo_size_bucket`: `"<1MB"`, `"1-10MB"`, `"10-50MB"`, `"50-250MB"`, `"250MB+"`, `"unknown"`.
   - `retrieval_reason_code`: `null` or from `RETRIEVAL_REASONS`.
   - `selection_reason_codes`: `null` or list of up to 100 codes, each strictly from `SELECTION_REASON_CODES`.
   - `language_families`: list of up to 50 items, each strictly from `KNOWN_LANGUAGES`.
   - `origin`: `null` (commands) or `"mcp"`, `"import"`, `"unknown"` (provider usage).

8. **Numeric Bounds & Token Consistency**:
   - `duration_seconds`: `null` or finite float `0.0 <= x <= 604800.0` (reject `NaN`, `inf`, and boolean types).
   - `cache_hit`: `null` or boolean.
   - Tokens (`input_tokens`, `output_tokens`, `total_tokens`, etc.): `null` or integer `0 <= x <= 100_000_000`.
   - Counts (`tool_call_count` `<= 100_000`; `files_considered`, `files_selected`, `files_omitted` `<= 1_000_000`).
   - Ratios (`cache_hit_ratio`, `semantic_cache_reuse`): `null` or finite float `0.0 <= x <= 1.0`.
   - Overheads (`local_overhead_seconds` `<= 86400.0`, `total_wall_time_seconds` `<= 604800.0`).
   - Consistency check: `cached_input_tokens <= input_tokens`, `total_tokens >= input_tokens + output_tokens`.

9. **Rate Limiting**:
   - Enforce IP-based token bucket or leaky bucket rate limiting (e.g., max 60 requests per minute per IP address).
   - In case of abuse, return `429 Too Many Requests` with a `Retry-After` header.

10. **Deduplication & Idempotency**:
   - The delivery model is **at-least-once / best-effort delivery with `event_id` available for deduplication**. Network retries after a lost connection or dropped ACK can deliver duplicates.
   - The collector MUST use `event_id` as a deduplication key.
   - When receiving an `event_id` that already exists in the recent deduplication index:
     - Do NOT re-insert or double-count the payload.
     - Return `200 OK` (or `202 Accepted`) so the client marks the event as delivered and stops retrying.
   - `event_id` MUST NOT be used for user tracking or cross-event profiling; it exists solely for idempotency.
   - Retention of the deduplication index must align with raw event retention (90 days).

---

## 3. Privacy & Data Handling Guarantees

1. **No Raw IP Logging**:
   - The application collector must not store client IP addresses in database tables or long-term storage.
   - Reverse proxies (e.g. Nginx, Cloudflare) should configure access logs to truncate or hash IP addresses (e.g. subnet masking `/24` for IPv4, `/48` for IPv6) or disable access logs completely for the telemetry path.
2. **No User Identification or Fingerprinting**:
   - Do not attempt to correlate events by IP address or TCP timestamps.
   - Do not perform browser/system fingerprinting.
   - Do not link events across sessions.
3. **No External Enrichment**:
   - Do not enrich events using commercial tracking databases, geo-IP lookup providers, or advertising networks.
4. **Data Retention Policy**:
   - Raw individual events should have a retention limit of 90 days.
   - After 90 days, events should be aggregated into statistical distributions (e.g., histograms, percentiles) and raw events permanently deleted.

---

## 4. Development & Mock Collector

For integration tests or local development, a lightweight HTTP server can serve as a mock collector:

```python
import json
from http.server import BaseHTTPRequestHandler, HTTPServer

class MockCollector(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        event = json.loads(body)
        print(f"Received event {event.get('event_id')} [{event.get('telemetry_level')}]: {event.get('command_name')}")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"status": "accepted"}')

if __name__ == "__main__":
    server = HTTPServer(("127.0.0.1", 8080), MockCollector)
    print("Mock collector running on http://127.0.0.1:8080 ...")
    server.serve_forever()
```

To test against the local mock collector:
```bash
ai-dev telemetry sharing enable basic
export AI_DEV_COMMUNITY_TELEMETRY_ENDPOINT="http://127.0.0.1:8080/events"
ai-dev telemetry sharing flush
```
