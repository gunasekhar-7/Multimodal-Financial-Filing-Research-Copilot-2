import json
import os
import time
from typing import Any

import numpy as np
from pydantic import BaseModel

from src.agents.orchestrator import ResearchOrchestrator
from src.schemas.financial import DataSource, SearchQuery
from src.schemas.reports import ClaimVerificationStatus
from src.storage.database import DatabaseStorage


class EvaluationResult(BaseModel):
    total_questions: int
    recall_at_k: float
    mrr: float
    numerical_accuracy_pct: float
    citation_resolution_rate_pct: float
    claim_faithfulness_rate_pct: float
    latency_p50_sec: float
    latency_p95_sec: float
    category_breakdown: dict[str, dict[str, float]]


class BenchmarkEvaluator:
    def __init__(
        self, db: DatabaseStorage | None = None, dataset_path: str | None = None
    ):
        self.db = db or DatabaseStorage()
        self.orchestrator = ResearchOrchestrator(db=self.db)
        if dataset_path is None:
            dataset_path = os.path.join(
                os.path.dirname(__file__), "golden_dataset.json"
            )
        self.dataset_path = dataset_path

    def load_dataset(self) -> list[dict[str, Any]]:
        with open(self.dataset_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def evaluate(self, sample_limit: int | None = None) -> EvaluationResult:
        dataset = self.load_dataset()
        if sample_limit and sample_limit < len(dataset):
            dataset = dataset[:sample_limit]

        if not dataset:
            raise ValueError("Evaluation dataset is empty; no metrics can be computed.")
        ranks = []
        hits_at_k = 0
        k = 5

        numerical_correct = 0
        numerical_total = 0

        citation_resolved = 0
        citation_total = 0
        faithful_claims = 0
        claims_total = 0

        latencies = []
        category_stats: dict[str, dict[str, Any]] = {}

        for item in dataset:
            cat = item.get("category", "general")
            if cat not in category_stats:
                category_stats[cat] = {
                    "count": 0,
                    "hits": 0,
                    "num_correct": 0,
                    "num_total": 0,
                }

            category_stats[cat]["count"] += 1

            start_time = time.time()

            if item.get("expected_data_source", "demo") != "demo":
                raise ValueError(
                    "This benchmark is defined only for the deterministic demo data source."
                )

            # Evaluate Retrieval Quality (Recall@k & MRR)
            ticker = item["expected_ticker"]
            q = SearchQuery(
                query=item["question"],
                tickers=[ticker],
                top_k=k,
                sections=[item["expected_item_section"]]
                if item.get("expected_item_section")
                else None,
            )
            retrieved = self.orchestrator.search_engine.search(q)
            all_source_chunks = self.orchestrator.search_engine._get_all_chunks()
            source_chunks_by_id = {chunk.chunk_id: chunk for chunk in all_source_chunks}

            rank = 0
            for idx, res in enumerate(retrieved):
                expected_sec = item.get("expected_item_section")
                if (
                    expected_sec
                    and expected_sec.lower() in res.chunk.item_section.lower()
                ):
                    rank = idx + 1
                    break

            if rank > 0:
                hits_at_k += 1
                ranks.append(1.0 / rank)
                category_stats[cat]["hits"] += 1
            else:
                ranks.append(0.0)

            # Evaluate Orchestrated Agent Analysis
            report = self.orchestrator.run(item["question"], default_ticker=ticker)
            elapsed = time.time() - start_time
            latencies.append(elapsed)

            # Numerical accuracy check
            if item.get("expected_numerical_value") is not None:
                numerical_total += 1
                category_stats[cat]["num_total"] += 1
                expected_val = item["expected_numerical_value"]

                # Check claims
                matched = False
                for claim in report.claims:
                    if (
                        claim.status == ClaimVerificationStatus.UNVERIFIED
                        and claim.numerical_value is not None
                    ):
                        diff = abs(claim.numerical_value - expected_val) / max(
                            1.0, abs(expected_val)
                        )
                        if diff <= item.get("tolerance_pct", 0.01):
                            matched = True
                            break
                if matched:
                    numerical_correct += 1
                    category_stats[cat]["num_correct"] += 1

            # Citation resolution check
            for cite in report.citations:
                citation_total += 1
                chunk_id = cite.citation_id.removeprefix("cite-")
                source_chunk = source_chunks_by_id.get(chunk_id)
                if (
                    source_chunk is not None
                    and cite.data_source == source_chunk.data_source
                    and len(cite.excerpt) >= 20
                    and cite.excerpt in source_chunk.content
                    and (
                        (
                            cite.data_source == DataSource.SEC_EDGAR
                            and cite.source_url.startswith("https://www.sec.gov/")
                        )
                        or (
                            cite.data_source == DataSource.DEMO
                            and cite.source_url.startswith("demo://")
                        )
                    )
                ):
                    citation_resolved += 1

            # Claim faithfulness check
            for claim in report.claims:
                claims_total += 1
                if (
                    claim.status == ClaimVerificationStatus.VERIFIED
                    and len(claim.citations) > 0
                    and all(
                        citation.data_source == DataSource.SEC_EDGAR
                        for citation in claim.citations
                    )
                    and (
                        claim.numerical_value is None
                        or claim.numerical_value == claim.expected_xbrl_value
                    )
                ):
                    faithful_claims += 1

        recall_at_k = round((hits_at_k / max(1, len(dataset))) * 100.0, 2)
        mrr = round(float(np.mean(ranks)) * 100.0, 2) if ranks else 0.0
        num_acc = round((numerical_correct / max(1, numerical_total)) * 100.0, 2)
        cite_rate = round((citation_resolved / max(1, citation_total)) * 100.0, 2)
        faith_rate = round((faithful_claims / max(1, claims_total)) * 100.0, 2)

        p50 = round(float(np.percentile(latencies, 50)), 3) if latencies else 0.0
        p95 = round(float(np.percentile(latencies, 95)), 3) if latencies else 0.0

        cat_breakdown = {}
        for c, stats in category_stats.items():
            cat_breakdown[c] = {
                "count": float(stats["count"]),
                "recall_at_k": round(
                    (stats["hits"] / max(1, stats["count"])) * 100.0, 2
                ),
                "numerical_accuracy": round(
                    (stats["num_correct"] / max(1, stats["num_total"])) * 100.0, 2
                )
                if stats["num_total"] > 0
                else 0.0,
            }

        return EvaluationResult(
            total_questions=len(dataset),
            recall_at_k=recall_at_k,
            mrr=mrr,
            numerical_accuracy_pct=num_acc,
            citation_resolution_rate_pct=cite_rate,
            claim_faithfulness_rate_pct=faith_rate,
            latency_p50_sec=p50,
            latency_p95_sec=p95,
            category_breakdown=cat_breakdown,
        )
