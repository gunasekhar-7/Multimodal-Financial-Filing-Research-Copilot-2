import os

import pytest

from src.retrieval.hybrid_search import HybridSearchEngine
from src.schemas.financial import DataSource, DocumentChunk, FilingType, SearchQuery
from src.storage.database import DatabaseStorage


@pytest.fixture
def populated_db(tmp_path):
    db_file = os.path.join(tmp_path, "test_retrieval.db")
    db = DatabaseStorage(db_path=db_file)
    chunks = [
        DocumentChunk(
            chunk_id="AAPL-2024-Q1-c1",
            ticker="AAPL",
            cik="0000320193",
            filing_type=FilingType.FORM_10Q,
            fiscal_year=2024,
            fiscal_period="Q1",
            filed_date="2024-03-31",
            accession_number="0000320193-24-001",
            item_section="Item 7. MD&A",
            page_number=12,
            content="Apple iPhone sales grew 15% year-over-year in Q1 2024.",
            is_table=False,
            source_url="https://sec.gov",
        ),
        DocumentChunk(
            chunk_id="MSFT-2024-Q1-c1",
            ticker="MSFT",
            cik="0000789019",
            filing_type=FilingType.FORM_10Q,
            fiscal_year=2024,
            fiscal_period="Q1",
            filed_date="2024-03-31",
            accession_number="0000789019-24-001",
            item_section="Item 7. MD&A",
            page_number=14,
            content="Microsoft Azure cloud revenue reached $25 billion with 30% growth.",
            is_table=True,
            table_data={"AzureRevenue": 25000000000.0},
            source_url="https://sec.gov",
        ),
    ]
    db.insert_document_chunks(chunks)
    return db


def test_dense_vector_search(populated_db):
    engine = HybridSearchEngine(populated_db)
    query = SearchQuery(query="Azure cloud revenue", tickers=["MSFT"], top_k=5)
    results = engine.search(query)
    assert len(results) > 0
    assert results[0].chunk.ticker == "MSFT"
    assert "Azure cloud revenue" in results[0].chunk.content


def test_hybrid_search_filtering(populated_db):
    engine = HybridSearchEngine(populated_db)
    query = SearchQuery(query="iPhone sales", tickers=["AAPL"], top_k=5)
    results = engine.search(query)
    assert len(results) > 0
    assert results[0].chunk.ticker == "AAPL"


def test_dense_index_refreshes_after_reseed_without_restart(tmp_path):
    """The dense TF-IDF index must refresh when the DB is reseeded, without
    restarting the HybridSearchEngine process."""
    db_file = os.path.join(tmp_path, "test_refresh.db")
    db = DatabaseStorage(db_path=db_file)

    old_chunk = DocumentChunk(
        chunk_id="TEST-refresh-1",
        ticker="AAPL",
        cik="0000320193",
        filing_type=FilingType.FORM_10Q,
        fiscal_year=2024,
        fiscal_period="Q1",
        filed_date="2024-03-31",
        accession_number="0000320193-24-001",
        item_section="Item 7. MD&A",
        page_number=12,
        content="Apple iPhone sales grew 15% year-over-year in Q1 2024.",
        is_table=False,
        source_url="https://sec.gov",
    )
    db.insert_document_chunks([old_chunk])

    engine = HybridSearchEngine(db)
    before = engine.search(SearchQuery(query="iPhone sales", tickers=["AAPL"], top_k=5))
    assert len(before) > 0
    assert "iPhone sales" in before[0].chunk.content

    # Reseed with new content for the same chunk (simulates DB reseed).
    new_chunk = DocumentChunk(
        chunk_id="TEST-refresh-1",
        ticker="AAPL",
        cik="0000320193",
        filing_type=FilingType.FORM_10Q,
        fiscal_year=2024,
        fiscal_period="Q1",
        filed_date="2024-03-31",
        accession_number="0000320193-24-001",
        item_section="Item 7. MD&A",
        page_number=12,
        content="Microsoft Azure cloud revenue reached $25 billion with 30% growth.",
        is_table=False,
        source_url="https://sec.gov",
    )
    db.insert_document_chunks([new_chunk])

    # Same engine instance, no restart — dense index must refresh.
    after = engine.search(
        SearchQuery(query="Azure cloud revenue", tickers=["AAPL"], top_k=5)
    )
    assert len(after) > 0
    assert "Azure cloud revenue" in after[0].chunk.content
    assert "iPhone sales" not in after[0].chunk.content


def test_hybrid_search_filters_provenance_before_top_k(populated_db):
    sec_chunk = DocumentChunk(
        chunk_id="AAPL-2024-Q1-sec",
        ticker="AAPL",
        cik="0000320193",
        filing_type=FilingType.FORM_10Q,
        fiscal_year=2024,
        fiscal_period="Q1",
        filed_date="2024-04-15",
        accession_number="sec-1",
        item_section="Item 7. MD&A",
        page_number=1,
        content="Apple iPhone sales grew 15% year-over-year in Q1 2024.",
        source_url="https://www.sec.gov/Archives/filing",
        data_source=DataSource.SEC_EDGAR,
    )
    populated_db.insert_document_chunks([sec_chunk])
    results = HybridSearchEngine(populated_db).search(
        SearchQuery(query="iPhone sales", tickers=["AAPL"], top_k=1),
        data_source=DataSource.SEC_EDGAR,
    )
    assert len(results) == 1
    assert results[0].chunk.data_source == DataSource.SEC_EDGAR
    assert results[0].chunk.chunk_id == sec_chunk.chunk_id
