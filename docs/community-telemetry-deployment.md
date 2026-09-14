# Community Telemetry Collector Deployment Guide

This guide describes how to deploy, configure, and operate the production backend collector for **ai-dev Community Telemetry** (`collector/`).

---

## Architecture Overview

```mermaid
flowchart LR
    Client["ai-dev CLI / MCP\n(Community Telemetry Client)"]
    Proxy["Reverse Proxy\n(Caddy / Nginx / Cloudflare)\n- TLS Termination\n- 32 KB Body Limit\n- IP Access Log Suppressed"]
    Collector["FastAPI Collector\n(collector/app/main.py)\n- Fail-closed Schema Validation\n- In-Memory Rate Limiting\n- Zero IP Storage"]
    DB[("PostgreSQL 16+\n(telemetry_events table)\n- PK Deduplication (event_id)\n- 90-Day Retention")]

    Client -- "POST /v1/events\n(max 32 KB JSON)" --> Proxy
    Proxy -- "HTTP (internal net)" --> Collector
    Collector -- "SQLAlchemy / psycopg" --> DB
```

### Core Tenets
1. **Privacy-Preserving**: No client IP addresses are ever stored in the database.
2. **Reverse Proxy Log Suppression**: Web server access logs for `/v1/events` must have client IPs discarded or disabled.
3. **Strict Trusted Proxying**: The collector ignores `X-Forwarded-For` unless `TRUST_PROXY_HEADERS=true` and the direct peer matches `TRUSTED_PROXY_IPS`.
4. **Streaming Chunk Body Limit**: Payloads exceeding 32 KB are aborted immediately without buffering.
5. **Fail-Closed Validation**: Payloads are strictly checked against schema invariants before database insertion.
6. **Idempotent Ingestion**: Duplicate submissions of the same `event_id` are acknowledged with `200 OK` (`duplicate: true`) without redundant database writes.
7. **Versioned Migrations**: Database schema changes are managed explicitly via Alembic (`collector/alembic/`).
8. **90-Day Retention**: Raw events are purged after 90 days via an automated retention task based on server `received_at`.

---

## Deployment Options

### Comparison

| Dimension | Option A: Managed PaaS (Render / Fly.io) | Option B: Self-Hosted VPS (Docker Compose + Caddy) |
|---|---|---|
| **Simplicity & Ops** | High (Managed buildpacks, zero OS maintenance) | Medium (Requires Docker, OS updates, systemd) |
| **Privacy & Log Control** | Medium (Platform access logs may log IPs unless stripped) | **Maximum** (Full control over Caddy/Nginx log discards) |
| **Cost** | ~$7–$15/mo (Free tier available for low volume) | **~$4–$6/mo** (Fixed cost e.g., Hetzner / OVH) |
| **Database Management** | Managed Postgres (Automated backups, HA) | Containerized Postgres or Managed DB |
| **Recommendation** | Ideal for zero-ops, prototyping, and rapid setup | **Recommended for Production** (Guarantees strict log privacy) |

---

## Option B: Self-Hosted VPS with Docker Compose & Caddy (Recommended)

This setup provides absolute control over server logs, ensuring zero IP tracking at the edge.

### 1. Prerequisites
- Linux VPS (Ubuntu 22.04 / 24.04 or Debian 12).
- Ports 80 and 443 open.
- Domain name pointed to the server's public IP (e.g. `telemetry.ai-dev.example.com`).
- Docker and Docker Compose installed.

### 2. Environment Configuration
On your server, create an application directory:
```bash
mkdir -p /opt/ai-dev-collector
cd /opt/ai-dev-collector
```

Copy the repository to `/opt/ai-dev-collector`.

Create `/opt/ai-dev-collector/.env`:
```env
POSTGRES_PASSWORD=GENERATE_A_VERY_STRONG_RANDOM_PASSWORD_HERE
DATABASE_URL=postgresql+psycopg://telemetry_user:GENERATE_A_VERY_STRONG_RANDOM_PASSWORD_HERE@db:5432/telemetry
RATE_LIMIT_PER_MINUTE=60
RATE_LIMIT_MAX_ENTRIES=10000
RETENTION_DAYS=90
MAX_PAYLOAD_BYTES=32768
ENVIRONMENT=production
TRUST_PROXY_HEADERS=true
TRUSTED_PROXY_IPS=127.0.0.1,::1,172.16.0.0/12
```

### 3. Caddy Reverse Proxy Configuration

Caddy provides automatic HTTPS (Let's Encrypt / ZeroSSL) and flexible logging directives. Configure Caddy to explicitly discard access logs for telemetry endpoints:

```caddy
# /etc/caddy/Caddyfile

telemetry.ai-dev.example.com {
    encode gzip zstd

    # Enforce request body size limit at edge
    request_body {
        max_size 32KiB
    }

    # Security headers
    header {
        X-Content-Type-Options nosniff
        X-Frame-Options DENY
        Referrer-Policy no-referrer
        Strict-Transport-Security "max-age=31536000; includeSubDomains; preload"
        -Server
    }

    # PRIVACY CRITICAL: Disable access logging for telemetry ingestion
    @telemetry path /v1/events
    handle @telemetry {
        log {
            output discard
        }
        reverse_proxy collector:8000 {
            transport http {
                read_timeout 10s
                write_timeout 10s
            }
        }
    }

    # Health & readiness probes
    @health path /health /ready
    handle @health {
        reverse_proxy collector:8000
    }

    # Reject all other paths
    handle {
        respond "Not Found" 404
    }
}
```

### 4. Alternative: Nginx Reverse Proxy Configuration

If using Nginx, configure the virtual host as follows:

```nginx
# /etc/nginx/sites-available/telemetry.ai-dev.example.com

server {
    listen 443 ssl http2;
    server_name telemetry.ai-dev.example.com;

    ssl_certificate /etc/letsencrypt/live/telemetry.ai-dev.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/telemetry.ai-dev.example.com/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;

    # Security headers
    add_header X-Content-Type-Options nosniff always;
    add_header X-Frame-Options DENY always;
    add_header Referrer-Policy no-referrer always;

    # Limit client request body size to 32 KB
    client_max_body_size 32k;
    client_body_buffer_size 32k;

    # PRIVACY CRITICAL: Completely disable access log for /v1/events
    location = /v1/events {
        access_log off;
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 10s;
        proxy_send_timeout 10s;
    }

    # Health & readiness probes
    location ~ ^/(health|ready)$ {
        access_log /var/log/nginx/health_access.log;
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
    }

    # Default deny
    location / {
        return 404;
    }
}
```

### 5. Applying Database Migrations & Starting Services

Before launching the collector, apply Alembic migrations to create the database schema:

```bash
docker compose -f collector/docker-compose.yml run --rm migrate
docker compose -f collector/docker-compose.yml up -d
```

Verify service status:
```bash
docker compose -f collector/docker-compose.yml ps
curl -i https://telemetry.ai-dev.example.com/health
curl -i https://telemetry.ai-dev.example.com/ready
```

Expected responses:
```json
HTTP/2 200
content-type: application/json
x-content-type-options: nosniff

{"status":"ok","schema_version":1}
```

And for `/ready`:
```json
HTTP/2 200
content-type: application/json
x-content-type-options: nosniff

{"status":"ready","database":"connected"}
```

---

## Option A: Managed PaaS Deployment (Render / Fly.io)

### Deploying to Render
1. **New Web Service**: Connect your GitHub repository.
2. **Root Directory**: Repository root.
3. **Environment**: `Docker` (Dockerfile Path: `collector/Dockerfile`).
4. **Environment Variables**:
   - `DATABASE_URL`: Connection string from Managed PostgreSQL instance.
   - `RATE_LIMIT_PER_MINUTE`: `60`
   - `RATE_LIMIT_MAX_ENTRIES`: `10000`
   - `RETENTION_DAYS`: `90`
   - `ENVIRONMENT`: `production`
   - `TRUST_PROXY_HEADERS`: `true`
5. **Health Check Path**: `/health`.
6. **Pre-Deploy Command**: `alembic -c collector/alembic.ini upgrade head`.

---

## Automated Retention Policy (90 Days)

The collector includes a retention cleanup module (`collector/app/retention.py`).

### Option 1: Host Cron Job
Add a daily cron job on the host machine to run the retention script inside the container:

```bash
# /etc/cron.d/ai-dev-telemetry-retention
0 3 * * * root docker exec ai-dev-collector python -m app.retention --days 90 >> /var/log/telemetry-retention.log 2>&1
```

### Option 2: Systemd Timer
Create a systemd service:
```ini
# /etc/systemd/system/telemetry-retention.service
[Unit]
Description=ai-dev Community Telemetry 90-Day Retention Cleanup
After=docker.service

[Service]
Type=oneshot
WorkingDirectory=/opt/ai-dev-collector
ExecStart=/usr/bin/docker compose -f collector/docker-compose.yml exec -T collector python -m app.retention --days 90
```

---

## Operational Verification & Checklist

Before pointing production clients to this endpoint, verify each item:

- [ ] **Liveness Probe**: `GET /health` returns `200 OK` with `{"status": "ok", "schema_version": 1}`.
- [ ] **Readiness Probe**: `GET /ready` returns `200 OK` with `{"status": "ready", "database": "connected"}`.
- [ ] **TLS Enforcement**: Non-HTTPS requests are redirected to HTTPS.
- [ ] **Access Log Privacy**: Confirmed reverse proxy does NOT write client IP addresses for requests to `/v1/events`.
- [ ] **Trusted Proxy**: Verified that direct requests with fake `X-Forwarded-For` are ignored.
- [ ] **Streaming Payload Limit**: A streamed request exceeding 32 KB returns `413 Content Too Large`.
- [ ] **Bounded Memory**: Rate limiter state does not exceed configured `RATE_LIMIT_MAX_ENTRIES`.
- [ ] **Fail-Closed Validation**: Sending an invalid schema or unexpected field returns `400 Bad Request`.
- [ ] **Deduplication**: Submitting the same `event_id` twice returns `200 OK` with `{"duplicate": true}` on the second call without creating a second record.
- [ ] **Alembic Migrations**: `python -m alembic -c collector/alembic.ini current` reports `head`.
- [ ] **Retention Job**: `python -m app.retention --dry-run` successfully connects and reports expired count based on `received_at`.
