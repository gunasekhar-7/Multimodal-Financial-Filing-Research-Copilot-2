from src.retrieval.hybrid_search import HybridSearchEngine
from src.schemas.financial import DataSource, SearchQuery, SearchResultItem, XBRLFact
from src.storage.database import DatabaseStorage


class RetrievalAgent:
    def __init__(self, db: DatabaseStorage, search_engine: HybridSearchEngine):
        self.db = db
        self.search_engine = search_engine

    def retrieve_chunks(
        self,
        question: str,
        tickers: list[str],
        top_k: int = 10,
        sections: list[str] | None = None,
        data_source: DataSource | None = None,
    ) -> list[SearchResultItem]:
        query = SearchQuery(
            query=question,
            tickers=tickers,
            top_k=top_k,
            sections=sections or None,
        )
        return self.search_engine.search(query, data_source=data_source)

    def retrieve_facts(
        self, tickers: list[str], data_source: DataSource | None = None
    ) -> list[XBRLFact]:
        all_facts = []
        for ticker in tickers:
            facts = self.db.query_xbrl_facts(ticker=ticker, data_source=data_source)
            all_facts.extend(facts)
        return all_facts
