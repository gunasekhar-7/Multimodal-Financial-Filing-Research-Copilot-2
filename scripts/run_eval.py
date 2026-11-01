import json
import logging
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.eval.evaluator import BenchmarkEvaluator

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def run():
    logger.info("Starting Financial Research Copilot Benchmark Evaluation...")
    db_path = os.getenv("DATABASE_PATH", "financial_copilot.db")
    if not os.path.exists(db_path):
        from scripts.seed_database import seed

        seed()
    evaluator = BenchmarkEvaluator()
    results = evaluator.evaluate()  # Run the complete checked-in dataset

    logger.info("\n" + "=" * 50)
    logger.info("EVALUATION BENCHMARK RESULTS")
    logger.info("=" * 50)
    logger.info(f"Total Evaluated Questions: {results.total_questions}")
    logger.info(f"Retrieval Recall@5:       {results.recall_at_k}%")
    logger.info(f"Retrieval MRR:             {results.mrr}%")
    logger.info(f"Numerical Accuracy:        {results.numerical_accuracy_pct}%")
    logger.info(f"Citation Resolution Rate:  {results.citation_resolution_rate_pct}%")
    logger.info(f"Claim Faithfulness Rate:   {results.claim_faithfulness_rate_pct}%")
    logger.info(f"Latency p50:               {results.latency_p50_sec}s")
    logger.info(f"Latency p95:               {results.latency_p95_sec}s")
    logger.info("=" * 50)

    # Save metrics JSON artifact for CI/CD gates
    artifact_path = os.getenv("EVAL_RESULTS_PATH", "eval_results.json")
    with open(artifact_path, "w", encoding="utf-8") as f:
        json.dump(results.model_dump(), f, indent=2)
    logger.info(f"Saved evaluation result artifact to {artifact_path}")


if __name__ == "__main__":
    run()
