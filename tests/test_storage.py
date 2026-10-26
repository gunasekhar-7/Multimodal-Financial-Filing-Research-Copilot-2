import pytest
import os
import sqlite3
from src.schemas.financial import CompanyInfo, XBRLFact, DocumentChunk, SearchQuery, FilingType, SectorType
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
        is_restated=False
    )
    temp_db.insert_xbrl_facts([fact])
    results = temp_db.query_xbrl_facts(ticker="TEST", concept="Revenues", year=2024, period="Q1")
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
        source_url="https://sec.gov"
    )
    temp_db.insert_document_chunks([chunk])
    query = SearchQuery(query="services growth", tickers=["AAPL"], top_k=5)
    results = temp_db.search_bm25(query)
    assert len(results) > 0
    assert "iPhone and services growth" in results[0].chunk.content
