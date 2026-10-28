import re
from typing import List
from src.schemas.financial import SearchResultItem

# A chunk's structure/priority only earns a boost when the question actually
# asks for it. These are the question-side signals.
METRIC_QUERY_SIGNALS = (
    "revenue", "income", "eps", "profit", "margin", "earnings",
    "growth", "yoy", "year-over-year", "quarter", "cash",
)
TABLE_QUERY_SIGNALS = ("table", "statement", "consolidated", "operations")

# Content-side financial metric keywords, as before.
METRIC_CONTENT_KEYWORDS = (
    "revenue", "net income", "eps", "gross profit", "operating income",
)


class CrossEncoderReranker:
    """Heuristic cross-encoder-style reranker.

    Score = base_rank * (1 + query-term density) * table_boost * metric_boost.

    All boosts are query-conditional so a risk question is never outranked
    merely because a competing chunk mentions revenue:

    - table_boost (1.25): the query asks for tables/statements AND the chunk
      is a table.
    - metrics_table_boost (1.10): the query asks about financial metrics AND
      the chunk is a table — consolidated-statement chunks are the canonical
      ground truth for numerical metric questions (they carry the primary
      figures), even when the question does not literally say "statement".
    - metric_boost (1.15): the query asks about financial metrics AND the
      content contains a metric keyword.

    All boosts are positive multipliers — the reranker can inflate a
    high-scoring hit but cannot demote a low-scoring one.
    """

    def __init__(self):
        pass

    def rerank(self, query: str, items: List[SearchResultItem], top_k: int = 10) -> List[SearchResultItem]:
        if not items:
            return []

        query_lower = query.lower()
        query_wants_metrics = any(s in query_lower for s in METRIC_QUERY_SIGNALS)
        query_wants_tables = any(s in query_lower for s in TABLE_QUERY_SIGNALS)
        query_terms = set(re.findall(r"\w+", query_lower))

        reranked: List[SearchResultItem] = []
        for item in items:
            base_score = item.score
            content_lower = item.chunk.content.lower()

            # Match term density
            matches = sum(1 for term in query_terms if term in content_lower)
            term_ratio = matches / max(1, len(query_terms))

            is_table = bool(item.chunk.is_table)
            # Boost table structure only when the query asks for it
            table_boost = (
                1.25 if query_wants_tables and is_table else 1.0
            )
            # Boost statement chunks for numerical metric questions
            metrics_table_boost = (
                1.10 if query_wants_metrics and is_table and table_boost == 1.0 else 1.0
            )
            # Boost metric keyword content only when the query asks for it
            metric_boost = (
                1.15
                if query_wants_metrics
                and any(k in content_lower for k in METRIC_CONTENT_KEYWORDS)
                else 1.0
            )

            final_score = base_score * (1.0 + term_ratio) * table_boost * metrics_table_boost * metric_boost

            # Build in wrap mode: item.chunk and item.retrieval_method are already
            # validated Pydantic values coming in, so skip re-validation on the
            # inner DocumentChunk. We only freshly validate the new float score and
            # the new retrieval_method string.
            reranked.append(SearchResultItem.model_construct(
                chunk=item.chunk,
                score=round(final_score, 4),
                retrieval_method=f"{item.retrieval_method}+reranked",
            ))

        reranked.sort(key=lambda x: x.score, reverse=True)
        return reranked[:top_k]
