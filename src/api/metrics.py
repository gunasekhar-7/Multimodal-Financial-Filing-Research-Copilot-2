"""Request metrics with optional Redis backend.

Deliberately dependency-free by default: in-process counters and latency
ring-buffers give operators real signal without standing up Prometheus or
a metrics service.

When Redis is available (REDIS_URL set and reachable), counters and
latency samples are stored in Redis for cross-worker visibility across
multiple uvicorn workers.
"""

import os
import threading
import time
from collections import deque


def _percentile(values: list[float] | tuple[float, ...], p: int) -> float | None:
    """Nearest-rank percentile of a latency sample tuple (milliseconds)."""
    if not values:
        return None
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, round((p / 100.0) * (len(ordered) - 1))))
    return round(ordered[idx], 2)


class RequestMetrics:
    """Request counter and latency ring-buffers per endpoint, with optional Redis backend."""

    def __init__(self, max_samples: int = 1000):
        self._started_at = time.time()
        self.max_samples = max_samples
        self._request_count = 0
        self._latencies: dict[str, deque] = {}
        self._lock = threading.Lock()
        self._use_redis = os.getenv("REDIS_ENABLED", "true").strip().lower() not in {
            "false",
            "0",
            "no",
            "off",
        }

    @property
    def request_count(self) -> int:
        if self._use_redis:
            try:
                from src.api.redis_observability import get_redis

                client = get_redis()
                if client is not None:
                    count = client.get("metrics:request_count")
                    return int(count) if count else 0
            except Exception:  # noqa: BLE001,S110 - graceful degradation
                pass
        with self._lock:
            return self._request_count

    @property
    def started_at(self) -> float:
        return self._started_at

    def note_request(self) -> None:
        if self._use_redis:
            try:
                from src.api.redis_observability import get_redis

                client = get_redis()
                if client is not None:
                    client.incr("metrics:request_count")
                    return
            except Exception:  # noqa: BLE001,S110 - graceful degradation
                pass
        with self._lock:
            self._request_count += 1

    def record(self, endpoint: str, latency_ms: float) -> None:
        if self._use_redis:
            try:
                from src.api.redis_observability import get_redis

                client = get_redis()
                if client is not None:
                    now = time.time()
                    key = f"metrics:latencies:{endpoint}"
                    client.zadd(key, {str(now): latency_ms})
                    client.zremrangebyscore(key, 0, now - 3600)
                    client.expire(key, 3600 + 60)
                    return
            except Exception:  # noqa: BLE001,S110 - graceful degradation
                pass
        with self._lock:
            samples = self._latencies.setdefault(
                endpoint, deque(maxlen=self.max_samples)
            )
            samples.append(latency_ms)

    def summary(self, endpoint: str) -> dict[str, float | None]:
        if self._use_redis:
            try:
                from src.api.redis_observability import get_redis

                client = get_redis()
                if client is not None:
                    key = f"metrics:latencies:{endpoint}"
                    samples = [
                        float(v) for _, v in client.zrange(key, 0, -1, withscores=True)
                    ]
                    if not samples:
                        return {"count": 0, "p50": None, "p95": None}
                    ordered = sorted(samples)
                    return {
                        "count": len(ordered),
                        "p50": _percentile(ordered, 50),
                        "p95": _percentile(ordered, 95),
                    }
            except Exception:  # noqa: BLE001,S110 - graceful degradation
                pass
        with self._lock:
            local_samples = tuple(self._latencies.get(endpoint, ()))
        return {
            "count": len(local_samples),
            "p50": _percentile(local_samples, 50),
            "p95": _percentile(local_samples, 95),
        }
