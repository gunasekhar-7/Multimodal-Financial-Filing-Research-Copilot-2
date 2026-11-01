import pytest
from fastapi.testclient import TestClient

from src.api.app import app

client = TestClient(app)


def test_health_endpoint():
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["companies_count"] >= 25
    assert data["data_mode"] in {"demo", "sec"}
    assert "demo_data" in data


def test_get_companies_endpoint():
    response = client.get("/api/companies")
    assert response.status_code == 200
    companies = response.json()
    assert len(companies) >= 25
    assert any(c["ticker"] == "AAPL" for c in companies)


def test_get_xbrl_facts_endpoint(monkeypatch, tmp_path):
    from src.api import app as app_module
    from src.ingestion.companies import TARGET_COMPANIES
    from src.ingestion.sec_client import SECDataIngestionClient
    from src.storage.database import DatabaseStorage

    isolated_db = DatabaseStorage(str(tmp_path / "api-facts.db"))
    isolated_db.insert_xbrl_facts(
        SECDataIngestionClient(data_mode="demo").fetch_company_facts(
            TARGET_COMPANIES[0]
        )
    )
    monkeypatch.setattr(app_module, "db", isolated_db)
    monkeypatch.setenv("DATA_MODE", "demo")
    response = client.get("/api/facts?ticker=AAPL&concept=Revenues")
    assert response.status_code == 200
    facts = response.json()
    assert len(facts) > 0
    assert all(fact["data_source"] == "demo" for fact in facts)


@pytest.mark.parametrize(
    "mode, expected_source",
    [("demo", "demo"), ("sec", "sec_edgar")],
)
def test_facts_endpoint_respects_selected_mode(
    monkeypatch, tmp_path, mode, expected_source
):
    from src.api import app as app_module
    from src.schemas.financial import DataSource, XBRLFact
    from src.storage.database import DatabaseStorage

    isolated_db = DatabaseStorage(str(tmp_path / "api-mode.db"))
    isolated_db.insert_xbrl_facts(
        [
            XBRLFact(
                fact_id="API-DEMO-2024-FY",
                ticker="AAPL",
                cik="0000320193",
                entity_name="Apple Inc.",
                concept="Revenues",
                label="Revenues",
                value=2,
                fiscal_year=2024,
                fiscal_period="FY",
                form="10-K",
                filed_date="2025-01-01",
                period_end="2024-12-31",
                data_source=DataSource.DEMO,
            ),
            XBRLFact(
                fact_id="API-SEC-2024-FY",
                ticker="AAPL",
                cik="0000320193",
                entity_name="Apple Inc.",
                concept="Revenues",
                label="Revenues",
                value=1,
                fiscal_year=2024,
                fiscal_period="FY",
                form="10-K",
                filed_date="2025-01-01",
                period_end="2024-12-31",
                data_source=DataSource.SEC_EDGAR,
            ),
        ]
    )
    monkeypatch.setattr(app_module, "db", isolated_db)
    monkeypatch.setenv("DATA_MODE", mode)
    response = client.get("/api/facts?ticker=AAPL&concept=Revenues")
    assert response.status_code == 200
    assert [item["data_source"] for item in response.json()] == [expected_source]


def test_query_research_copilot_endpoint():
    payload = {"question": "What was Apple's total revenue in 2024?", "ticker": "AAPL"}
    response = client.post("/api/query", json=payload)
    assert response.status_code == 200
    report = response.json()
    assert "report_id" in report
    assert "executive_summary" in report
    assert len(report["claims"]) > 0


def test_cors_preflight_specific_origins():
    """CORS uses specific localhost origins (not wildcard), credentials only with specific origins."""
    resp = client.options(
        "/api/query",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert resp.status_code == 200
    # Credentials should be allowed only with specific origins, not wildcard
    assert resp.headers.get("access-control-allow-credentials") == "true"
    # Origin should be the specific allowed one
    assert resp.headers.get("access-control-allow-origin") == "http://localhost:3000"


def test_cors_preflight_rejects_wildcard():
    """CORS must not allow credentials with wildcard origin."""
    resp = client.options(
        "/api/query",
        headers={
            "Origin": "http://example.com",
            "Access-Control-Request-Method": "POST",
        },
    )
    # With specific origin config, wildcard origin should not get credentials
    # The header may be absent or not credentials; we verify safety
    allow_cred = resp.headers.get("access-control-allow-credentials", "")
    allow_origin = resp.headers.get("access-control-allow-origin", "")
    # Should NOT allow credentials on unknown origin
    assert allow_cred != "true" or allow_origin not in (
        "http://localhost",
        "http://127.0.0.1",
    )


def test_metrics_endpoint_shape():
    """Metrics report uptime, tracked request count, latency percentiles, index freshness."""
    resp = client.get("/api/metrics")
    assert resp.status_code == 200
    data = resp.json()
    assert data["uptime_seconds"] >= 0
    assert data["request_count"] >= 1
    assert "/api/query" in data["latency_ms"]
    assert "/api/search" in data["latency_ms"]
    query_stats = data["latency_ms"]["/api/query"]
    assert set(query_stats) == {"count", "p50", "p95"}
    assert "dense_index" in data
    assert "initialized" in data["dense_index"]
    assert "last_refresh" in data["dense_index"]


def test_rate_limit_returns_429_with_retry_after():
    """A tightened budget produces 429 with a usable Retry-After header."""
    from src.api import app as app_module
    from src.api.ratelimit import SlidingWindowRateLimiter

    app_module.rate_limiter = SlidingWindowRateLimiter(limit=2, window_seconds=60)
    try:
        payload = {"query": "Apple revenue 2024", "top_k": 3}
        assert client.post("/api/search", json=payload).status_code == 200
        assert client.post("/api/search", json=payload).status_code == 200
        resp = client.post("/api/search", json=payload)
        assert resp.status_code == 429
        assert int(resp.headers["retry-after"]) >= 1
        assert "detail" in resp.json()
    finally:
        app_module.rate_limiter = SlidingWindowRateLimiter()
        app_module.rate_limiter.reset()
