from typing import List
from src.schemas.financial import SearchQuery, SearchResultItem, XBRLFact
from src.storage.database import DatabaseStorage
from src.retrieval.hybrid_search import HybridSearchEngine

class RetrievalAgent:
    def __init__(self, db: DatabaseStorage, search_engine: HybridSearchEngine):
        self.db = db
        self.search_engine = search_engine

    def retrieve_chunks(self, question: str, tickers: List[str], top_k: int = 10) -> List[SearchResultItem]:
        query = SearchQuery(
            query=question,
            tickers=tickers,
            top_k=top_k
        )
        return self.search_engine.search(query)

    def retrieve_facts(self, tickers: List[str]) -> List[XBRLFact]:
        all_facts = []
        for ticker in tickers:
            facts = self.db.query_xbrl_facts(ticker=ticker)
            all_facts.extend(facts)
        return all_facts
