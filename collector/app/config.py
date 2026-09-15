from __future__ import annotations

import ipaddress
import os
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Settings:
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///./telemetry.db")
    rate_limit_per_minute: int = int(os.getenv("RATE_LIMIT_PER_MINUTE", "60"))
    rate_limit_max_entries: int = int(os.getenv("RATE_LIMIT_MAX_ENTRIES", "10000"))
    retention_days: int = int(os.getenv("RETENTION_DAYS", "90"))
    max_payload_bytes: int = int(os.getenv("MAX_PAYLOAD_BYTES", "32768"))
    environment: str = os.getenv("ENVIRONMENT", "development").lower()
    trust_proxy_headers: bool = os.getenv("TRUST_PROXY_HEADERS", "false").lower() in (
        "1",
        "true",
        "yes",
    )
    trusted_proxy_ips_raw: str = os.getenv("TRUSTED_PROXY_IPS", "127.0.0.1,::1")
    trusted_proxy_networks: tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...] = field(
        init=False
    )

    def __post_init__(self) -> None:
        self.validate()
        # Parse trusted proxy networks
        networks: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = []
        for item in self.trusted_proxy_ips_raw.split(","):
            cleaned = item.strip()
            if cleaned:
                try:
                    networks.append(ipaddress.ip_network(cleaned, strict=False))
                except ValueError as exc:
                    raise ValueError(f"Invalid trusted proxy IP/network: '{cleaned}'") from exc
        if self.trust_proxy_headers and not networks:
            raise ValueError("TRUST_PROXY_HEADERS is enabled but TRUSTED_PROXY_IPS is empty")
        object.__setattr__(self, "trusted_proxy_networks", tuple(networks))

    def validate(self) -> None:
        if self.rate_limit_per_minute < 1 or self.rate_limit_per_minute > 10_000:
            raise ValueError(
                f"RATE_LIMIT_PER_MINUTE must be between 1 and 10000, "
                f"got {self.rate_limit_per_minute}"
            )
        if self.rate_limit_max_entries < 100 or self.rate_limit_max_entries > 1_000_000:
            raise ValueError(
                f"RATE_LIMIT_MAX_ENTRIES must be between 100 and 1000000, "
                f"got {self.rate_limit_max_entries}"
            )
        if self.retention_days < 1 or self.retention_days > 3650:
            raise ValueError(
                f"RETENTION_DAYS must be between 1 and 3650, got {self.retention_days}"
            )
        if self.max_payload_bytes < 1024 or self.max_payload_bytes > 1_048_576:
            raise ValueError(
                f"MAX_PAYLOAD_BYTES must be between 1024 and 1048576, got {self.max_payload_bytes}"
            )
        if self.environment == "production" and self.database_url.startswith("sqlite"):
            raise ValueError(
                "Production environment requires PostgreSQL database_url, SQLite is not allowed"
            )

    def is_trusted_peer(self, peer_ip: str) -> bool:
        """Check if peer IP matches any configured trusted proxy network."""
        try:
            ip = ipaddress.ip_address(peer_ip.strip())
        except ValueError:
            return False
        return any(ip in net for net in self.trusted_proxy_networks)


settings = Settings()
