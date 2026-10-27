import math
import os
import threading
import time
from collections import defaultdict, deque
from typing import Deque, Dict, Optional, Tuple


class SlidingWindowRateLimiter:
    """Per-key sliding-window request limiter.

    check() returns (allowed, retry_after_seconds): when blocked, callers
    should respond 429 with Retry-After set to retry_after_seconds.
    The default limit is configurable via RATE_LIMIT_PER_MINUTE so tests
    can tighten it without changing production defaults.
    """

    def __init__(self, limit: Optional[int] = None, window_seconds: float = 60.0):
        self.limit = int(
            limit if limit is not None else os.getenv("RATE_LIMIT_PER_MINUTE", "60")
        )
        self.window_seconds = window_seconds
        self._events: Dict[str, Deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str) -> Tuple[bool, int]:
        now = time.monotonic()
        with self._lock:
            window = self._events[key]
            cutoff = now - self.window_seconds
            while window and window[0] <= cutoff:
                window.popleft()
            if len(window) >= self.limit:
                retry_after = math.ceil(window[0] + self.window_seconds - now)
                return False, max(1, retry_after)
            window.append(now)
            return True, 0

    def reset(self) -> None:
        with self._lock:
            self._events.clear()
