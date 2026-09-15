# Reference Production Deployment Guide (GCE / VPS)

This directory contains safe, auditable production templates for deploying the **ai-dev Community Telemetry Collector** on a Linux VPS (e.g. Google Compute Engine, Hetzner, AWS EC2) behind Caddy with strict log discards.

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
cp deploy/gce/.env.example deploy/gce/.env
chmod 600 deploy/gce/.env

# Generate a strong 32-byte hex password (hex avoids URL encoding issues)
PASSWORD=$(openssl rand -hex 32)
sed -i "s/GENERATE_STRONG_RANDOM_PASSWORD_HERE/${PASSWORD}/g" deploy/gce/.env
```

Review `deploy/gce/.env` to ensure `POSTGRES_PASSWORD` and `DATABASE_URL` match your deployment settings.

### 2. Launch Production Containers

Run Docker Compose directly using the production template:

```bash
docker compose --env-file deploy/gce/.env -f deploy/gce/docker-compose.production.example.yml up -d --build
```

Verify that all containers are healthy:

```bash
docker compose --env-file deploy/gce/.env -f deploy/gce/docker-compose.production.example.yml ps
```

### 3. Configure Caddy

Copy `Caddyfile.example` to `/etc/caddy/Caddyfile`, replace `telemetry.example.com` with your actual domain or static IP DNS mapping (e.g. `35.209.177.185.sslip.io`), and reload Caddy:

```bash
sudo cp deploy/gce/Caddyfile.example /etc/caddy/Caddyfile
# Edit /etc/caddy/Caddyfile with your hostname
sudo systemctl reload caddy
```

### 4. Automated 90-Day Retention Job

Add a daily cron job on the host to purge raw events older than 90 days based on server `received_at`:

```bash
# /etc/cron.d/ai-dev-telemetry-retention
0 3 * * * root docker exec ai-dev-collector python -m collector.app.retention --days 90 >> /var/log/telemetry-retention.log 2>&1
```

### 5. Operational Verification

Test liveness and readiness probes through the public HTTPS endpoint:

```bash
curl -i https://telemetry.example.com/health
curl -i https://telemetry.example.com/ready
```
