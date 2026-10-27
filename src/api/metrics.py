import time
from collections import deque
from typing import Dict, Optional, Tuple


def _percentile(values: Tuple[float, ...], p: int) -> Optional[float]:
    """Nearest-rank percentile of a latency sample tuple (milliseconds)."""
    if not values:
        return None
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, int(round((p / 100.0) * (len(ordered) - 1)))))
    return round(ordered[idx], 2)


class RequestMetrics:
    """In-process request counter and latency ring-buffers per endpoint.

    Deliberately process-local and dependency-free: it is enough for the
    /api/metrics endpoint to give operators real signal without standing
    up Prometheus or a metrics service.
    """

    def __init__(self, max_samples: int = 1000):
        self.started_at = time.time()
        self.max_samples = max_samples
        self._request_count = 0
        self._latencies: Dict[str, deque] = {}

    @property
    def request_count(self) -> int:
        return self._request_count

    def note_request(self) -> None:
        self._request_count += 1

    def record(self, endpoint: str, latency_ms: float) -> None:
        samples = self._latencies.setdefault(
            endpoint, deque(maxlen=self.max_samples)
        )
        samples.append(latency_ms)

    def summary(self, endpoint: str) -> Dict[str, Optional[float]]:
        samples = tuple(self._latencies.get(endpoint, ()))
        return {
            "count": len(samples),
            "p50": _percentile(samples, 50),
            "p95": _percentile(samples, 95),
        }
