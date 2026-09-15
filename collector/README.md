# ai-dev Community Telemetry Collector

Lightweight, privacy-preserving, fail-closed production collector for `ai-dev` Community Telemetry (`schema_version = 1`).

---

## Key Privacy & Security Guarantees

1. **No User Tracking**: Does not assign, store, or generate user IDs, device fingerprints, or machine identifiers.
2. **No Persistent IP Logging**: IP addresses are used solely in transient in-memory token buckets for rate limiting and are never written to disk or database. Access logs must be disabled or sanitized at the edge reverse proxy.
3. **Strict Trusted Proxy Model & Single-IP Defense-in-Depth**: By default, `TRUST_PROXY_HEADERS=false` and client IP is extracted from the direct peer (`request.client.host`). `X-Forwarded-For` is only parsed if explicitly enabled and the connecting peer IP matches `TRUSTED_PROXY_IPS` networks. Furthermore, the reverse proxy must sanitize `X-Forwarded-For: $remote_addr;` and the collector strictly accepts only a single forwarded IP (any multi-value comma-separated header is rejected and falls back to peer IP).
4. **Hard-Bounded Rate Limiter**: Rate limiter state is backed by an `OrderedDict` with LRU and stale eviction, guaranteeing `len(_buckets) <= MAX_ENTRIES` (bounds: 100 to 1,000,000) under adversarial key generation.
5. **Streaming Body Limit**: Request body is read incrementally via streaming chunks. Payloads exceeding 32 KB (`32,768 bytes`) are aborted immediately with `413 Content Too Large` without full buffer allocation.
6. **Explicit Schema Migrations**: Managed by Alembic (`collector/alembic/`). Production startup never performs silent `create_all()` mutations.
7. **No Code, Prompts, or Paths**: Strict fail-closed schema validation automatically rejects any payload containing unknown keys, file paths, code snippets, or prompt text.
8. **Privacy-Safe Application Logging**: Application logs never record raw payload contents, field values, model names, paths, emails, client IPs, or database credentials. Validation errors log controlled category codes only, and storage failures log exception type names only.
9. **90-Day Raw Retention**: Automated retention script purges raw records older than 90 days based strictly on server `received_at` timestamp.
10. **Idempotent Ingestion**: `event_id` is an RFC 4122 UUIDv4 used exclusively as a deduplication primary key (`ON CONFLICT DO NOTHING`). Duplicate submissions return `200 OK` (`{"status": "accepted", "duplicate": true}`) without duplicate writes.

---

## API Endpoints

### 1. Liveness Probe: `GET /health`
Confirms the collector process is running and responsive.
- **Response** (`200 OK`):
  ```json
  {
    "status": "ok",
    "schema_version": 1
  }
  ```

### 2. Readiness Probe: `GET /ready`
Confirms connectivity to the backing database.
- **Response** (`200 OK`):
  ```json
  {
    "status": "ready",
    "database": "connected"
  }
  ```
- **Error Response** (`503 Service Unavailable`):
  ```json
  {
    "status": "degraded",
    "error": "database_unavailable"
  }
  ```

### 3. Ingest Event: `POST /v1/events`
- **Headers**:
  - `Content-Type: application/json`
  - `X-Content-Type-Options: nosniff` (applied to response)
- **Limits**: Body size $\le 32\text{ KB}$, 60 req/min per transient client IP.
- **Success Response** (`202 Accepted`):
  ```json
  {
    "status": "accepted",
    "duplicate": false
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
  - `413 Content Too Large`: `{"status": "rejected", "error": "payload_too_large"}`
  - `415 Unsupported Media Type`: `{"status": "rejected", "error": "unsupported_media_type"}`
  - `429 Too Many Requests`: `{"status": "rejected", "error": "rate_limited"}` (with `Retry-After` header)
  - `500 Server Error`: `{"status": "error", "error": "storage_failed"}`

---

## Local Development vs. Production

### Local Development (SQLite or Docker Compose)
In development, SQLite is permitted and the database can be initialized automatically or via Alembic:
```bash
# 1. Run migrations locally
python -m alembic -c collector/alembic.ini upgrade head

# 2. Run collector locally
uvicorn collector.app.main:app --host 127.0.0.1 --port 8000
```
Or with Docker Compose:
```bash
docker compose -f collector/docker-compose.yml up -d --build
```

### Production Deployment (PostgreSQL Required)
In production (`ENVIRONMENT=production`):
- `DATABASE_URL` **must** be a PostgreSQL connection string (`postgresql+psycopg://...`). SQLite will fail fast on startup.
- Migrations **must** be executed before launching the collector:
  ```bash
  alembic -c collector/alembic.ini upgrade head
  ```
- Set `TRUST_PROXY_HEADERS=true` only if deployed behind a verified reverse proxy (e.g. Caddy / Nginx) and configure `TRUSTED_PROXY_IPS`.

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
