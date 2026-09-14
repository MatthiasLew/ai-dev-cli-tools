# Community Telemetry Collector Specification & Architecture

This document defines the contract, schema validation rules, storage architecture, and operational guidelines for the production Community Telemetry Collector service (`collector/`) receiving events from `ai-dev`.

---

## 1. Collector Architecture

```mermaid
flowchart TD
    Client["ai-dev CLI / MCP (Client)"] -->|"POST /v1/events"| Proxy["Edge Reverse Proxy (Caddy / Nginx)"]
    Proxy -->|"HTTP (internal)"| FastAPIServer["FastAPI Collector (collector/app/main.py)"]
    FastAPIServer -->|"1. Check Content-Type & Size (<=32KB)"| Guard["Body Size & Header Guard"]
    Guard -->|"2. Token Bucket IP Check"| RateLimiter["In-Memory Rate Limiter"]
    RateLimiter -->|"3. Fail-Closed Validation"| Validator["Schema & Invariant Validator (validation.py)"]
    Validator -->|"4. Atomic Ingestion"| Storage["SQLAlchemy Storage (storage.py)"]
    Storage -->|"ON CONFLICT (event_id) DO NOTHING"| DB[("PostgreSQL 16+\n(telemetry_events table)")]
```

### Key Modules
- **`collector/app/main.py`**: FastAPI application exposing `POST /v1/events` and `GET /health`.
- **`collector/app/validation.py`**: Fail-closed schema and invariant validation (UUIDv4, UTC hour format, PEP 440 semver, exact key allowlist, token consistency, origin/event_type invariants).
- **`collector/app/models.py`**: SQLAlchemy declarative model (`TelemetryEvent`). Stores only allowlisted fields.
- **`collector/app/storage.py`**: Database session and atomic conflict handling.
- **`collector/app/rate_limit.py`**: Token bucket rate limiter keyed by transient client IP (memory bounded).
- **`collector/app/retention.py`**: 90-day retention cleanup utility.

---

## 2. HTTP Endpoints Contract

### `POST /v1/events`
Receives and stores a single telemetry event.

- **Method**: `POST`
- **Path**: `/v1/events`
- **Request Headers**:
  - `Content-Type: application/json`
  - `User-Agent: ai-dev/<version>`
  - `X-Schema-Version: 1`
- **Request Body**: JSON object matching `schema_version = 1` (maximum `32,768 bytes`).
- **Response Status Codes**:
  - `202 Accepted`: Payload accepted and stored (`{"status": "accepted", "duplicate": false}`).
  - `200 OK`: Payload accepted as duplicate (`{"status": "accepted", "duplicate": true}`). No new record is inserted.
  - `400 Bad Request`: Validation failure or malformed JSON (`{"status": "rejected", "error": "validation_failed", "detail": "<reason>"}`).
  - `413 Content Too Large`: Payload exceeds 32 KB (`{"status": "rejected", "error": "payload_too_large"}`).
  - `415 Unsupported Media Type`: Content-Type is not `application/json` (`{"status": "rejected", "error": "unsupported_media_type"}`).
  - `429 Too Many Requests`: Client exceeded rate limit (`{"status": "rejected", "error": "rate_limit_exceeded"}`). Includes `Retry-After` header.

### `GET /health`
Liveness and database connectivity probe.

- **Method**: `GET`
- **Path**: `/health`
- **Response**:
  - `200 OK`: `{"status": "ok", "schema_version": 1}`
  - `503 Service Unavailable`: `{"status": "degraded", "error": "database_unreachable"}`

---

## 3. Strict Fail-Closed Ingestion & Validation Rules

The collector operates with zero client trust. Every incoming payload is validated against these rules:

1. **Payload Size Limit**: Raw request body must be $\le 32,768$ bytes.
2. **No Schema Coercion**: Types must match strictly (e.g. `true` is never coerced to `1`, `"120"` is never coerced to `120`).
3. **Strict Top-Level Key Allowlist**:
   - `basic`: Exactly the 11 keys (`schema_version`, `event_id`, `event_type`, `timestamp_hour`, `os_family`, `python_version`, `ai_dev_version`, `command_name`, `command_category`, `command_outcome`, `duration_bucket`).
   - `research`: Only the 33 approved keys. Any unknown key causes immediate `400 Bad Request`.
4. **Format & Identity Constraints**:
   - `schema_version`: Must strictly equal integer `1`.
   - `event_id`: Valid UUIDv4 matching `^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$`.
   - `timestamp_hour`: Must strictly match UTC hour format `YYYY-MM-DDTHH:00:00Z` (minutes, seconds, and microseconds must be zero).
   - `python_version`: Major.minor string `^3\.\d+$` (e.g. `3.11`, `3.12`).
   - `ai_dev_version`: PEP 440 semver string starting with digits, length 1–32.
5. **Event Type Invariants**:
   - `command_run`: Allowed levels `basic` or `research`. When `research`, `origin` must strictly be `null`.
   - `provider_usage`: Allowed level `research` only. `origin` must be one of `{"mcp", "import", "unknown"}`. `command_name` must be `"mcp"` or `"telemetry"`, and `command_category` must be `"telemetry"`.
6. **Numeric Bounds & Token Consistency**:
   - Finite floats only: Reject `NaN`, `Infinity`, `-Infinity`.
   - `duration_seconds`: $0.0 \le x \le 604800.0$.
   - Tokens: $0 \le \text{tokens} \le 100,000,000$.
   - Token Consistency: `cached_input_tokens <= input_tokens` and `total_tokens >= input_tokens + output_tokens`.
   - Ratios: $0.0 \le \text{ratio} \le 1.0$.
   - Tool calls $\le 100,000$, file counts $\le 1,000,000$.
   - List limits: `selection_reason_codes` $\le 100$, `language_families` $\le 50$.

---

## 4. Database Schema

The database table `telemetry_events` stores only validated fields:

```sql
CREATE TABLE telemetry_events (
    event_id VARCHAR(36) PRIMARY KEY,
    received_at TIMESTAMP WITH TIME ZONE NOT NULL,
    schema_version INTEGER NOT NULL,
    telemetry_level VARCHAR(16) NOT NULL,
    event_type VARCHAR(32) NOT NULL,
    timestamp_hour TIMESTAMP WITH TIME ZONE NOT NULL,
    os_family VARCHAR(16) NOT NULL,
    python_version VARCHAR(16) NOT NULL,
    ai_dev_version VARCHAR(32) NOT NULL,
    command_name VARCHAR(64) NOT NULL,
    command_category VARCHAR(32) NOT NULL,
    command_outcome VARCHAR(16) NOT NULL,
    reason_code VARCHAR(64),
    duration_bucket VARCHAR(32) NOT NULL,
    duration_seconds DOUBLE PRECISION,
    cache_hit BOOLEAN,
    ai_client VARCHAR(32),
    model VARCHAR(64),
    input_tokens INTEGER,
    output_tokens INTEGER,
    total_tokens INTEGER,
    cached_input_tokens INTEGER,
    cache_read_input_tokens INTEGER,
    cache_creation_input_tokens INTEGER,
    tool_call_count INTEGER,
    task_kind VARCHAR(32),
    validation_result VARCHAR(16),
    task_outcome VARCHAR(16),
    repo_files_bucket VARCHAR(32),
    repo_size_bucket VARCHAR(32),
    retrieval_reason_code VARCHAR(64),
    selection_reason_codes TEXT,
    language_families TEXT,
    cache_hit_ratio DOUBLE PRECISION,
    semantic_cache_reuse DOUBLE PRECISION,
    local_overhead_seconds DOUBLE PRECISION,
    total_wall_time_seconds DOUBLE PRECISION,
    origin VARCHAR(16)
);

-- Indices for analytical aggregation and retention cleanup
CREATE INDEX idx_telemetry_events_timestamp_hour ON telemetry_events (timestamp_hour);
CREATE INDEX idx_telemetry_events_received_at ON telemetry_events (received_at);
CREATE INDEX idx_telemetry_events_command ON telemetry_events (command_name, command_category);
CREATE INDEX idx_telemetry_events_level ON telemetry_events (telemetry_level);
```

---

## 5. Deduplication & Idempotency

The collector relies on `event_id` as a primary key constraint:
- If a client retries due to network failure, the collector encounters an `IntegrityError` (or `ON CONFLICT DO NOTHING`).
- The duplicate event is discarded without modifying the existing row.
- The collector returns `200 OK` with `{"status": "accepted", "duplicate": true}`.
- The client sees a successful HTTP 200, cleans up its local spool, and does not retry further.

---

## 6. Retention Policy (90 Days)

Raw events older than 90 days are deleted using `collector/app/retention.py`:

```bash
# Dry run: check expired count without deleting
python -m app.retention --days 90 --dry-run

# Execute purge
python -m app.retention --days 90
```

Recommended automation: Schedule a daily cron job or systemd timer as detailed in [Deployment Guide](community-telemetry-deployment.md).

---

## 7. Analytical SQL Queries

Below are read-only analytical queries for deriving community insights without compromising privacy:

### 1. Daily Event Volume by Telemetry Level
```sql
SELECT
    DATE_TRUNC('day', timestamp_hour) AS day,
    telemetry_level,
    event_type,
    COUNT(*) AS event_count
FROM telemetry_events
GROUP BY 1, 2, 3
ORDER BY 1 DESC, 2;
```

### 2. Command Execution Latency (P50, P90, P95)
```sql
SELECT
    command_name,
    COUNT(*) AS run_count,
    ROUND(PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY duration_seconds)::NUMERIC, 3) AS p50_seconds,
    ROUND(PERCENTILE_CONT(0.90) WITHIN GROUP (ORDER BY duration_seconds)::NUMERIC, 3) AS p90_seconds,
    ROUND(PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY duration_seconds)::NUMERIC, 3) AS p95_seconds
FROM telemetry_events
WHERE duration_seconds IS NOT NULL
GROUP BY command_name
HAVING COUNT(*) >= 10
ORDER BY run_count DESC;
```

### 3. Token Consumption & Cache Efficiency
```sql
SELECT
    model,
    COUNT(*) AS session_count,
    SUM(input_tokens) AS total_input_tokens,
    SUM(output_tokens) AS total_output_tokens,
    SUM(cached_input_tokens) AS total_cached_tokens,
    ROUND(
        (SUM(cached_input_tokens)::NUMERIC / NULLIF(SUM(input_tokens), 0)::NUMERIC) * 100, 2
    ) AS cache_savings_pct
FROM telemetry_events
WHERE model IS NOT NULL AND input_tokens IS NOT NULL
GROUP BY model
ORDER BY session_count DESC;
```

### 4. Provider Usage Breakdown (MCP vs CLI Import)
```sql
SELECT
    origin,
    ai_client,
    model,
    COUNT(*) AS events_count,
    SUM(total_tokens) AS total_tokens_used
FROM telemetry_events
WHERE event_type = 'provider_usage'
GROUP BY origin, ai_client, model
ORDER BY events_count DESC;
```

---

## 8. Further Reading
- [Deployment Guide](community-telemetry-deployment.md) for Caddy / Nginx configurations and production setup.
- [Community Telemetry Specification](community-telemetry.md) for client privacy rules and telemetry level details.
