import os

import pytest

from src.agents.orchestrator import ResearchOrchestrator
from src.ingestion.companies import TARGET_COMPANIES
from src.mcp.sec_server import SECMCPTools
from src.retrieval.reranker import CrossEncoderReranker
from src.schemas.financial import (
    CompanyInfo,
    DataSource,
    DocumentChunk,
    FilingType,
    SearchResultItem,
    SectorType,
    XBRLFact,
)
from src.schemas.reports import ClaimVerificationStatus
from src.storage.database import DatabaseStorage

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
    test_yoy_cases,
)
def test_extraction_math_yoy_qoq(old_val, new_val, expected_pct, description):
    """YoY extraction calls the implementation and guards division by zero."""
    from src.agents.extraction import FinancialExtractionAgent

    facts = [
        XBRLFact(
            fact_id=f"TEST-{year}-FY-Revenues",
            ticker="TEST",
            cik="0000000000",
            entity_name="Test Inc",
            concept="Revenues",
            label="Revenues",
            value=value,
            unit="USD",
            fiscal_year=year,
            fiscal_period="FY",
            form="10-K",
            filed_date=f"{year}-02-01",
            period_end=f"{year}-12-31",
        )
        for year, value in ((2023, old_val), (2024, new_val))
    ]
    comparison = FinancialExtractionAgent().extract_metrics(facts)[0]
    assert comparison.yoy_change_pct == expected_pct, description


@pytest.mark.parametrize(
    "old_val, new_val, expected_pct, description",
    test_qoq_cases,
)
def test_extraction_qoq_math_calls_implementation(
    old_val, new_val, expected_pct, description
):
    from src.agents.extraction import FinancialExtractionAgent

    facts = [
        XBRLFact(
            fact_id=f"TEST-2024-{period}-Revenues",
            ticker="TEST",
            cik="0000000000",
            entity_name="Test Inc",
            concept="Revenues",
            label="Revenues",
            value=value,
            unit="USD",
            fiscal_year=2024,
            fiscal_period=period,
            form="10-Q",
            filed_date=f"2024-{month}-15",
            period_end=f"2024-{month}-01",
        )
        for period, month, value in (("Q2", "06", old_val), ("Q3", "09", new_val))
    ]
    comparison = FinancialExtractionAgent().extract_metrics(facts)[0]
    assert comparison.qoq_change_pct == expected_pct, description


# ── Reranker boost parametrization ───────────────────────────────────────────
#
# Each test verifies that the CrossEncoderReranker's boost algorithm produces
# the documented score multipliers. The reranker boosts are:
#
# Reranker scoring contract (documented):
#   - term_ratio:    (matches / len(query_terms))  — how many query terms appear in content
#   - table_boost:           1.25 — query asks for tables/statements AND chunk is a table
#   - metrics_table_boost:   1.10 — query asks for financial metrics AND chunk is a table,
#     and table_boost did not already fire (statement chunks carry the primary figures)
#   - metric_boost:  1.15 — query asks about financial metrics AND the content
#     contains a metric keyword (revenue, net income, eps, gross profit, operating income)
#
# The final score = base_score * (1.0 + term_ratio) * table_boost * metrics_table_boost * metric_boost
#
# Important design note: all boosts are positive multipliers. The reranker can
# inflate a high-scoring hit but cannot demote a low-scoring one. Boosts are
# query-conditional so a risk question is never outranked merely because a
# competing chunk mentions revenue.


test_reranker_cases = [
    # (query, content, is_table, expected_table_boost, expected_metric_boost, description)
    # Test 0: metric query + metric-keyword content → boosts applied
    (
        "Apple revenue growth for the quarter",
        "Revenue grew 15% year-over-year",
        False,
        1.0,
        1.0,
        1.15,
        "metric query gets metric boost",
    ),
    # Test 1: risk query with revenue-keyword content → NO metric boost (the Item 1A regression pin)
    (
        "What key operational and market risks were disclosed",
        "Revenue grew 15% year-over-year",
        False,
        1.0,
        1.0,
        1.0,
        "risk query ignores revenue chunks",
    ),
    # Test 2: table query + table chunk → explicit table boost applied
    (
        "Show me the consolidated statements",
        "ABCDEFGHIJKLMNOPQRSTUVWXYZ",
        True,
        1.25,
        1.0,
        1.0,
        "table query gets table boost",
    ),
    # Test 3: non-table query + table chunk → NO table boost (the unconditional-table regression pin)
    (
        "What market risks were disclosed",
        "Helvetica random table content",
        True,
        1.0,
        1.0,
        1.0,
        "risk query ignores table chunks",
    ),
    # Test 4: metric query + table chunk without metric keywords → metrics_table_boost only
    (
        "What was total revenue in Q1",
        "CONSOLIDATED STATEMENTS OF OPERATIONS 2024",
        True,
        1.0,
        1.10,
        1.0,
        "metric query favors statement chunks",
    ),
    # Test 5: table query + table chunk with metric keywords → table_boost, no metrics_table_boost double-count
    (
        "Show the statement with the net income",
        "Net income rose 5% year-over-year",
        True,
        1.25,
        1.0,
        1.15,
        "explicit table boost excludes metrics_table_boost",
    ),
]


@pytest.mark.parametrize(
    "query, content, is_table, table_boost_expected, metrics_table_boost_expected, metric_boost_expected, description",
    test_reranker_cases,
)
def test_reranker_boost_behavior(
    query,
    content,
    is_table,
    table_boost_expected,
    metrics_table_boost_expected,
    metric_boost_expected,
    description,
):
    """Boosts fire only when the query asks for them — pins the query-conditional contract."""

    reranker = CrossEncoderReranker()

    # Build a minimal SearchResultItem (content chosen so term_ratio is computeable)
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
    item = SearchResultItem(chunk=chunk, score=0.5, retrieval_method="bm25")

    reranked = reranker.rerank(query, [item], top_k=10)
    assert len(reranked) == 1
    actual_final = reranked[0].score

    # Recompute the documented contract and confirm the reranker matches it
    import re

    query_terms = set(re.findall(r"\w+", query.lower()))
    content_lower = content.lower()
    matches = sum(1 for term in query_terms if term in content_lower)
    term_ratio = matches / max(1, len(query_terms))
    # Test 2 has a table chunk with no metric-keyword-containing content, so no
    # metric boost can fire in the oracle either; the table_boost pin stands.
    metric_query_wanted = any(
        s in query.lower()
        for s in (
            "revenue",
            "income",
            "eps",
            "profit",
            "margin",
            "earnings",
            "growth",
            "yoy",
            "year-over-year",
            "quarter",
            "cash",
        )
    )
    # metrics_table_boost fires only when the query asks for metrics and the
    # chunk is a table AND the explicit table boost did not fire.
    metrics_table_boost = (
        1.10
        if metric_query_wanted and is_table and table_boost_expected == 1.0
        else 1.0
    )
    expected_final = round(
        0.5
        * (1.0 + term_ratio)
        * table_boost_expected
        * metrics_table_boost
        * metric_boost_expected,
        4,
    )

    assert actual_final == expected_final, (
        f"{description}: final_score={actual_final}, expected={expected_final} "
        f"(table_boost={table_boost_expected}, metrics_table_boost={metrics_table_boost}, metric_boost={metric_boost_expected})"
    )


# ── Existing end-to-end test ──────────────────────────────────────────────────


@pytest.fixture
def populated_orchestrator(tmp_path):
    db_file = os.path.join(tmp_path, "test_agents.db")
    db = DatabaseStorage(db_path=db_file)
    from src.ingestion.companies import TARGET_COMPANIES
    from src.ingestion.sec_client import SECDataIngestionClient

    client = SECDataIngestionClient()
    for c in TARGET_COMPANIES[:2]:  # First 2 companies for fast test
        facts = client.fetch_company_facts(c)
        chunks = client.fetch_document_chunks(c)
        db.insert_xbrl_facts(facts)
        db.insert_document_chunks(chunks)

    return ResearchOrchestrator(db=db)


def test_research_orchestrator_end_to_end(populated_orchestrator, monkeypatch):
    monkeypatch.setenv("DATA_MODE", "demo")
    question = (
        "What was Apple's total revenue in 2024 and what are its key risk factors?"
    )
    report = populated_orchestrator.run(question, default_ticker="AAPL")

    assert report is not None
    assert "AAPL" in report.target_tickers
    assert len(report.claims) > 0
    assert report.claims[0].status == ClaimVerificationStatus.UNVERIFIED
    assert report.data_mode == "demo"
    assert "synthetic" in report.executive_summary
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


@pytest.mark.parametrize(
    "question, concept, fiscal_year, fiscal_period",
    [
        ("What was Apple's revenue in Q1 2024?", "Revenues", 2024, "Q1"),
        ("What was Apple's net income in FY 2023?", "NetIncomeLoss", 2023, "FY"),
        (
            "What was Apple's diluted EPS in FY 2023?",
            "EarningsPerShareDiluted",
            2023,
            "FY",
        ),
    ],
)
def test_verifier_selects_requested_concept_and_period(
    question, concept, fiscal_year, fiscal_period
):
    """Numerical verification must match both the requested metric and period."""
    from src.agents.verifier import VerificationAgent
    from src.ingestion.sec_client import generate_mock_xbrl_facts

    company = CompanyInfo(
        ticker="AAPL",
        cik="0000320193",
        name="Apple Inc.",
        sector=SectorType.TECHNOLOGY,
    )
    facts = generate_mock_xbrl_facts(company)
    expected = next(
        fact
        for fact in facts
        if fact.concept == concept
        and fact.fiscal_year == fiscal_year
        and fact.fiscal_period == fiscal_period
    )

    chunk = DocumentChunk(
        chunk_id="AAPL-2024-test",
        ticker="AAPL",
        cik="0000320193",
        filing_type=FilingType.FORM_10K,
        fiscal_year=2024,
        fiscal_period="FY",
        filed_date="2025-02-01",
        accession_number="a-2024",
        item_section="Item 8. Financial Statements",
        page_number=1,
        content="Revenue and income facts from the selected company.",
        source_url="demo://AAPL/2024/FY",
    )
    claims = VerificationAgent().verify_claims(
        question,
        facts,
        [SearchResultItem(chunk=chunk, score=1.0, retrieval_method="test")],
    )
    numerical_claim = next(
        claim for claim in claims if claim.claim_id.startswith("claim-num-")
    )

    assert numerical_claim.status == ClaimVerificationStatus.UNVERIFIED
    assert numerical_claim.numerical_value == expected.value
    assert f"{fiscal_period} {fiscal_year}" in numerical_claim.claim_text


@pytest.mark.parametrize(
    "question",
    [
        "What was Apple's revenue in Q4 2024?",
        "What was Apple's revenue in fiscal year 2025?",
    ],
)
def test_verifier_does_not_substitute_another_period(question):
    """Unavailable requested data must stay unverified, not borrow another period."""
    from src.agents.verifier import VerificationAgent
    from src.ingestion.sec_client import generate_mock_xbrl_facts

    company = CompanyInfo(
        ticker="AAPL",
        cik="0000320193",
        name="Apple Inc.",
        sector=SectorType.TECHNOLOGY,
    )
    claims = VerificationAgent().verify_claims(
        question, generate_mock_xbrl_facts(company), chunks=[]
    )
    numerical_claim = next(
        claim for claim in claims if claim.claim_id.startswith("claim-num-")
    )

    assert numerical_claim.status == ClaimVerificationStatus.UNVERIFIED
    assert numerical_claim.numerical_value is None


def test_planner_keeps_comparison_queries_unfiltered():
    """Comparisons need MD&A commentary, unlike single-figure lookups."""
    from src.agents.planner import PlannerAgent

    planner = PlannerAgent()
    comparison = planner.plan(
        "Compare year-over-year revenue growth for AAPL between 2023 and 2024."
    )
    lookup = planner.plan("What was AAPL revenue in fiscal year 2024?")

    assert comparison.section_hints == []
    assert lookup.section_hints == ["Item 8."]
    lowercase_now = planner.plan("What is Apple's revenue now?")
    uppercase_ticker = planner.plan("What is NOW revenue in FY 2024?")
    assert lowercase_now.tickers == ["AAPL"]
    assert uppercase_ticker.tickers == ["NOW"]


def test_demo_facts_are_never_claimed_as_sec_verified():
    from src.agents.verifier import VerificationAgent
    from src.ingestion.sec_client import generate_mock_xbrl_facts

    company = CompanyInfo(
        ticker="AAPL",
        cik="0000320193",
        name="Apple Inc.",
        sector=SectorType.TECHNOLOGY,
    )
    chunk = DocumentChunk(
        chunk_id="AAPL-2024-test",
        ticker="AAPL",
        cik="0000320193",
        filing_type=FilingType.FORM_10K,
        fiscal_year=2024,
        fiscal_period="FY",
        filed_date="2025-02-01",
        accession_number="a-2024",
        item_section="Item 8. Financial Statements",
        page_number=1,
        content="Revenue figures for Apple.",
        source_url="demo://AAPL/2024/FY",
    )
    claims = VerificationAgent().verify_claims(
        "What was Apple's revenue in FY 2024?",
        generate_mock_xbrl_facts(company),
        [SearchResultItem(chunk=chunk, score=1.0, retrieval_method="test")],
    )
    numerical = next(
        claim for claim in claims if claim.claim_id.startswith("claim-num-")
    )
    assert numerical.status == ClaimVerificationStatus.UNVERIFIED
    assert "generated demo" in numerical.verification_notes


def test_qualitative_claim_quotes_retrieved_text_without_verified_badge():
    from src.agents.verifier import VerificationAgent

    chunk = DocumentChunk(
        chunk_id="AAPL-2024-q1-text",
        ticker="AAPL",
        cik="0000320193",
        filing_type=FilingType.FORM_10Q,
        fiscal_year=2024,
        fiscal_period="Q1",
        filed_date="2024-04-15",
        accession_number="a-1",
        item_section="Item 7. MD&A",
        page_number=1,
        content="The company expanded research investment. Revenue was reported.",
        source_url="demo://AAPL/2024/Q1",
        data_source=DataSource.DEMO,
    )
    result = SearchResultItem(chunk=chunk, score=1.0, retrieval_method="test")
    claims = VerificationAgent().verify_claims(
        "What is Apple's revenue trend?", [], [result]
    )
    qualitative = next(
        claim for claim in claims if claim.claim_id == "claim-qualitative-1"
    )
    assert qualitative.claim_text == "The company expanded research investment."
    assert qualitative.status == ClaimVerificationStatus.UNVERIFIED


def test_risk_analysis_does_not_invent_when_no_risk_sources():
    from src.agents.analysis import FinancialAnalysisAgent

    assert FinancialAnalysisAgent().analyze_risk_disclosures([]) == []


def test_risk_analysis_matches_ai_as_word_not_substring():
    from src.agents.analysis import FinancialAnalysisAgent

    chunk = DocumentChunk(
        chunk_id="AAPL-2024-q1-text",
        ticker="AAPL",
        cik="0000320193",
        filing_type=FilingType.FORM_10Q,
        fiscal_year=2024,
        fiscal_period="Q1",
        filed_date="2024-04-15",
        accession_number="a-1",
        item_section="Item 1A. Risk Factors",
        page_number=1,
        content="The company said supply chain risks remained stable.",
        source_url="demo://AAPL/2024/Q1",
    )
    analysis = FinancialAnalysisAgent().analyze_risk_disclosures(
        [SearchResultItem(chunk=chunk, score=1.0, retrieval_method="test")]
    )
    assert analysis[0].trend == "not_assessed"


def test_sec_ingestion_requires_user_agent():
    from src.ingestion.sec_client import SECDataIngestionClient

    with pytest.raises(ValueError, match="SEC_USER_AGENT"):
        SECDataIngestionClient(data_mode="sec", user_agent=None)


def test_sec_mode_never_returns_demo_chunks():
    from src.ingestion.sec_client import SECDataIngestionClient

    client = SECDataIngestionClient(
        data_mode="sec", user_agent="TestResearch/1.0 (test@example.com)"
    )
    assert client.fetch_document_chunks(TARGET_COMPANIES[0]) == []


def test_sec_mode_report_excludes_demo_provenance(populated_orchestrator, monkeypatch):
    monkeypatch.setenv("DATA_MODE", "sec")
    report = populated_orchestrator.run("What was AAPL revenue in FY 2024?")
    assert report.data_mode == "sec"
    assert report.claims[0].status == ClaimVerificationStatus.UNVERIFIED
    assert report.citations == []
