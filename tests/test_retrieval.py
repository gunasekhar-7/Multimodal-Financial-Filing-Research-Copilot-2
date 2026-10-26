import pytest
import os
from src.schemas.financial import SearchQuery, DocumentChunk, FilingType
from src.storage.database import DatabaseStorage
from src.retrieval.dense_search import DenseVectorSearch
from src.retrieval.hybrid_search import HybridSearchEngine

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
            source_url="https://sec.gov"
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
            source_url="https://sec.gov"
        )
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
