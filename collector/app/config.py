from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///./telemetry.db")
    rate_limit_per_minute: int = int(os.getenv("RATE_LIMIT_PER_MINUTE", "60"))
    retention_days: int = int(os.getenv("RETENTION_DAYS", "90"))
    max_payload_bytes: int = int(os.getenv("MAX_PAYLOAD_BYTES", "32768"))
    environment: str = os.getenv("ENVIRONMENT", "development")


settings = Settings()
