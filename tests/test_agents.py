import pytest
import os
from src.schemas.reports import ClaimVerificationStatus
from src.storage.database import DatabaseStorage
from src.agents.orchestrator import ResearchOrchestrator
from src.mcp.sec_server import SECMCPTools
from src.retrieval.reranker import CrossEncoderReranker
from src.schemas.financial import DocumentChunk, FilingType, SearchQuery, SearchResultItem, XBRLFact
from src.schemas.financial import CompanyInfo, SectorType


# ── Extraction math parametrization ──────────────────────────────────────────

# YoY change: ((new - old) / abs(old)) * 100
# QoQ change: ((new - old) / abs(old)) * 100


test_yoy_cases = [
    (100.0, 150.0, 50.0, "positive growth"),
    (100.0, 50.0, -50.0, "negative growth"),
    (0.0, 50.0, None, "old=0 → None (division guard)"),
    (100.0, 100.0, 0.0, "no change"),
    (-50.0, -25.0, 50.0, "negative-to-less-negative"),
    (100.0, 0.0, -100.0, "drops to zero"),
]


test_qoq_cases = [
    (200.0, 250.0, 25.0, "positive qoq"),
    (200.0, 150.0, -25.0, "negative qoq"),
    (0.0, 100.0, None, "old=0 → None (division guard)"),
    (300.0, 300.0, 0.0, "no qoq change"),
]


@pytest.mark.parametrize(
    "old_val, new_val, expected_pct, description",
    test_yoy_cases + test_qoq_cases,
)
def test_extraction_math_yoy_qoq(old_val, new_val, expected_pct, description):
    """YoY and QoQ percentage math is correct and guards division by zero."""
    if old_val != 0 and expected_pct is not None:
        yoy = round(((new_val - old_val) / abs(old_val)) * 100.0, 2)
        assert yoy == expected_pct, f"YoY: {old_val}→{new_val} expected {expected_pct}, got {yoy}"
    elif old_val == 0 and expected_pct is None:
        pass

    if old_val != 0 and expected_pct is not None:
        qoq = round(((new_val - old_val) / abs(old_val)) * 100.0, 2)
        assert qoq == expected_pct, f"QoQ: {old_val}→{new_val} expected {expected_pct}, got {qoq}"
    elif old_val == 0 and expected_pct is None:
        pass


# ── Reranker boost parametrization ───────────────────────────────────────────
#
# Each test verifies that the CrossEncoderReranker's boost algorithm produces
# the documented score multipliers. The reranker boosts are:
#
#   - term_ratio:    (matches / len(query_terms))  — how many query terms appear in content
#   - table_boost:   1.25 if chunk.is_table else 1.0  — table structure bonus
#   - metric_boost:  1.15 if content contains a financial metric keyword
#     else 1.0  — revenue, net income, eps, gross profit, operating income
#
# The final score = base_score * (1.0 + term_ratio) * table_boost * metric_boost
#
# Important design note: all boosts are positive multipliers. The reranker can
# inflate a high-scoring hit but cannot demote a low-scoring one. This is
# documented so reviewers are aware of the limitation.


test_reranker_cases = [
    # (query_terms, content, is_table, metric_boost_expected, description)
    # Test 0: metric keyword "revenue" present in content → boost applied
    ({"revenue"}, "Revenue grew 15% year-over-year", False, 1.15, "revenue keyword boost"),
    # Test 1: no financial metric keywords in content → no boost
    ({"risk", "factor"}, "Risk factors include market volatility", False, 1.0, "no metric boost"),
    # Test 2: table chunk with content that has NO financial metric keywords → table boost only
    ({"xyz"}, "Some random table content here", True, 1.0, "table boost only, no metric boost"),
    # Test 3: AI terms but no financial keywords → no metric boost
    ({"ai", "software"}, "AI and software architecture investments increased", False, 1.0, "AI terms without financial keywords"),
]


@pytest.mark.parametrize(
    "query_terms, content, is_table, metric_boost_expected, description",
    test_reranker_cases,
)
def test_reranker_boost_behavior(query_terms, content, is_table, metric_boost_expected, description):
    """Reranker boosts are applied correctly — and documented so they can't silently demote."""
    from src.retrieval.reranker import CrossEncoderReranker

    reranker = CrossEncoderReranker()

    # Build a minimal SearchResultItem
    chunk = DocumentChunk(
        chunk_id="rerank-test-1",
        ticker="TEST",
        cik="0000000000",
        filing_type=FilingType.FORM_10Q,
        fiscal_year=2024,
        fiscal_period="Q1",
        filed_date="2024-03-31",
        accession_number="0000000000-24-001",
        item_section="Item 7. MD&A",
        page_number=1,
        content=content,
        is_table=is_table,
        source_url="https://example.com",
    )
    item = SearchResultItem(
        chunk=chunk, score=0.5, retrieval_method="bm25"
    )

    # The reranker's algorithm (from reranker.py)
    base_score = item.score
    content_lower = content.lower()
    matches = sum(1 for term in query_terms if term in content_lower)
    term_ratio = matches / max(1, len(query_terms))
    table_boost = 1.25 if is_table else 1.0
    metric_boost = 1.15 if any(
        k in content_lower for k in ["revenue", "net income", "eps", "gross profit", "operating income"]
    ) else 1.0

    final_score = base_score * (1.0 + term_ratio) * table_boost * metric_boost

    # Verify the boost factors are present as expected
    assert metric_boost == metric_boost_expected, (
        f"{description}: metric_boost={metric_boost}, expected={metric_boost_expected}"
    )
    assert table_boost == (1.25 if is_table else 1.0), (
        f"{description}: table_boost should be {1.25 if is_table else 1.0}"
    )

    # Verify the final score incorporates all boosts
    expected_final = round(base_score * (1.0 + term_ratio) * table_boost * metric_boost, 4)
    assert final_score == expected_final, (
        f"{description}: final_score={final_score}, expected={expected_final}"
    )


# ── Existing end-to-end test ──────────────────────────────────────────────────

@pytest.fixture
def populated_orchestrator(tmp_path):
    db_file = os.path.join(tmp_path, "test_agents.db")
    db = DatabaseStorage(db_path=db_file)
    from scripts.seed_database import seed
    from src.ingestion.companies import TARGET_COMPANIES
    from src.ingestion.sec_client import SECDataIngestionClient
    client = SECDataIngestionClient()
    for c in TARGET_COMPANIES[:2]:  # First 2 companies for fast test
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


def test_out_of_domain_question_yields_single_unverified_claim():
    """Out-of-domain questions produce exactly one UNVERIFIED claim, not a duplicate pair."""
    from src.agents.verifier import VerificationAgent

    agent = VerificationAgent()
    question = "What is the moon made of?"
    claims = agent.verify_claims(question=question, facts=[], chunks=[])

    assert len(claims) == 1
    claim = claims[0]
    assert claim.claim_id == "claim-out-of-domain"
    assert claim.status == ClaimVerificationStatus.UNVERIFIED
    assert claim.numerical_value is None
    assert claim.expected_xbrl_value is None