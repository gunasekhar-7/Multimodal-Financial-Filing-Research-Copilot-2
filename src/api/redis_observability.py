"""Cross-worker observability backed by Redis with in-process fallback.

Provides Redis-backed rate limiting and metrics that work across multiple
uvicorn workers. Falls back gracefully to in-process implementations when
Redis is unavailable, so the service can run standalone without Redis.

Environment variables:
- REDIS_URL: Redis connection URL (default: redis://localhost:6379/0)
- REDIS_ENABLED: Set to "false" to disable Redis and use in-process only
- RATE_LIMIT_PER_MINUTE: Default rate limit per minute per key
"""

import logging
import math
import os
import secrets
import time

logger = logging.getLogger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
REDIS_ENABLED = os.getenv("REDIS_ENABLED", "true").strip().lower() not in {
    "false",
    "0",
    "no",
    "off",
}


def _try_redis():
    """Attempt to import and connect to Redis. Returns (redis_module, client) or (None, None)."""
    if not REDIS_ENABLED:
        return None, None
    try:
        import redis  # type: ignore[import-not-found,import-untyped]

        client = redis.from_url(REDIS_URL, socket_connect_timeout=1, socket_timeout=1)
        client.ping()
        return redis, client
    except Exception:  # noqa: BLE001 - graceful degradation
        return None, None


# Module-level Redis client (lazy connection)
_redis_client = None
_redis_available = None


def get_redis():
    """Get Redis client, attempting connection on first call."""
    global _redis_client, _redis_available
    if _redis_available is None:
        _, _redis_client = _try_redis()
        _redis_available = _redis_client is not None
        if _redis_available:
            logger.info("Redis connected for cross-worker observability")
        else:
            logger.info("Redis unavailable; using in-process observability")
    return _redis_client


# ---------------------------------------------------------------------------
# Redis-backed sliding window rate limiter
# ---------------------------------------------------------------------------


class RedisSlidingWindowRateLimiter:
    """Redis-backed sliding window rate limiter with in-process fallback.

    Uses Redis sorted sets to track request timestamps across workers.
    Falls back to the in-process SlidingWindowRateLimiter when Redis is down.
    """

    def __init__(self, limit: int | None = None, window_seconds: float = 60.0):
        if limit is not None:
            self.limit = limit
        else:
            self.limit = int(os.getenv("RATE_LIMIT_PER_MINUTE", "60"))
        self.window_seconds = window_seconds
        # Fallback in-process limiter
        self._fallback = None

    def _get_fallback(self):
        if self._fallback is None:
            from src.api.ratelimit import SlidingWindowRateLimiter

            self._fallback = SlidingWindowRateLimiter(
                limit=self.limit, window_seconds=self.window_seconds
            )
        return self._fallback

    def check(self, key: str) -> tuple[bool, int]:
        redis_client = get_redis()
        if redis_client is not None:
            try:
                return self._check_redis(redis_client, key)
            except Exception as exc:  # noqa: BLE001 - graceful degradation
                logger.warning("Redis rate limit check failed, falling back: %s", exc)
        return self._get_fallback().check(key)

    def _check_redis(self, client, key: str) -> tuple[bool, int]:
        now = time.time()
        window_start = now - self.window_seconds
        unique_token = secrets.token_hex(4)
        pipe = client.pipeline()
        pipe.zremrangebyscore(f"ratelimit:{key}", 0, window_start)
        pipe.zcard(f"ratelimit:{key}")
        pipe.zadd(f"ratelimit:{key}", {f"{now}:{unique_token}": now})
        pipe.expire(f"ratelimit:{key}", int(self.window_seconds) + 1)
        results = pipe.execute()
        current_count = results[1]
        if current_count >= self.limit:
            # Get the oldest entry to compute retry_after
            oldest = client.zrange(f"ratelimit:{key}", 0, 0, withscores=True)
            if oldest:
                oldest_time = float(oldest[0][1])
                retry_after = math.ceil(oldest_time + self.window_seconds - now)
                return False, max(1, retry_after)
            return False, max(1, int(self.window_seconds))
        return True, 0

    def reset(self) -> None:
        redis_client = get_redis()
        if redis_client is not None:
            try:
                # Scan and delete all rate limit keys
                for key in redis_client.scan_iter("ratelimit:*"):
                    redis_client.delete(key)
            except Exception:  # noqa: BLE001,S110 - graceful degradation
                pass
        if self._fallback is not None:
            self._fallback.reset()


# ---------------------------------------------------------------------------
# Redis-backed metrics
# ---------------------------------------------------------------------------


class RedisRequestMetrics:
    """Redis-backed request metrics with in-process fallback.

    Stores request counters and latency samples in Redis sorted sets/hashes
    for cross-worker visibility. Falls back to in-process RequestMetrics.
    """

    def __init__(self, max_samples: int = 1000):
        self._started_at = time.time()
        self.max_samples = max_samples
        self._fallback = None

    def _get_fallback(self):
        if self._fallback is None:
            from src.api.metrics import RequestMetrics

            self._fallback = RequestMetrics(max_samples=self.max_samples)
        return self._fallback

    @property
    def request_count(self) -> int:
        redis_client = get_redis()
        if redis_client is not None:
            try:
                count = redis_client.get("metrics:request_count")
                return int(count) if count else 0
            except Exception:  # noqa: BLE001,S110 - graceful degradation
                pass
        return self._get_fallback().request_count

    @property
    def started_at(self) -> float:
        return self._started_at

    def note_request(self) -> None:
        redis_client = get_redis()
        if redis_client is not None:
            try:
                redis_client.incr("metrics:request_count")
                return
            except Exception:  # noqa: BLE001,S110 - graceful degradation
                pass
        self._get_fallback().note_request()

    def record(self, endpoint: str, latency_ms: float) -> None:
        redis_client = get_redis()
        if redis_client is not None:
            try:
                now = time.time()
                key = f"metrics:latencies:{endpoint}"
                unique_token = secrets.token_hex(4)
                member = f"{latency_ms}:{now}:{unique_token}"
                pipe = redis_client.pipeline()
                pipe.zadd(key, {member: now})
                pipe.zremrangebyscore(key, 0, now - 3600)  # keep 1 hour
                pipe.zremrangebyrank(key, 0, -(self.max_samples + 1))
                pipe.expire(key, 3600 + 60)
                pipe.execute()
                return
            except Exception:  # noqa: BLE001,S110 - graceful degradation
                pass
        self._get_fallback().record(endpoint, latency_ms)

    def summary(self, endpoint: str) -> dict[str, float | None]:
        redis_client = get_redis()
        if redis_client is not None:
            try:
                key = f"metrics:latencies:{endpoint}"
                raw_entries = redis_client.zrange(key, 0, -1)
                samples: list[float] = []
                for entry in raw_entries:
                    text = (
                        entry.decode("utf-8")
                        if isinstance(entry, bytes)
                        else str(entry)
                    )
                    try:
                        val = float(text.split(":", 1)[0])
                        samples.append(val)
                    except (ValueError, IndexError):
                        continue
                if not samples:
                    return {"count": 0, "p50": None, "p95": None}
                ordered = sorted(samples)
                return {
                    "count": len(ordered),
                    "p50": _percentile(ordered, 50),
                    "p95": _percentile(ordered, 95),
                }
            except Exception:  # noqa: BLE001,S110 - graceful degradation to fallback
                pass
        return self._get_fallback().summary(endpoint)


def _percentile(values: list[float], p: int) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, round((p / 100.0) * (len(ordered) - 1))))
    return round(ordered[idx], 2)
