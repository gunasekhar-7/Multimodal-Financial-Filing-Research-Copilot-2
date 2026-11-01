from src.agents.verifier import VerificationAgent
from src.schemas.financial import (
    DataSource,
    DocumentChunk,
    FilingType,
    SearchResultItem,
    XBRLFact,
)
from src.schemas.reports import ClaimVerificationStatus


def _make_fact(
    ticker="AAPL",
    concept="Revenues",
    year=2024,
    period="Q1",
    value=100000000.0,
    data_source=DataSource.DEMO,
    label="Revenues",
    fact_id=None,
):
    return XBRLFact(
        fact_id=fact_id or f"{ticker}-{year}-{period}-{concept}",
        ticker=ticker,
        cik="0000320193",
        entity_name="Apple Inc.",
        concept=concept,
        taxonomy="us-gaap",
        label=label,
        value=value,
        unit="USD",
        fiscal_year=year,
        fiscal_period=period,
        form="10-Q",
        filed_date="2024-04-15",
        period_end=f"{year}-03-31",
        is_restated=False,
        data_source=data_source,
    )


def _make_chunk(
    ticker="AAPL",
    year=2024,
    period="Q1",
    data_source=DataSource.DEMO,
    chunk_id="AAPL-2024-Q1-test",
    content="Apple reported revenue of $100 million for Q1 2024.",
):
    return SearchResultItem(
        chunk=DocumentChunk(
            chunk_id=chunk_id,
            ticker=ticker,
            cik="0000320193",
            filing_type=FilingType.FORM_10Q,
            fiscal_year=year,
            fiscal_period=period,
            filed_date="2024-04-15",
            accession_number="0000320193-24-001",
            item_section="Item 8. Financial Statements",
            page_number=28,
            content=content,
            is_table=True,
            source_url="demo://AAPL/2024/Q1",
            data_source=data_source,
        ),
        score=1.0,
        retrieval_method="test",
    )


class TestVerificationStatusMachine:
    """Parametrized tests for the VerificationAgent status machine."""

    def test_demo_exact_match_is_unverified(self):
        """Demo data with exact fixture match → UNVERIFIED (synthetic, not SEC-reported)."""
        facts = [_make_fact(data_source=DataSource.DEMO)]
        chunks = [_make_chunk(data_source=DataSource.DEMO)]
        claims = VerificationAgent().verify_claims(
            "What was Apple's revenue in Q1 2024?", facts, chunks
        )
        numerical = next(c for c in claims if c.claim_id.startswith("claim-num-"))
        assert numerical.status == ClaimVerificationStatus.UNVERIFIED
        assert numerical.numerical_value == 100000000.0
        assert "generated demo" in numerical.verification_notes

    def test_sec_exact_match_with_citation_is_verified(self):
        """SEC fact with matching same-source/same-period chunk → VERIFIED."""
        facts = [_make_fact(data_source=DataSource.SEC_EDGAR)]
        chunks = [_make_chunk(data_source=DataSource.SEC_EDGAR)]
        claims = VerificationAgent().verify_claims(
            "What was Apple's revenue in Q1 2024?", facts, chunks
        )
        numerical = next(c for c in claims if c.claim_id.startswith("claim-num-"))
        assert numerical.status == ClaimVerificationStatus.VERIFIED
        assert numerical.numerical_value == 100000000.0
        assert len(numerical.citations) == 1

    def test_sec_fact_without_citation_is_unverified(self):
        """SEC fact without matching chunk → UNVERIFIED (no filing-text context)."""
        facts = [_make_fact(data_source=DataSource.SEC_EDGAR)]
        # Chunk has different period — no match for the fact's Q1 period.
        chunks = [_make_chunk(period="FY", data_source=DataSource.SEC_EDGAR)]
        claims = VerificationAgent().verify_claims(
            "What was Apple's revenue in Q1 2024?", facts, chunks
        )
        numerical = next(c for c in claims if c.claim_id.startswith("claim-num-"))
        assert numerical.status == ClaimVerificationStatus.UNVERIFIED
        assert numerical.numerical_value == 100000000.0
        assert "no matching source passage" in numerical.verification_notes

    def test_missing_fact_is_unverified_none_value(self):
        """No matching fact for requested period → UNVERIFIED with None value."""
        facts = [_make_fact(year=2023, period="FY")]  # Not Q1 2024
        chunks = [_make_chunk()]
        claims = VerificationAgent().verify_claims(
            "What was Apple's revenue in Q1 2024?", facts, chunks
        )
        numerical = next(c for c in claims if c.claim_id.startswith("claim-num-"))
        assert numerical.status == ClaimVerificationStatus.UNVERIFIED
        assert numerical.numerical_value is None

    def test_ambiguous_facts_is_ambiguous(self):
        """Multiple facts with different values for same period → AMBIGUOUS."""
        facts = [
            _make_fact(value=100000000.0),
            _make_fact(value=200000000.0, fact_id="dup"),
        ]
        chunks = [_make_chunk()]
        claims = VerificationAgent().verify_claims(
            "What was Apple's revenue in Q1 2024?", facts, chunks
        )
        numerical = next(c for c in claims if c.claim_id.startswith("claim-num-"))
        assert numerical.status == ClaimVerificationStatus.AMBIGUOUS
        assert numerical.numerical_value is None

    def test_out_of_domain_is_single_unverified(self):
        """Out-of-domain question → single UNVERIFIED claim."""
        claims = VerificationAgent().verify_claims("What is the moon made of?", [], [])
        assert len(claims) == 1
        assert claims[0].claim_id == "claim-out-of-domain"
        assert claims[0].status == ClaimVerificationStatus.UNVERIFIED
        assert claims[0].numerical_value is None


class TestQuarterlyExtraction:
    """Tests that quarterly numerical values surface correctly in extraction."""

    def test_q1_quarter_value_surfaces(self):
        """Q1 2024 revenue fact is extractable as a period value."""
        from src.agents.extraction import FinancialExtractionAgent

        facts = [
            _make_fact(year=2024, period="Q1", value=90000000000.0),
            _make_fact(year=2024, period="Q2", value=95000000000.0),
            _make_fact(year=2024, period="Q3", value=100000000000.0),
            _make_fact(year=2024, period="FY", value=385000000000.0),
        ]
        comparisons = FinancialExtractionAgent().extract_metrics(facts)
        rev = next(c for c in comparisons if c.concept == "Revenues")
        assert "2024-Q1" in rev.periods
        assert rev.periods["2024-Q1"] == 90000000000.0
        assert rev.periods["2024-Q2"] == 95000000000.0
        assert rev.periods["2024-Q3"] == 100000000000.0
        assert rev.periods["2024-FY"] == 385000000000.0

    def test_yoy_only_when_both_fy_exist(self):
        """YoY change computed only when both FY periods exist."""
        from src.agents.extraction import FinancialExtractionAgent

        # Only 2024-FY → no YoY
        facts = [_make_fact(year=2024, period="FY", value=385000000000.0)]
        comparisons = FinancialExtractionAgent().extract_metrics(facts)
        rev = comparisons[0]
        assert rev.yoy_change_pct is None

        # Both FYs → YoY computed
        facts = [
            _make_fact(year=2023, period="FY", value=350000000000.0),
            _make_fact(year=2024, period="FY", value=385000000000.0),
        ]
        comparisons = FinancialExtractionAgent().extract_metrics(facts)
        rev = comparisons[0]
        assert rev.yoy_change_pct == 10.0  # (385-350)/350 * 100

    def test_qoq_only_when_two_quarters_exist(self):
        """QoQ change computed only when at least two quarters exist."""
        from src.agents.extraction import FinancialExtractionAgent

        # Only Q1 → no QoQ
        facts = [_make_fact(year=2024, period="Q1", value=90000000000.0)]
        comparisons = FinancialExtractionAgent().extract_metrics(facts)
        rev = comparisons[0]
        assert rev.qoq_change_pct is None

        # Q1 and Q2 → QoQ computed
        facts = [
            _make_fact(year=2024, period="Q1", value=90000000000.0),
            _make_fact(year=2024, period="Q2", value=95000000000.0),
        ]
        comparisons = FinancialExtractionAgent().extract_metrics(facts)
        rev = comparisons[0]
        assert rev.qoq_change_pct == 5.56  # (95-90)/90 * 100

    def test_division_by_zero_guarded(self):
        """Zero denominator → None change, not crash."""
        from src.agents.extraction import FinancialExtractionAgent

        facts = [
            _make_fact(year=2023, period="FY", value=0.0),
            _make_fact(year=2024, period="FY", value=100000000.0),
        ]
        comparisons = FinancialExtractionAgent().extract_metrics(facts)
        rev = comparisons[0]
        assert rev.yoy_change_pct is None
