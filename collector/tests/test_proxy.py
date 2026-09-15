from __future__ import annotations

from typing import Any
from unittest.mock import patch

from starlette.datastructures import Address
from starlette.requests import Request

from collector.app.config import Settings
from collector.app.main import extract_transient_ip


def _make_request(
    client_host: str = "127.0.0.1",
    headers: dict[str, str] | None = None,
) -> Request:
    raw_headers = [
        (k.lower().encode("latin-1"), v.encode("latin-1")) for k, v in (headers or {}).items()
    ]
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/v1/events",
        "headers": raw_headers,
        "client": Address(client_host, 12345),
    }
    return Request(scope)


def test_default_config_ignores_spoofed_xff() -> None:
    # Default: trust_proxy_headers is False
    settings = Settings(trust_proxy_headers=False)
    with patch("collector.app.main.settings", settings):
        req = _make_request(
            client_host="203.0.113.195",
            headers={"X-Forwarded-For": "198.51.100.42"},
        )
        extracted = extract_transient_ip(req)
        # Must return the direct peer IP, ignoring the spoofed XFF header
        assert extracted == "203.0.113.195"


def test_trusted_proxy_uses_single_forwarded_client_ip() -> None:
    # Configured to trust proxy from 127.0.0.1
    settings = Settings(
        trust_proxy_headers=True,
        trusted_proxy_ips_raw="127.0.0.1,::1",
    )
    with patch("collector.app.main.settings", settings):
        req = _make_request(
            client_host="127.0.0.1",
            headers={"X-Forwarded-For": "198.51.100.42"},
        )
        extracted = extract_transient_ip(req)
        # Must extract the sanitized single forwarded client IP
        assert extracted == "198.51.100.42"


def test_trusted_proxy_rejects_multi_value_xff_fallback_to_peer() -> None:
    # Defense-in-depth: multi-value XFF chains are rejected to prevent spoofing
    settings = Settings(
        trust_proxy_headers=True,
        trusted_proxy_ips_raw="127.0.0.1,::1",
    )
    with patch("collector.app.main.settings", settings):
        req = _make_request(
            client_host="127.0.0.1",
            headers={"X-Forwarded-For": "8.8.8.8, 198.51.100.42"},
        )
        extracted = extract_transient_ip(req)
        # Must reject multi-IP and fallback to trusted peer IP
        assert extracted == "127.0.0.1"


def test_untrusted_peer_ignores_xff_even_if_proxy_headers_enabled() -> None:
    settings = Settings(
        trust_proxy_headers=True,
        trusted_proxy_ips_raw="10.0.0.0/8,127.0.0.1",
    )
    with patch("collector.app.main.settings", settings):
        # Peer comes from public IP outside the trusted network
        req = _make_request(
            client_host="192.168.1.50",
            headers={"X-Forwarded-For": "198.51.100.42"},
        )
        extracted = extract_transient_ip(req)
        # Must ignore XFF and use the peer IP directly
        assert extracted == "192.168.1.50"


def test_malformed_xff_falls_back_to_peer_ip() -> None:
    settings = Settings(
        trust_proxy_headers=True,
        trusted_proxy_ips_raw="127.0.0.1",
    )
    with patch("collector.app.main.settings", settings):
        # Header has invalid non-IP string
        req = _make_request(
            client_host="127.0.0.1",
            headers={"X-Forwarded-For": "not-an-ip-address"},
        )
        extracted = extract_transient_ip(req)
        assert extracted == "127.0.0.1"


def test_missing_client_in_scope_falls_back_to_default() -> None:
    settings = Settings(trust_proxy_headers=False)
    with patch("collector.app.main.settings", settings):
        scope: dict[str, Any] = {
            "type": "http",
            "method": "POST",
            "path": "/v1/events",
            "headers": [],
            "client": None,
        }
        req = Request(scope)
        extracted = extract_transient_ip(req)
        assert extracted == "127.0.0.1"
