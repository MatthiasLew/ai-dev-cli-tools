from __future__ import annotations

import threading
import time
from collections import OrderedDict
from collections.abc import Callable


class TokenBucketRateLimiter:
    """
    Thread-safe in-memory token bucket rate limiter with hard memory bounds.
    Transient keys (e.g. client IP) are held in memory only and never persisted.
    Uses an OrderedDict with LRU eviction to guarantee:
        len(_buckets) <= max_entries
    under any adversarial key flooding.
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
        self.max_entries = max(1, max_entries)
        self._buckets: OrderedDict[str, tuple[float, float]] = OrderedDict()
        self._lock = threading.Lock()

    def __len__(self) -> int:
        with self._lock:
            return len(self._buckets)

    def is_allowed(self, key: str) -> tuple[bool, int]:
        """
        Check if request for key is permitted under the rate limit.
        Returns:
            (allowed: bool, retry_after_seconds: int)
        """
        now = self.clock()
        with self._lock:
            if key in self._buckets:
                tokens, last_time = self._buckets[key]
                elapsed = max(0.0, now - last_time)
                refilled_tokens = min(self.capacity, tokens + (elapsed * self.fill_rate))

                if refilled_tokens >= 1.0:
                    self._buckets[key] = (refilled_tokens - 1.0, now)
                    self._buckets.move_to_end(key)
                    return True, 0

                # Rate limited
                self._buckets[key] = (refilled_tokens, now)
                self._buckets.move_to_end(key)
                needed = 1.0 - refilled_tokens
                retry_after = max(1, int(needed / self.fill_rate) + 1)
                return False, retry_after

            # Key is not present: enforce hard memory bound before insertion
            if len(self._buckets) >= self.max_entries:
                # 1. Attempt fast eviction of stale entries older than 10 minutes
                stale_cutoff = now - 600.0
                stale_keys = [k for k, v in self._buckets.items() if v[1] < stale_cutoff]
                for k in stale_keys:
                    self._buckets.pop(k, None)

                # 2. If still at capacity, strictly evict least recently used entries
                while len(self._buckets) >= self.max_entries:
                    self._buckets.popitem(last=False)

            # Insert new key
            self._buckets[key] = (self.capacity - 1.0, now)
            return True, 0

    def reset(self) -> None:
        """Clear all rate limiting state."""
        with self._lock:
            self._buckets.clear()
