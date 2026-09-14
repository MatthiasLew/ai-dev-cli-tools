# ai-dev Community Telemetry Collector

Lightweight, privacy-preserving, fail-closed production collector for `ai-dev` Community Telemetry (`schema_version = 1`).

---

## Key Privacy & Security Guarantees

1. **No User Tracking**: Does not assign, store, or generate user IDs, device fingerprints, or machine identifiers.
2. **No Persistent IP Logging**: IP addresses are used solely in transient in-memory token buckets for rate limiting and are never written to disk or database. Access logs should be disabled or sanitized.
3. **No Code, Prompts, or Paths**: Strict fail-closed schema validation automatically rejects any payload containing unknown keys, file paths, code snippets, or prompt text.
4. **90-Day Raw Retention**: Automated retention script removes events older than 90 days.
5. **Idempotent Ingestion**: `event_id` is an RFC 4122 UUIDv4 used exclusively as a deduplication key (`ON CONFLICT DO NOTHING`). Duplicate events return `200 OK` with `{"status": "accepted", "duplicate": true}` without double counting.

---

## API Endpoints

### 1. Health Check
- **Endpoint**: `GET /health`
- **Response** (`200 OK`):
  ```json
  {
    "status": "ok",
    "schema_version": 1
  }
  ```

### 2. Ingest Event
- **Endpoint**: `POST /v1/events`
- **Headers**:
  - `Content-Type: application/json`
  - `X-Content-Type-Options: nosniff` (applied to response)
- **Limits**: Body size $\le 32\text{ KB}$, 60 req/min per transient IP.
- **Success Response** (`202 Accepted`):
  ```json
  {
    "status": "accepted"
  }
  ```
- **Duplicate Response** (`200 OK`):
  ```json
  {
    "status": "accepted",
    "duplicate": true
  }
  ```
- **Error Responses**:
  - `400 Bad Request`: `{"status": "rejected", "error": "validation_failed"}`
  - `413 Payload Too Large`: `{"status": "rejected", "error": "payload_too_large"}`
  - `415 Unsupported Media Type`: `{"status": "rejected", "error": "unsupported_media_type"}`
  - `429 Too Many Requests`: `{"status": "rejected", "error": "rate_limited"}` (with `Retry-After` header)
  - `500/503 Service Error`: `{"status": "rejected", "error": "..."}`

---

## Running Locally

### Option A: Local Python with SQLite
```bash
cd collector
pip install -r requirements.txt
uvicorn collector.app.main:app --host 127.0.0.1 --port 8000
```

### Option B: Docker Compose with PostgreSQL
```bash
cd collector
docker compose up -d
```

---

## Running Retention Cleanup

To purge events older than 90 days:
```bash
python -m collector.app.retention --days 90
```
Dry run mode (preview without deletion):
```bash
python -m collector.app.retention --days 90 --dry-run
```
