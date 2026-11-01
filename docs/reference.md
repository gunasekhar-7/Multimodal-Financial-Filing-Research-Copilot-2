# Technical reference

This page describes the current interfaces implemented by the repository. For setup steps, see the [local tutorial](tutorial-local.md) and [how-to guides](how-to.md); for design rationale and limits, see [architecture](architecture.md).

## Runtime configuration

| Variable | Default | Meaning |
|---|---|---|
| `DATA_MODE` | `demo` | Selects the provenance returned by ingestion and API queries. Supported values are `demo` and `sec`. Set it consistently for seeding and serving. |
| `DATABASE_PATH` | `financial_copilot.db` | SQLite file used by the API, seed script, and evaluator. Parent directories are created as needed. Seeding replaces facts/chunks in this database. |
| `SEC_USER_AGENT` | unset | Required in `sec` mode. Identifies the application and monitored contact to SEC. It is sent as the HTTP User-Agent. |
| `RATE_LIMIT_PER_MINUTE` | `60` | Maximum in-memory requests per client-IP key in a 60-second sliding window for tracked POST endpoints. |
| `EVAL_RESULTS_PATH` | `eval_results.json` | Output location for the JSON report written by `scripts/run_eval.py`; does not select or seed the database. |
| `PYTHONPATH` | shell-dependent | Set to `.` when invoking scripts/tests in environments that do not automatically put the project root on the import path. CI sets it explicitly. |

Unknown `DATA_MODE` values cause `SECDataIngestionClient` initialization to raise `ValueError`. The API's runtime mode check treats only the literal normalized value `sec` as SEC; use one of the documented values.

### Company universe and periods

`src/ingestion/companies.py` defines 25 technology tickers. The deterministic generator defines eight records per company: `2023-Q1`, `2023-Q2`, `2023-Q3`, `2023-FY`, `2024-Q1`, `2024-Q2`, `2024-Q3`, and `2024-FY`. SEC mode is limited by the ingestion code to 10-K/10-Q facts with fiscal years 2023/2024. SEC data may not provide a fact for every generated period.

## HTTP API

FastAPI serves the dashboard at `/`, static JavaScript under `/static`, and interactive OpenAPI documentation at `/docs` when the application is running.

### `GET /health`

Returns an operational summary:

```json
{
  "status": "healthy",
  "database": "connected",
  "companies_count": 25,
  "xbrl_facts_count": 0,
  "document_chunks_count": 0,
  "data_mode": "demo",
  "demo_data": true
}
```

Counts are read from SQLite. `status` and `database` are fixed labels in this response; they do not indicate that every downstream feature or external SEC endpoint is healthy.

### `GET /api/companies`

Returns a JSON array of `CompanyInfo`: `ticker`, `cik`, `name`, `sector`, optional `sic`, and optional `industry`. The API list comes from the companies table, initially seeded from the code-defined universe.

### `GET /api/facts`

Required query parameter: `ticker`. Optional: `concept`, `year`, `period`.

Example: `GET /api/facts?ticker=AAPL&concept=Revenues&year=2024&period=FY`

Returns an array of `XBRLFact`, filtered to the currently selected `DATA_MODE` provenance. No matches returns `[]`. Each fact includes identifier, issuer/ticker, XBRL concept/taxonomy/label, numeric value and unit, fiscal year/period, form, filed date, period start/end, restatement flag, and `data_source` (`demo`, `sec_edgar`, or `legacy_unknown`).

### `POST /api/search`

Request model: `SearchQuery`.

```json
{
  "query": "Apple revenue growth",
  "tickers": ["AAPL"],
  "fiscal_years": [2024],
  "fiscal_periods": ["FY"],
  "sections": ["Item 8."],
  "top_k": 5
}
```

`query` is required. The filter fields are optional; `top_k` defaults to 10 and is constrained to 1–100 by Pydantic. The lexical storage layer clamps its SQL result count to 1–100. The endpoint returns `SearchResultItem[]`, each carrying a `DocumentChunk`, retrieval score, and method. The current API schema declares `filing_types`, but the current retrieval implementation does not apply that filter; do not rely on it until implemented.

### `POST /api/query`

Request:

```json
{
  "question": "What was Apple revenue in FY 2024?",
  "ticker": "AAPL"
}
```

`ticker` defaults to `AAPL`. Questions shorter than three non-whitespace characters return HTTP 400. A ticker not present in the company table returns HTTP 400. Processing failures return HTTP 500 with a generic client message; details are logged server-side.

Success returns a `ResearchReport` with:

- report ID and creation timestamp;
- original question and target tickers;
- executive summary and uncertainty disclosures;
- extracted metric comparisons and risk passages;
- claims with verification status, notes, optional values, and citations;
- deduplicated citation list;
- `data_mode` and `data_sources`.

Verification status values: `verified`, `unverified`, `contradicted`, `ambiguous`. Current behavior uses `verified` only for a matching SEC EDGAR structured fact when a same-source, same-period citation passage is available. Demo claims remain unverified, and qualitative claims remain unverified because semantic entailment is not implemented. SEC mode currently has no document chunks, so its structured numerical fact alone is not promoted to a cited verified claim.

### `GET /api/metrics`

Returns process uptime, request count, per-tracked-endpoint latency sample count/p50/p95 in milliseconds, and dense-index initialization/last-refresh data. Only `/api/query` and `/api/search` are latency-tracked. Metric samples are held in bounded in-process ring buffers; the endpoint is not a Prometheus exporter.

### Middleware and cross-origin requests

CORS allows the configured localhost origins `http://localhost`, `http://localhost:3000`, `http://127.0.0.1`, and `http://127.0.0.1:3000`, with credentials enabled for those explicit origins. Per-IP rate limiting applies to POST `/api/query` and `/api/search`; a blocked response is HTTP 429 with a `Retry-After` header.

## Data models

Pydantic contracts live in `src/schemas`:

| Model | Purpose |
|---|---|
| `CompanyInfo` | Supported company identity and industry information |
| `XBRLFact` | Structured numeric fact, unit, fiscal period, and source provenance |
| `DocumentChunk` | Searchable filing/demo passage with period, section, location, URL, and provenance |
| `SearchQuery` | Search text, ticker/type/year/period/section filters, and result limit |
| `SearchResultItem` | Chunk, score, retrieval method |
| `ResearchPlan`, `AgentState` | Internal orchestration state and plan |
| `Citation` | Passage reference with section, fiscal period, excerpt, URL, and provenance |
| `VerifiedClaim` | Claim text, optional numeric value, status, notes, citations |
| `FinancialMetricComparison` | Per-period values, units, computed YoY/QoQ percentage changes |
| `RiskFactorAnalysis` | Retrieved risk text and citations; `trend` is currently `not_assessed` |
| `ResearchReport` | Public query response, disclosures, source mode and source set |

`DataSource` enum values are `demo`, `sec_edgar`, and `legacy_unknown`. New database columns default existing legacy rows to `legacy_unknown`; they are not silently reclassified as SEC or demo evidence.

## Storage reference

`DatabaseStorage` creates these SQLite structures:

- `companies`: ticker primary key plus identity/industry fields.
- `xbrl_facts`: fact ID primary key, numeric values, periods, and source.
- `document_chunks`: chunk ID primary key, passage metadata, optional JSON table data, source URL, and source.
- `document_chunks_fts`: FTS5 search index for chunk ID, ticker, section, and content.
- `search_index_state`: singleton revision counter, advanced by insert/update/delete triggers on document chunks.

Storage methods use parameterized SQL. `insert_document_chunks` replaces the corresponding FTS row by chunk ID. `replace_seed_data` clears and replaces facts, chunks, and FTS entries in a transaction. Initialization rebuilds FTS rows from canonical chunks to repair stale/duplicate legacy entries. FTS is derived state; `document_chunks` is canonical.

## Pipeline and retrieval reference

The pipeline order is planner → retrieval → extraction → risk analysis → verification → writer. See [architecture](architecture.md#request-and-data-flow) for behavior and trust boundaries.

Retrieval uses two channels:

1. SQLite FTS5 BM25 with sanitized query tokens, prefix matching for longer tokens, source/ticker/year/section filters, and LIKE fallback when FTS execution fails.
2. TF-IDF cosine similarity using one- and two-gram features, filtered by source/ticker/year/period/section.

Results are merged by reciprocal-rank fusion (`k=60`) using `chunk_id`, then reranked with query-conditional term, table, and financial-metric boosts. The reranker is a transparent heuristic, not a learned cross-encoder. Both channels and the fused result are local to the process.

## Scripts

| Command | Behavior |
|---|---|
| `python scripts/seed_database.py` | Fetch/generate all source records first; then transactionally replace facts/chunks in `DATABASE_PATH`. Mode selected by `DATA_MODE`. |
| `python scripts/run_eval.py` | Run the checked-in demo benchmark and write metrics JSON to `EVAL_RESULTS_PATH` (or root `eval_results.json`). Seeds automatically only if the configured database path does not exist. |
| `python scripts/generate_golden_dataset.py` | Regenerate tracked `src/eval/golden_dataset.json` from deterministic demo data. |

The evaluator returns total question count, Recall@5, MRR, numerical accuracy, citation resolution rate, claim faithfulness rate, p50/p95 end-to-end latency, and category breakdown. CI currently expects 150 questions and applies thresholds; see `.github/workflows/ci.yml` for the authoritative gates. The benchmark's expected numbers come from the same synthetic generator, so it validates code behavior, not independent financial correctness.

## Docker reference

`Dockerfile` uses `python:3.12-slim`, installs `requirements.txt`, seeds the image's default demo database at build time, and runs Uvicorn on `0.0.0.0:8000`. `docker-compose.yml` exposes port 8000, mounts host `./data` at `/app/data`, and checks `/health` using curl. Compose defaults to `DATA_MODE=demo`; optional `SEC_USER_AGENT` is passed from the host environment. See [Docker how-to](how-to.md#run-the-application-with-docker-compose).

## CI reference

`.github/workflows/ci.yml` runs on pushes to `main`, `master`, and `jules-*`, and pull requests targeting `main` or `master`. It sets up Python 3.12, installs pinned requirements, seeds a runner-temporary demo database, runs pytest with coverage, runs the full benchmark into a temporary artifact path, and asserts dataset size and quality thresholds. CI does not need SEC credentials or external SEC access.

## Dependency reference

Direct pinned requirements are listed in [`requirements.txt`](../requirements.txt): Pydantic 2, FastAPI, Uvicorn, HTTPX, scikit-learn, NumPy, pytest, and pytest-cov. SQLite/FTS5 is provided by Python's SQLite build. There is no separate frontend package manager or JavaScript build step; the current page references Tailwind and Font Awesome CDNs.
