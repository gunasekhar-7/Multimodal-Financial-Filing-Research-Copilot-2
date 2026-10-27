import time
import pytest
from src.schemas.financial import SearchQuery, SearchResultItem, FilingType
from src.storage.database import DatabaseStorage
from src.retrieval.hybrid_search import HybridSearchEngine


def test_retrieval_hot_path_avg_under_threshold(tmp_path):
    """The retrieval hot path (search -> RRF -> rerank) should stay cheap on a
    seeded corpus. Measured with the same shape the orchestrator uses."""
    db_file = str(tmp_path / "perf.db")
    db = DatabaseStorage(db_path=db_file)

    from src.schemas.financial import DocumentChunk

    db.insert_document_chunks(
        [
            DocumentChunk(
                chunk_id=f"chunk-{i}",
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
            for i in range(100)
        ]
    )

    engine = HybridSearchEngine(db)
    query = SearchQuery(query="revenue growth", tickers=["AAPL"], top_k=10)

    start = time.perf_counter()
    for _ in range(30):
        engine.search(query)
    elapsed = time.perf_counter() - start
    avg_ms = (elapsed / 30) * 1000.0

    # Keep the hot path cheap enough that it is not the systemic bottleneck on
    # the seeded corpus. This is a regression guard, not a benchmark promise.
    assert avg_ms < 25.0, (
        f"retrieval hot path regressed: {avg_ms:.2f} ms avg per search "
        f"(limit 25.0 ms)"
    )


def test_reranker_and_dense_results_are_valid_search_result_items(tmp_path):
    """SearchResultItem objects produced by the reranker and dense search must
    round-trip through Pydantic validation even when they were built in wrap
    mode for performance."""
    db_file = str(tmp_path / "valid.db")
    db = DatabaseStorage(db_path=db_file)

    from src.schemas.financial import DocumentChunk

    db.insert_document_chunks(
        [
            DocumentChunk(
                chunk_id="chunk-1",
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
        ]
    )

    engine = HybridSearchEngine(db)
    query = SearchQuery(query="iPhone", tickers=["AAPL"], top_k=5)
    results = engine.search(query)

    assert results, "expected at least one search result"
    for item in results:
        # model_construct (wrap mode) must still produce a valid instance.
        validated = SearchResultItem.model_validate(item.model_dump())
        assert validated.chunk.ticker == item.chunk.ticker
        assert validated.score == item.score
        assert validated.retrieval_method == item.retrieval_method
        assert validated.retrieval_method.endswith("+reranked") or (
            validated.retrieval_method in {"bm25", "dense_vector", "rrf_hybrid"}
        )
