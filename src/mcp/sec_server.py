import json
import logging
from typing import Dict, Any, List
from src.storage.database import DatabaseStorage
from src.retrieval.hybrid_search import HybridSearchEngine
from src.schemas.financial import SearchQuery

logger = logging.getLogger(__name__)

class SECMCPTools:
    def __init__(self, db: DatabaseStorage):
        self.db = db
        self.search_engine = HybridSearchEngine(self.db)

    def list_companies(self) -> List[Dict[str, Any]]:
        companies = self.db.get_all_companies()
        return [c.model_dump() for c in companies]

    def get_xbrl_facts(self, ticker: str, concept: str = None, year: int = None) -> List[Dict[str, Any]]:
        facts = self.db.query_xbrl_facts(ticker=ticker, concept=concept, year=year)
        return [f.model_dump() for f in facts]

    def search_sec_filings(self, query: str, ticker: str = None, top_k: int = 5) -> List[Dict[str, Any]]:
        tickers = [ticker] if ticker else None
        q = SearchQuery(query=query, tickers=tickers, top_k=top_k)
        results = self.search_engine.search(q)
        return [
            {
                "chunk_id": r.chunk.chunk_id,
                "ticker": r.chunk.ticker,
                "filing_type": r.chunk.filing_type.value,
                "fiscal_year": r.chunk.fiscal_year,
                "fiscal_period": r.chunk.fiscal_period,
                "page_number": r.chunk.page_number,
                "section": r.chunk.item_section,
                "score": r.score,
                "content": r.chunk.content,
                "source_url": r.chunk.source_url
            } for r in results
        ]
