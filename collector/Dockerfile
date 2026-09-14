# Multi-stage minimal production Dockerfile for Community Telemetry Collector
# Build context MUST be the repository root:
#   docker build -f collector/Dockerfile -t ai-dev-collector:latest .

FROM python:3.13-slim AS builder

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# 1. Install collector dependencies
COPY collector/requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# 2. Build and install ai-dev-cli-tools package for schema validation without external dev tools
COPY pyproject.toml README.md ./
COPY src/ ./src/
RUN pip install --no-cache-dir build hatchling && \
    python -m build --wheel --no-isolation --outdir /wheels . && \
    pip install --no-cache-dir --user --no-deps /wheels/*.whl


FROM python:3.13-slim AS runner

# Security: Create non-root user
RUN groupadd -r appuser && useradd -r -g appuser -d /app -s /sbin/nologin -c "Docker image user" appuser

WORKDIR /app

# Copy installed python dependencies from builder
COPY --from=builder /root/.local /home/appuser/.local
ENV PATH=/home/appuser/.local/bin:$PATH
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Copy application source & Alembic migrations
COPY collector/app/ /app/collector/app/
COPY collector/alembic/ /app/collector/alembic/
COPY collector/alembic.ini /app/collector/alembic.ini

# Set ownership to non-root user
RUN chown -R appuser:appuser /app

USER appuser

EXPOSE 8000

# Health check without curl dependency (probes liveness endpoint)
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

# Start uvicorn with access logging disabled (privacy preservation for client IPs)
CMD ["uvicorn", "collector.app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
