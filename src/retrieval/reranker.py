import re
from typing import List
from src.schemas.financial import SearchResultItem

class CrossEncoderReranker:
    def __init__(self):
        pass

    def rerank(self, query: str, items: List[SearchResultItem], top_k: int = 10) -> List[SearchResultItem]:
        if not items:
            return []

        query_terms = set(re.findall(r'\w+', query.lower()))

        reranked = []
        for item in items:
            base_score = item.score
            content_lower = item.chunk.content.lower()

            # Match term density
            matches = sum(1 for term in query_terms if term in content_lower)
            term_ratio = matches / max(1, len(query_terms))

            # Boost if chunk contains financial tabular structures or key metric terms
            table_boost = 1.25 if item.chunk.is_table else 1.0

            # Specific financial metric keywords boost
            metric_boost = 1.15 if any(k in content_lower for k in ["revenue", "net income", "eps", "gross profit", "operating income"]) else 1.0

            final_score = base_score * (1.0 + term_ratio) * table_boost * metric_boost

            reranked.append(SearchResultItem(
                chunk=item.chunk,
                score=round(final_score, 4),
                retrieval_method=f"{item.retrieval_method}+reranked"
            ))

        reranked.sort(key=lambda x: x.score, reverse=True)
        return reranked[:top_k]
