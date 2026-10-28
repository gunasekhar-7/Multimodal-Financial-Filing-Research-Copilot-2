import numpy as np
from typing import List, Dict, Any
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from src.schemas.financial import SearchQuery, SearchResultItem, DocumentChunk

class DenseVectorSearch:
    def __init__(self):
        self.vectorizer = TfidfVectorizer(ngram_range=(1, 2), max_features=10000, stop_words='english')
        self.doc_vectors = None
        self.chunks = []

    def refresh(self, chunks: List[DocumentChunk]):
        """Refresh the index with new chunks (e.g., after DB reseed)."""
        self.chunks = chunks
        corpus = [c.content for c in chunks]
        self.doc_vectors = self.vectorizer.fit_transform(corpus)

    def search(self, query: SearchQuery) -> List[SearchResultItem]:
        if not self.chunks or self.doc_vectors is None:
            return []

        query_vec = self.vectorizer.transform([query.query])
        similarities = cosine_similarity(query_vec, self.doc_vectors)[0]

        # Filter by tickers if specified
        results: List[SearchResultItem] = []
        ticker_filter = [t.upper() for t in query.tickers] if query.tickers else None
        section_filter = [s.lower() for s in query.sections if isinstance(s, str) and s.strip()] if query.sections else None
        for idx, sim in enumerate(similarities):
            chunk = self.chunks[idx]
            if ticker_filter and chunk.ticker.upper() not in ticker_filter:
                continue
            if query.fiscal_years and chunk.fiscal_year not in query.fiscal_years:
                continue
            if query.fiscal_periods and chunk.fiscal_period not in query.fiscal_periods:
                continue
            if section_filter and not any(
                chunk.item_section.lower().startswith(prefix) for prefix in section_filter
            ):
                continue
            if sim > 0.0:
                # chunk here is an already-validated DocumentChunk stored in the index, so
                # construct in wrap mode to avoid re-validating the inner model on every hit.
                results.append(SearchResultItem.model_construct(
                    chunk=chunk,
                    score=float(sim),
                    retrieval_method="dense_vector",
                ))

        results.sort(key=lambda x: x.score, reverse=True)
        return results[:query.top_k]
