from __future__ import annotations

from fastapi.testclient import TestClient

from ai_dev_tools.community.builder import build_community_payload
from collector.app.rate_limit import TokenBucketRateLimiter


def test_token_bucket_deterministic_clock() -> None:
    current_time = 1000.0

    def mock_clock() -> float:
        return current_time

    # Rate: 10 requests per minute = 10 capacity, fill rate = 10/60 = 0.1667 tokens/sec
    limiter = TokenBucketRateLimiter(rate_per_minute=10, max_burst=10, clock=mock_clock)

    # First 10 requests must succeed
    for _ in range(10):
        allowed, retry_after = limiter.is_allowed("192.168.1.10")
        assert allowed is True
        assert retry_after == 0

    # 11th request must be rejected
    allowed, retry_after = limiter.is_allowed("192.168.1.10")
    assert allowed is False
    assert retry_after > 0

    # Advance clock by 30 seconds (5 tokens refilled)
    current_time += 30.0
    allowed, retry_after = limiter.is_allowed("192.168.1.10")
    assert allowed is True

    # Different IP should have independent capacity
    allowed_other, _ = limiter.is_allowed("10.0.0.1")
    assert allowed_other is True


def test_token_bucket_hard_memory_bound() -> None:
    # Hard bound: max_entries = 100
    limiter = TokenBucketRateLimiter(rate_per_minute=60, max_burst=60, max_entries=100)

    # Flood with 10,000 distinct IP keys
    for i in range(10_000):
        key = f"10.0.{i // 256}.{i % 256}"
        allowed, _ = limiter.is_allowed(key)
        assert allowed is True

    # Invariant: internal state must NEVER exceed max_entries
    assert len(limiter) <= 100
    assert len(limiter) == 100


def test_token_bucket_lru_and_stale_eviction() -> None:
    current_time = 1000.0
    limiter = TokenBucketRateLimiter(
        rate_per_minute=60,
        max_burst=60,
        max_entries=3,
        clock=lambda: current_time,
    )

    limiter.is_allowed("ip1")
    limiter.is_allowed("ip2")
    limiter.is_allowed("ip3")
    assert len(limiter) == 3

    # Access ip1 again to make it most recently used
    limiter.is_allowed("ip1")

    # Add ip4: ip2 (oldest LRU) should be evicted
    limiter.is_allowed("ip4")
    assert len(limiter) == 3
    # ip1, ip3, ip4 should be in buckets, ip2 should have been evicted
    assert "ip1" in limiter._buckets
    assert "ip3" in limiter._buckets
    assert "ip4" in limiter._buckets
    assert "ip2" not in limiter._buckets

    # Advance clock past 600s stale threshold
    current_time += 700.0
    # Insert new IP: triggers stale cleanup
    limiter.is_allowed("ip5")
    assert len(limiter) <= 3


def test_http_rate_limiting_integration(client: TestClient) -> None:
    # Temporarily set rate limiter with small burst
    simulated_time = 0.0
    limiter = TokenBucketRateLimiter(rate_per_minute=3, max_burst=3, clock=lambda: simulated_time)

    import collector.app.main as main_mod

    old_limiter = main_mod.rate_limiter
    main_mod.rate_limiter = limiter

    try:
        payload = build_community_payload("basic", sample=True)

        # 3 requests allowed
        for _ in range(3):
            resp = client.post(
                "/v1/events", json={**payload, "event_id": str(__import__("uuid").uuid4())}
            )
            assert resp.status_code == 202

        # 4th request rate limited
        resp_limited = client.post(
            "/v1/events", json={**payload, "event_id": str(__import__("uuid").uuid4())}
        )
        assert resp_limited.status_code == 429
        assert resp_limited.json() == {"status": "rejected", "error": "rate_limited"}
        assert "Retry-After" in resp_limited.headers

        # Advance simulated time by 60 seconds -> window refilled
        simulated_time += 60.0
        resp_after = client.post(
            "/v1/events", json={**payload, "event_id": str(__import__("uuid").uuid4())}
        )
        assert resp_after.status_code == 202

    finally:
        main_mod.rate_limiter = old_limiter
