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

def test_get_companies_endpoint():
    response = client.get("/api/companies")
    assert response.status_code == 200
    companies = response.json()
    assert len(companies) >= 25
    assert any(c["ticker"] == "AAPL" for c in companies)

def test_get_xbrl_facts_endpoint():
    response = client.get("/api/facts?ticker=AAPL&concept=Revenues")
    assert response.status_code == 200
    facts = response.json()
    assert len(facts) > 0

def test_query_research_copilot_endpoint():
    payload = {
        "question": "What was Apple's total revenue in 2024?",
        "ticker": "AAPL"
    }
    response = client.post("/api/query", json=payload)
    assert response.status_code == 200
    report = response.json()
    assert "report_id" in report
    assert "executive_summary" in report
    assert len(report["claims"]) > 0
