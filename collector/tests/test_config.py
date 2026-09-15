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
    with pytest.raises(ValueError, match="RATE_LIMIT_PER_MINUTE must be between"):
        Settings(rate_limit_per_minute=0)

    with pytest.raises(ValueError, match="RATE_LIMIT_PER_MINUTE must be between"):
        Settings(rate_limit_per_minute=-10)

    with pytest.raises(ValueError, match="RATE_LIMIT_PER_MINUTE must be between"):
        Settings(rate_limit_per_minute=10_001)

    # Valid bounds
    s1 = Settings(rate_limit_per_minute=1)
    assert s1.rate_limit_per_minute == 1
    s2 = Settings(rate_limit_per_minute=10_000)
    assert s2.rate_limit_per_minute == 10_000


def test_invalid_max_entries_rejected() -> None:
    with pytest.raises(ValueError, match="RATE_LIMIT_MAX_ENTRIES must be between"):
        Settings(rate_limit_max_entries=0)

    with pytest.raises(ValueError, match="RATE_LIMIT_MAX_ENTRIES must be between"):
        Settings(rate_limit_max_entries=99)

    with pytest.raises(ValueError, match="RATE_LIMIT_MAX_ENTRIES must be between"):
        Settings(rate_limit_max_entries=1_000_001)

    # Valid bounds
    s1 = Settings(rate_limit_max_entries=100)
    assert s1.rate_limit_max_entries == 100
    s2 = Settings(rate_limit_max_entries=1_000_000)
    assert s2.rate_limit_max_entries == 1_000_000


def test_invalid_retention_days_rejected() -> None:
    with pytest.raises(ValueError, match="RETENTION_DAYS must be between"):
        Settings(retention_days=0)

    with pytest.raises(ValueError, match="RETENTION_DAYS must be between"):
        Settings(retention_days=-5)

    with pytest.raises(ValueError, match="RETENTION_DAYS must be between"):
        Settings(retention_days=3651)

    # Valid bounds
    s1 = Settings(retention_days=1)
    assert s1.retention_days == 1
    s2 = Settings(retention_days=3650)
    assert s2.retention_days == 3650


def test_invalid_max_payload_bytes_rejected() -> None:
    with pytest.raises(ValueError, match="MAX_PAYLOAD_BYTES must be between"):
        Settings(max_payload_bytes=1023)

    with pytest.raises(ValueError, match="MAX_PAYLOAD_BYTES must be between"):
        Settings(max_payload_bytes=1_048_577)

    # Valid bounds
    s1 = Settings(max_payload_bytes=1024)
    assert s1.max_payload_bytes == 1024
    s2 = Settings(max_payload_bytes=1_048_576)
    assert s2.max_payload_bytes == 1_048_576


def test_trust_proxy_headers_requires_non_empty_trusted_ips() -> None:
    with pytest.raises(ValueError, match="TRUST_PROXY_HEADERS is enabled but TRUSTED_PROXY_IPS"):
        Settings(trust_proxy_headers=True, trusted_proxy_ips_raw="")

    with pytest.raises(ValueError, match="TRUST_PROXY_HEADERS is enabled but TRUSTED_PROXY_IPS"):
        Settings(trust_proxy_headers=True, trusted_proxy_ips_raw="   ,  ")


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
