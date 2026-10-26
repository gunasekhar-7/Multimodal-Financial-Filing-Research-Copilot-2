import pytest
import os
from src.eval.evaluator import BenchmarkEvaluator

def test_evaluator_runs_sample():
    evaluator = BenchmarkEvaluator()
    res = evaluator.evaluate(sample_limit=3)
    assert res.total_questions == 3
    assert res.citation_resolution_rate_pct >= 0.0
    assert res.latency_p50_sec >= 0.0
