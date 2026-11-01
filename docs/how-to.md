# How-to guides

## Run the automated test suite

Use a disposable database path so imports and tests cannot alter the tracked root database:

```bash
mkdir -p data
DATA_MODE=demo DATABASE_PATH=./data/test.db python scripts/seed_database.py
DATA_MODE=demo DATABASE_PATH=./data/test.db python -m pytest -q
```

PowerShell:

```powershell
New-Item -ItemType Directory -Force data | Out-Null
$env:DATA_MODE = "demo"
$env:DATABASE_PATH = ".\data\test.db"
python scripts/seed_database.py
python -m pytest -q
```

Most tests create isolated databases under pytest's temporary directory. The API module initializes its configured database at import time, so set `DATABASE_PATH` before starting pytest.

## Run the full benchmark

The checked-in golden dataset contains 150 deterministic demo questions. Seed the disposable database, then write benchmark output to an ignored local data path:

```bash
DATA_MODE=demo DATABASE_PATH=./data/test.db python scripts/seed_database.py
DATA_MODE=demo DATABASE_PATH=./data/test.db EVAL_RESULTS_PATH=./data/eval_results.json python scripts/run_eval.py
```

The evaluator reports retrieval Recall@5 and MRR, exact numerical matching against fixture values, citation resolution, SEC-only claim-faithfulness accounting, and end-to-end latency percentiles. Demo claim faithfulness is expected to remain 0%; this is a provenance safety check, not a defect in the fixture. Benchmark results describe this fixed synthetic corpus and are not evidence of live SEC accuracy or production-scale performance.

The evaluation code uses the configured database. `EVAL_RESULTS_PATH` changes only where the JSON result is written; it does not isolate or seed the database by itself.

## Opt into SEC Company Facts ingestion

SEC mode fetches structured Company Facts only. It requires an application-identifying User-Agent with a monitored contact address, network access, and acceptance of SEC availability/HTTP/schema failures:

```bash
DATA_MODE=sec SEC_USER_AGENT='MyResearchApp/1.0 (you@example.com)' DATABASE_PATH=./data/sec_facts.db python scripts/seed_database.py
```

PowerShell:

```powershell
$env:DATA_MODE = "sec"
$env:SEC_USER_AGENT = "MyResearchApp/1.0 (you@example.com)"
$env:DATABASE_PATH = ".\data\sec_facts.db"
python scripts/seed_database.py
```

The supported universe is the 25 companies listed in `src/ingestion/companies.py`; Company Facts are filtered to 10-K/10-Q entries with fiscal years 2023 or 2024. SEC mode does not ingest filing text, and it does not create narrative SEC citations. An unsuccessful request stops seeding before the existing corpus is replaced. The database path should be separate from demo data if both modes need to be retained.

After seeding, start the server with the same `DATA_MODE`, `SEC_USER_AGENT`, and `DATABASE_PATH` so the API filters to the same provenance. Do not assume a seeded database's contents change the runtime mode automatically; the environment variable selects which provenance is queried.

## Run the application with Docker Compose

Docker is optional. The Compose configuration mounts `./data` into `/app/data`; seed that mounted path before starting the service:

```bash
mkdir -p data
docker compose build
docker compose run --rm financial-copilot python scripts/seed_database.py
docker compose up
```

Open <http://localhost:8000>. The Compose port mapping is `8000:8000` and may bind on all host interfaces; use this setup only on a trusted development machine/network. For SEC facts mode, set `DATA_MODE=sec` and `SEC_USER_AGENT` in the invoking environment or a local untracked `.env` file, then seed the mounted database using the same settings. The container defaults to `demo` mode.

Persisted application data resides in the host's `./data` directory. The image build also seeds its own `/app/data` layer, but the Compose bind mount takes precedence at runtime.

## Regenerate the golden evaluation dataset

`python scripts/generate_golden_dataset.py` writes directly to the tracked `src/eval/golden_dataset.json`. It generates deterministic demo questions from the mock-data generator; it does not query SEC. Run it only when intentionally changing the benchmark, then review the full dataset diff and update tests/CI expectations if the item count or contract changes.

## Inspect health and operational counters

- `GET /health` reports the configured mode and current company/fact/chunk row counts. The status field is not a database connectivity probe independent of those SQLite reads.
- `GET /api/metrics` returns process uptime, request count, p50/p95 latencies for tracked POST routes, and dense-index initialization/refresh time.
- `RATE_LIMIT_PER_MINUTE` changes the in-memory per-client-IP limit for `POST /api/query` and `POST /api/search`; blocked responses include `Retry-After`.

These metrics and limits are local to one process. They are not durable or coordinated among workers.

## Troubleshooting

### The dashboard has no facts or returns no passages

Check that seeding and the server use the same `DATABASE_PATH` and `DATA_MODE`. The API filters facts and chunks to the selected source. Legacy rows labeled `legacy_unknown` are not treated as demo or SEC data.

### SEC mode rejects startup or seeding

Set `SEC_USER_AGENT` to a non-empty application name plus monitored contact email. Check the logs for the failing ticker and HTTP/JSON validation error. SEC network failures are raised; demo rows are not substituted.

### SEC reports have no narrative citations

This is expected: ingestion of filing text is not implemented. SEC mode indexes structured facts only; do not relabel generated demo chunks as SEC evidence.

### A requested period is reported unavailable

The verifier does not substitute another quarter/year for an explicit period when no exact matching fact is indexed. Check ticker, mode, concept, year, and fiscal period in `/api/facts`.

### Search index results look stale after direct database edits

Use `DatabaseStorage` methods, which maintain the FTS index and revision counter. Reinitializing the storage layer repairs/rebuilds the FTS table from canonical chunks. Recreate the dense index on the next search after a tracked chunk change. Direct writes that bypass SQLite triggers or the storage APIs are unsupported.

### Tests appear to use unexpected local data

Set `DATABASE_PATH` and `DATA_MODE` in the same shell before Python imports `src.api.app`. The API constructs storage at module import. Use `./data/test.db`; do not use the root working database as a disposable test target.
