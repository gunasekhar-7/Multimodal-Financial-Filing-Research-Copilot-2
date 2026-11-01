import os

import pytest

from src.schemas.financial import (
    DocumentChunk,
    FilingType,
    SearchQuery,
    XBRLFact,
)
from src.storage.database import DatabaseStorage


@pytest.fixture
def temp_db(tmp_path):
    db_file = os.path.join(tmp_path, "test.db")
    db = DatabaseStorage(db_path=db_file)
    return db


def test_database_initialization(temp_db):
    companies = temp_db.get_all_companies()
    assert len(companies) >= 25
    assert any(c.ticker == "AAPL" for c in companies)


def test_insert_and_query_xbrl_facts(temp_db):
    fact = XBRLFact(
        fact_id="TEST-2024-Q1-Revenues",
        ticker="TEST",
        cik="0000000000",
        entity_name="Test Inc",
        concept="Revenues",
        taxonomy="us-gaap",
        label="Revenues",
        value=1000000.0,
        unit="USD",
        fiscal_year=2024,
        fiscal_period="Q1",
        form="10-Q",
        filed_date="2024-04-15",
        period_end="2024-03-31",
        is_restated=False,
    )
    temp_db.insert_xbrl_facts([fact])
    results = temp_db.query_xbrl_facts(
        ticker="TEST", concept="Revenues", year=2024, period="Q1"
    )
    assert len(results) == 1
    assert results[0].value == 1000000.0


def test_search_bm25_documents(temp_db):
    chunk = DocumentChunk(
        chunk_id="TEST-2024-chunk1",
        ticker="AAPL",
        cik="0000320193",
        filing_type=FilingType.FORM_10Q,
        fiscal_year=2024,
        fiscal_period="Q1",
        filed_date="2024-03-31",
        accession_number="0000320193-24-001",
        item_section="Item 7. MD&A",
        page_number=10,
        content="Apple reported strong iPhone and services growth in China.",
        is_table=False,
        source_url="https://sec.gov",
    )
    temp_db.insert_document_chunks([chunk])
    query = SearchQuery(query="services growth", tickers=["AAPL"], top_k=5)
    results = temp_db.search_bm25(query)
    assert len(results) > 0
    assert "iPhone and services growth" in results[0].chunk.content


def test_reinserting_chunk_keeps_fts_index_idempotent(temp_db):
    chunk = DocumentChunk(
        chunk_id="AAPL-2024-Q1-repeat",
        ticker="AAPL",
        cik="0000320193",
        filing_type=FilingType.FORM_10Q,
        fiscal_year=2024,
        fiscal_period="Q1",
        filed_date="2024-04-15",
        accession_number="0000320193-24-001",
        item_section="Item 7. MD&A",
        page_number=1,
        content="Revenue outlook remains stable across the fiscal period.",
        source_url="demo://AAPL/2024/Q1",
    )
    query = SearchQuery(query="revenue outlook", tickers=["AAPL"], top_k=10)
    temp_db.insert_document_chunks([chunk])
    before = temp_db.search_bm25(query)
    temp_db.insert_document_chunks([chunk])
    after = temp_db.search_bm25(query)
    with temp_db.get_connection() as conn:
        indexed = conn.execute(
            "SELECT COUNT(*) FROM document_chunks_fts WHERE chunk_id = ?",
            (chunk.chunk_id,),
        ).fetchone()[0]
    assert indexed == 1
    assert [item.chunk.chunk_id for item in after] == [
        item.chunk.chunk_id for item in before
    ]


def test_like_fallback_preserves_period_filter(temp_db):
    chunks = [
        DocumentChunk(
            chunk_id=f"AAPL-{year}-Q1-fallback",
            ticker="AAPL",
            cik="0000320193",
            filing_type=FilingType.FORM_10Q,
            fiscal_year=year,
            fiscal_period="Q1",
            filed_date=f"{year}-04-15",
            accession_number=f"a-{year}",
            item_section="Item 7. MD&A",
            page_number=1,
            content="Annual filing source passage.",
            source_url="demo://AAPL",
        )
        for year in (2023, 2024)
    ]
    temp_db.insert_document_chunks(chunks)
    results = temp_db.search_bm25(
        SearchQuery(
            query="*",
            tickers=["AAPL"],
            fiscal_years=[2023],
            top_k=10,
        )
    )
    assert results
    assert {item.chunk.fiscal_year for item in results} == {2023}


def test_replace_seed_data_is_repeatable(temp_db):
    from src.ingestion.companies import TARGET_COMPANIES
    from src.ingestion.sec_client import SECDataIngestionClient

    client = SECDataIngestionClient(data_mode="demo")
    company = TARGET_COMPANIES[0]
    facts = client.fetch_company_facts(company)
    chunks = client.fetch_document_chunks(company)
    temp_db.replace_seed_data(facts, chunks)
    first_counts = (temp_db.get_fact_count(), temp_db.get_chunk_count())
    temp_db.replace_seed_data(facts, chunks)
    second_counts = (temp_db.get_fact_count(), temp_db.get_chunk_count())
    with temp_db.get_connection() as conn:
        fts_count = conn.execute("SELECT COUNT(*) FROM document_chunks_fts").fetchone()[
            0
        ]
    assert first_counts == second_counts == (len(facts), len(chunks))
    assert fts_count == len(chunks)


def test_provenance_round_trips_through_sqlite(temp_db):
    from src.schemas.financial import DataSource

    fact = XBRLFact(
        fact_id="LIVE-2024-FY-Revenues",
        ticker="LIVE",
        cik="0000000000",
        entity_name="Live Corp",
        concept="Revenues",
        label="Revenues",
        value=1,
        fiscal_year=2024,
        fiscal_period="FY",
        form="10-K",
        filed_date="2025-01-01",
        period_end="2024-12-31",
        data_source=DataSource.SEC_EDGAR,
    )
    temp_db.insert_xbrl_facts([fact])
    loaded = temp_db.query_xbrl_facts("LIVE")
    assert loaded[0].data_source == DataSource.SEC_EDGAR
