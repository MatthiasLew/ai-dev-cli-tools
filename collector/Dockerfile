# Multi-stage minimal production Dockerfile for Community Telemetry Collector
FROM python:3.13-slim AS builder

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt


FROM python:3.13-slim AS runner

# Security: Create non-root user
RUN groupadd -r appuser && useradd -r -g appuser -d /app -s /sbin/nologin -c "Docker image user" appuser

WORKDIR /app

# Copy installed python dependencies from builder
COPY --from=builder /root/.local /home/appuser/.local
ENV PATH=/home/appuser/.local/bin:$PATH
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Copy application source
COPY app/ /app/collector/app/

# Set ownership to non-root user
RUN chown -R appuser:appuser /app

USER appuser

EXPOSE 8000

# Health check without curl dependency
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

# Start uvicorn with access logging disabled (privacy preservation for client IPs)
CMD ["uvicorn", "collector.app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
