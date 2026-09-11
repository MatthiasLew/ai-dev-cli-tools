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

## 2. Ingestion Constraints & Validation

1. **Payload Size Limit**: Maximum 32 KB (`32,768 bytes`) per event.
2. **Strict Schema Validation**:
   - Payloads must conform exactly to `schema_version = 1`.
   - Unknown or arbitrary top-level fields must be strictly rejected with HTTP 400.
   - Enums must be checked against known values (`os_family`, `ai_client`, `task_kind`, etc.).
   - Reject any payload containing keys not present in the allowlist.
3. **Rate Limiting**:
   - Enforce IP-based token bucket or leaky bucket rate limiting (e.g., max 60 requests per minute per IP address).
   - In case of abuse, return `429 Too Many Requests` with a `Retry-After` header.

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
