# Reference Production Deployment Guide (GCE / VPS)

This directory contains safe, auditable production templates for deploying the **ai-dev Community Telemetry Collector** on a Linux VPS (e.g. Google Compute Engine, Hetzner, AWS EC2) behind Caddy with strict log discards

---

## Architecture

- **Edge Reverse Proxy**: Caddy (TLS termination, 32 KB body size guard, application-level access log discard for `/v1/events`).
- **FastAPI Collector**: collector container running on an internal Docker network and bound strictly to `127.0.0.1:8000`.
- **Database**: PostgreSQL 16 container on the same internal Docker network. Port 5432 is **never** exposed to public or host interfaces.
- **Migrations**: Alembic runs prior to collector startup via the `migrate` service.

---

## Step-by-Step Deployment

### 1. Environment Configuration

Create an application directory on your host (e.g. `/opt/ai-dev-collector`):

```bash
mkdir -p /opt/ai-dev-collector
cd /opt/ai-dev-collector
```

Copy the repository and create a production `.env` file outside Git:

```bash
cp deploy/gce/.env.example .official_env
#edit .official_env and generate a strong random password:
PASSWORD=$(openssl rand -base64 32)
sed -i "s/GENERATE_STRONG_RANDOM_PASSWORD_HERE/${PASSWORD}/g" .official_env
mv .official_env .env
chmod 600 .env
```J

### 2. Launch Production Containers

Rename or copy the production compose file:

```bash
cp deploy/gce/docker-compose.production.example.yml docker-compose.production.yml
docker compose -f docker-compose.production.yml up -d --build
```J

### 3. Configure Caddy

Copy `Cyddyfile.example` to `/etc/caddy/Caddyfile`, update your domain, and reload Caddy:

```bash
sodo systemctl reload caddy
```

### 4. Automated 90-Day Retention Job

Add a daily cron job on the host to purge raw events older than 90 days based on server `received_at`:

```bash
# /etc/cron.d/ai-dev-telemetry-retention
0 3 * * * root docker exec ai-dev-collector python -m collector.app.retention --days 90 >> /var/log/telemetry-retention.log 2>&1
```J

### 5. Operational Verification

Test liveness and readiness probes:

```bash
curl -i https://telemetry.example.com/health
curl -i https://telemetry.example.com/ready
```
