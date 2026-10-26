from typing import List, Dict, Any
from src.schemas.financial import SearchQuery, SearchResultItem, DocumentChunk
from src.storage.database import DatabaseStorage
from src.retrieval.dense_search import DenseVectorSearch
from src.retrieval.reranker import CrossEncoderReranker

def reciprocal_rank_fusion(bm25_results: List[SearchResultItem], dense_results: List[SearchResultItem], k: int = 60) -> List[SearchResultItem]:
    scores: Dict[str, float] = {}
    chunks_map: Dict[str, DocumentChunk] = {}

    # Rank BM25
    for rank, item in enumerate(bm25_results):
        cid = item.chunk.chunk_id
        chunks_map[cid] = item.chunk
        scores[cid] = scores.get(cid, 0.0) + (1.0 / (k + rank + 1))

    # Rank Dense
    for rank, item in enumerate(dense_results):
        cid = item.chunk.chunk_id
        chunks_map[cid] = item.chunk
        scores[cid] = scores.get(cid, 0.0) + (1.0 / (k + rank + 1))

    fused_results = []
    for cid, rrf_score in scores.items():
        fused_results.append(SearchResultItem(
            chunk=chunks_map[cid],
            score=round(rrf_score, 6),
            retrieval_method="rrf_hybrid"
        ))

    fused_results.sort(key=lambda x: x.score, reverse=True)
    return fused_results

class HybridSearchEngine:
    def __init__(self, db: DatabaseStorage):
        self.db = db
        self.reranker = CrossEncoderReranker()
        self._load_dense_index()

    def _load_dense_index(self):
        # Load chunks from DB for dense indexing
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM document_chunks")
            rows = cursor.fetchall()

            chunks = []
            for r in rows:
                chunks.append(DocumentChunk(
                    chunk_id=r["chunk_id"],
                    ticker=r["ticker"],
                    cik=r["cik"],
                    filing_type=r["filing_type"],
                    fiscal_year=r["fiscal_year"],
                    fiscal_period=r["fiscal_period"],
                    filed_date=r["filed_date"],
                    accession_number=r["accession_number"],
                    item_section=r["item_section"],
                    page_number=r["page_number"],
                    content=r["content"],
                    is_table=bool(r["is_table"]),
                    source_url=r["source_url"]
                ))
            self.dense_search = DenseVectorSearch(chunks)

    def search(self, query: SearchQuery) -> List[SearchResultItem]:
        bm25_res = self.db.search_bm25(query)
        dense_res = self.dense_search.search(query)

        fused_res = reciprocal_rank_fusion(bm25_res, dense_res)
        final_reranked = self.reranker.rerank(query.query, fused_res, top_k=query.top_k)
        return final_reranked
