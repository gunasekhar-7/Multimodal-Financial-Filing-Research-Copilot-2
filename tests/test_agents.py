import pytest
import os
from src.storage.database import DatabaseStorage
from src.agents.orchestrator import ResearchOrchestrator
from src.mcp.sec_server import SECMCPTools
from src.schemas.reports import ClaimVerificationStatus

@pytest.fixture
def populated_orchestrator(tmp_path):
    db_file = os.path.join(tmp_path, "test_agents.db")
    db = DatabaseStorage(db_path=db_file)
    from scripts.seed_database import seed
    # Insert facts & chunks
    from src.ingestion.companies import TARGET_COMPANIES
    from src.ingestion.sec_client import SECDataIngestionClient
    client = SECDataIngestionClient()
    for c in TARGET_COMPANIES[:2]: # First 2 companies for fast test
        facts = client.fetch_company_facts(c)
        chunks = client.fetch_document_chunks(c)
        db.insert_xbrl_facts(facts)
        db.insert_document_chunks(chunks)

    return ResearchOrchestrator(db=db)

def test_research_orchestrator_end_to_end(populated_orchestrator):
    question = "What was Apple's total revenue in 2024 and what are its key risk factors?"
    report = populated_orchestrator.run(question, default_ticker="AAPL")

    assert report is not None
    assert "AAPL" in report.target_tickers
    assert len(report.claims) > 0
    assert report.claims[0].status == ClaimVerificationStatus.VERIFIED
    assert len(report.metric_comparisons) > 0
    assert len(report.citations) > 0
    assert "disclaimer" in report.model_dump()

def test_mcp_sec_tools(populated_orchestrator):
    mcp_tools = SECMCPTools(populated_orchestrator.db)
    companies = mcp_tools.list_companies()
    assert len(companies) >= 25

    facts = mcp_tools.get_xbrl_facts(ticker="AAPL", concept="Revenues", year=2024)
    assert len(facts) > 0

    search_res = mcp_tools.search_sec_filings(query="revenue growth", ticker="AAPL")
    assert len(search_res) > 0
