from __future__ import annotations

import threading
import time
from collections.abc import Callable


class TokenBucketRateLimiter:
    """
    Thread-safe in-memory token bucket rate limiter.
    Transient keys (e.g. client IP) are held in memory only and never persisted.
    Supports injectable clock for deterministic unit testing.
    """

    def __init__(
        self,
        rate_per_minute: int = 60,
        max_burst: int = 60,
        clock: Callable[[], float] | None = None,
        max_entries: int = 10_000,
    ) -> None:
        self.rate_per_minute = max(1, rate_per_minute)
        self.capacity = float(max(1, max_burst))
        self.fill_rate = self.rate_per_minute / 60.0  # tokens per second
        self.clock = clock or time.monotonic
        self.max_entries = max_entries
        self._buckets: dict[str, tuple[float, float]] = {}  # key -> (tokens, last_time)
        self._lock = threading.Lock()

    def is_allowed(self, key: str) -> tuple[bool, int]:
        """
        Check if request for key is permitted under the rate limit.
        Returns:
            (allowed: bool, retry_after_seconds: int)
        """
        now = self.clock()
        with self._lock:
            # Memory bounded purge if table grows too large
            if len(self._buckets) > self.max_entries:
                stale_cutoff = now - 600.0  # 10 minutes inactive
                self._buckets = {k: v for k, v in self._buckets.items() if v[1] > stale_cutoff}

            if key not in self._buckets:
                # First request from this key: start with capacity - 1
                self._buckets[key] = (self.capacity - 1.0, now)
                return True, 0

            tokens, last_time = self._buckets[key]
            elapsed = max(0.0, now - last_time)
            refilled_tokens = min(self.capacity, tokens + (elapsed * self.fill_rate))

            if refilled_tokens >= 1.0:
                self._buckets[key] = (refilled_tokens - 1.0, now)
                return True, 0

            # Rate limited
            self._buckets[key] = (refilled_tokens, now)
            needed = 1.0 - refilled_tokens
            retry_after = max(1, int(needed / self.fill_rate) + 1)
            return False, retry_after

    def reset(self) -> None:
        """Clear all rate limiting state."""
        with self._lock:
            self._buckets.clear()
