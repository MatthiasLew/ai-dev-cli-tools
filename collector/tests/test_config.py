from __future__ import annotations

import pytest

from collector.app.config import Settings


def test_default_settings_valid() -> None:
    s = Settings()
    assert s.rate_limit_per_minute > 0
    assert s.rate_limit_max_entries > 0
    assert s.retention_days > 0
    assert s.max_payload_bytes == 32768
    assert s.environment == "development"
    assert s.trust_proxy_headers is False
    assert len(s.trusted_proxy_networks) >= 1


def test_invalid_rate_limit_rejected() -> None:
    with pytest.raises(ValueError, match="RATE_LIMIT_PER_MINUTE must be positive"):
        Settings(rate_limit_per_minute=0)

    with pytest.raises(ValueError, match="RATE_LIMIT_PER_MINUTE must be positive"):
        Settings(rate_limit_per_minute=-10)


def test_invalid_max_entries_rejected() -> None:
    with pytest.raises(ValueError, match="RATE_LIMIT_MAX_ENTRIES must be positive"):
        Settings(rate_limit_max_entries=0)


def test_invalid_retention_days_rejected() -> None:
    with pytest.raises(ValueError, match="RETENTION_DAYS must be positive"):
        Settings(retention_days=0)


def test_invalid_max_payload_bytes_rejected() -> None:
    with pytest.raises(ValueError, match="MAX_PAYLOAD_BYTES must be between"):
        Settings(max_payload_bytes=500)

    with pytest.raises(ValueError, match="MAX_PAYLOAD_BYTES must be between"):
        Settings(max_payload_bytes=2_000_000)


def test_production_rejects_sqlite() -> None:
    with pytest.raises(ValueError, match="Production environment requires PostgreSQL"):
        Settings(
            environment="production",
            database_url="sqlite:///./prod.db",
        )


def test_production_accepts_postgresql() -> None:
    s = Settings(
        environment="production",
        database_url="postgresql+psycopg://user:pass@localhost:5432/telemetry",
    )
    assert s.environment == "production"
    assert s.database_url.startswith("postgresql")


def test_invalid_trusted_proxy_ip_rejected() -> None:
    with pytest.raises(ValueError, match="Invalid trusted proxy IP/network"):
        Settings(trusted_proxy_ips_raw="127.0.0.1,not-an-ip")


def test_trusted_peer_matching() -> None:
    s = Settings(trusted_proxy_ips_raw="127.0.0.1,10.0.0.0/8,::1")
    assert s.is_trusted_peer("127.0.0.1") is True
    assert s.is_trusted_peer("10.1.2.3") is True
    assert s.is_trusted_peer("::1") is True
    assert s.is_trusted_peer("192.168.1.1") is False
    assert s.is_trusted_peer("invalid-ip") is False
