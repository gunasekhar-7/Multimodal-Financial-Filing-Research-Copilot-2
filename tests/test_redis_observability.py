from unittest.mock import MagicMock, patch

from src.api.redis_observability import (
    RedisRequestMetrics,
    RedisSlidingWindowRateLimiter,
    _percentile,
)


class TestRedisObservabilityFallback:
    def test_percentile_calculations(self):
        assert _percentile([], 50) is None
        assert _percentile([10.0], 50) == 10.0
        samples = [10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0, 80.0, 90.0, 100.0]
        assert _percentile(samples, 50) == 50.0
        assert _percentile(samples, 95) == 100.0

    def test_rate_limiter_in_process_fallback(self):
        limiter = RedisSlidingWindowRateLimiter(limit=3, window_seconds=60.0)
        limiter.reset()

        # Requests 1..3 should be allowed
        assert limiter.check("client_test")[0] is True
        assert limiter.check("client_test")[0] is True
        assert limiter.check("client_test")[0] is True

        # Request 4 exceeds limit
        allowed, retry_after = limiter.check("client_test")
        assert allowed is False
        assert retry_after > 0

        # Resetting clears counter
        limiter.reset()
        assert limiter.check("client_test")[0] is True

    def test_request_metrics_in_process_fallback(self):
        metrics = RedisRequestMetrics(max_samples=50)
        metrics.note_request()
        assert metrics.request_count >= 1

        metrics.record("/api/query", 120.5)
        metrics.record("/api/query", 180.2)
        metrics.record("/api/query", 150.0)

        summary = metrics.summary("/api/query")
        assert summary["count"] == 3
        assert summary["p50"] is not None
        assert 120.0 <= summary["p50"] <= 180.0


class TestRedisLiveMock:
    def test_check_redis_rate_limiter_allowed_and_blocked(self):
        limiter = RedisSlidingWindowRateLimiter(limit=2, window_seconds=60.0)
        mock_client = MagicMock()
        mock_pipe = MagicMock()
        mock_client.pipeline.return_value = mock_pipe

        # Case 1: Under limit (current_count = 1)
        mock_pipe.execute.return_value = [0, 1, 1, True]
        allowed, retry_after = limiter._check_redis(mock_client, "test_key")
        assert allowed is True
        assert retry_after == 0

        # Case 2: At or above limit (current_count = 2)
        mock_pipe.execute.return_value = [0, 2, 1, True]
        import time

        now = time.time()
        mock_client.zrange.return_value = [("some_entry", now - 30)]
        allowed, retry_after = limiter._check_redis(mock_client, "test_key")
        assert allowed is False
        assert retry_after > 0

    def test_redis_request_metrics_record_and_summary(self):
        metrics = RedisRequestMetrics(max_samples=100)
        mock_client = MagicMock()
        mock_pipe = MagicMock()
        mock_client.pipeline.return_value = mock_pipe

        with patch("src.api.redis_observability.get_redis", return_value=mock_client):
            # Test note_request
            metrics.note_request()
            mock_client.incr.assert_called_with("metrics:request_count")

            # Test record
            metrics.record("/api/query", 45.5)
            mock_pipe.execute.assert_called()

            # Test summary: entries formatted as "{latency}:{now}:{nonce}"
            mock_client.zrange.return_value = [
                b"40.0:1700000000:abc",
                b"50.0:1700000001:def",
                b"60.0:1700000002:ghi",
            ]
            summary = metrics.summary("/api/query")
            assert summary["count"] == 3
            assert summary["p50"] == 50.0
            assert summary["p95"] == 60.0
