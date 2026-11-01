"""Per-key sliding-window rate limiter with optional Redis backend.

check() returns (allowed, retry_after_seconds): when blocked, callers
should respond 429 with Retry-After set to retry_after_seconds.
The default limit is configurable via RATE_LIMIT_PER_MINUTE so tests
can tighten it without changing production defaults.

By default this is an in-memory, per-process limiter. When Redis is
available (REDIS_URL set and reachable), requests are tracked in Redis
so the limit is enforced across all uvicorn workers.
"""

import math
import os
import threading
import time
from collections import deque


class SlidingWindowRateLimiter:
    """Per-key sliding-window rate limiter with optional Redis backend."""

    def __init__(self, limit: int | None = None, window_seconds: float = 60.0):
        self.limit = int(
            limit if limit is not None else os.getenv("RATE_LIMIT_PER_MINUTE", "60")
        )
        self.window_seconds = window_seconds
        self._events: dict[str, deque[float]] = {}
        self._lock = threading.Lock()
        self._use_redis = self._redis_available()

    def _redis_available(self) -> bool:
        import os as _os

        return _os.getenv("REDIS_ENABLED", "true").strip().lower() not in {
            "false",
            "0",
            "no",
            "off",
        }

    def check(self, key: str) -> tuple[bool, int]:
        if self._use_redis:
            try:
                from src.api.redis_observability import get_redis

                client = get_redis()
                if client is not None:
                    return self._check_redis(client, key)
            except Exception:  # noqa: BLE001,S110 - graceful degradation
                pass
        return self._check_local(key)

    def _check_redis(self, client, key: str) -> tuple[bool, int]:
        now = time.time()
        window_start = now - self.window_seconds
        pipe = client.pipeline()
        pipe.zremrangebyscore(f"ratelimit:{key}", 0, window_start)
        pipe.zcard(f"ratelimit:{key}")
        pipe.zadd(f"ratelimit:{key}", {str(now): now})
        pipe.expire(f"ratelimit:{key}", int(self.window_seconds) + 1)
        results = pipe.execute()
        current_count = results[1]
        if current_count >= self.limit:
            oldest = client.zrange(f"ratelimit:{key}", 0, 0, withscores=True)
            if oldest:
                oldest_time = float(oldest[0][1])
                retry_after = math.ceil(oldest_time + self.window_seconds - now)
                return False, max(1, retry_after)
            return False, max(1, int(self.window_seconds))
        return True, 0

    def _check_local(self, key: str) -> tuple[bool, int]:
        now = time.monotonic()
        with self._lock:
            if len(self._events) >= 10_000 and key not in self._events:
                self._events.clear()
            window = self._events.setdefault(key, deque())
            cutoff = now - self.window_seconds
            while window and window[0] <= cutoff:
                window.popleft()
            if not window:
                self._events.pop(key, None)
                window = self._events.setdefault(key, deque())
            if len(window) >= self.limit:
                retry_after = math.ceil(window[0] + self.window_seconds - now)
                return False, max(1, retry_after)
            window.append(now)
            return True, 0

    def reset(self) -> None:
        with self._lock:
            self._events.clear()
        if self._use_redis:
            try:
                from src.api.redis_observability import get_redis

                client = get_redis()
                if client is not None:
                    for k in client.scan_iter("ratelimit:*"):
                        client.delete(k)
            except Exception:  # noqa: BLE001,S110 - graceful degradation
                pass
