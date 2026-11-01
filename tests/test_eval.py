from src.eval.evaluator import BenchmarkEvaluator


def test_evaluator_runs_sample(tmp_path):
    from src.ingestion.companies import TARGET_COMPANIES
    from src.ingestion.sec_client import SECDataIngestionClient
    from src.storage.database import DatabaseStorage

    db = DatabaseStorage(str(tmp_path / "eval.db"))
    client = SECDataIngestionClient(data_mode="demo")
    company = TARGET_COMPANIES[0]
    db.replace_seed_data(
        client.fetch_company_facts(company), client.fetch_document_chunks(company)
    )
    evaluator = BenchmarkEvaluator(db=db)
    res = evaluator.evaluate(sample_limit=3)
    assert res.total_questions == 3
    assert res.citation_resolution_rate_pct >= 0.0
    assert res.claim_faithfulness_rate_pct == 0.0
    assert res.latency_p50_sec >= 0.0
