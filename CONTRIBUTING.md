# Contributing

Thank you for improving the Financial Filing Research Copilot. This guide covers local setup, project conventions, and checks to run before proposing a change.

## Development setup

Requirements: Python 3.12 or newer and pip. SQLite is embedded; no database server or SEC account is required for the offline demo.

1. Create and activate a virtual environment:

   ```bash
   python -m venv .venv
   # Windows PowerShell
   .\.venv\Scripts\Activate.ps1
   # macOS / Linux / Bash
   source .venv/bin/activate
   ```

2. Install pinned dependencies:

   ```bash
   python -m pip install -r requirements.txt
   ```

3. Seed an isolated deterministic demo database (the corpus is 25 technology companies, with eight generated periods per company):

   ```bash
   mkdir -p data
   DATA_MODE=demo DATABASE_PATH=./data/financial_copilot.db python scripts/seed_database.py
   ```

4. Start the API and dashboard using the same mode and database path:

   ```bash
   DATA_MODE=demo DATABASE_PATH=./data/financial_copilot.db python -m uvicorn src.api.app:app --reload --host 127.0.0.1 --port 8000
   ```

   Open <http://127.0.0.1:8000>; interactive API docs are at `/docs`. A full first-run walkthrough is in the [local tutorial](docs/tutorial-local.md).

Do not use the root `financial_copilot.db` for disposable tests or reseeding if its contents need to be preserved. `scripts/seed_database.py` replaces the facts and chunks in its selected database.

## Quality checks

Set environment variables before pytest imports the FastAPI app; the app initializes its configured database at module import time. Use disposable paths and send benchmark output to ignored local data:

```bash
mkdir -p data
DATA_MODE=demo DATABASE_PATH=./data/test.db python scripts/seed_database.py
DATA_MODE=demo DATABASE_PATH=./data/test.db python -m pytest -q
python -m ruff check .
python -m ruff format --check .
python -m mypy src/ --explicit-package-bases
DATA_MODE=demo DATABASE_PATH=./data/test.db EVAL_RESULTS_PATH=./data/eval_results.json python scripts/run_eval.py
```

CI uses Python 3.12, a runner-temporary demo database, the test suite, and the full 150-question synthetic benchmark. It does not contact SEC. A passing demo benchmark is not evidence of live-source accuracy or semantic claim faithfulness; demo claims are intentionally not counted as SEC-verified.

## Project conventions

- **Keep layers focused:** Pydantic contracts in `src/schemas`; persistence in `src/storage`; ingestion in `src/ingestion`; retrieval in `src/retrieval`; pipeline steps in `src/agents`; HTTP and browser surface in `src/api` and `src/web`. See [architecture](docs/architecture.md).
- **Preserve provenance:** never present demo-generated facts or passages as SEC evidence. Keep `data_source` consistent through storage, retrieval, citations, and reports.
- **Fail honestly:** missing or ambiguous source data should remain unavailable/unverified rather than borrowing another ticker/period or inventing a claim.
- **Avoid unnecessary dependencies:** current API metrics/rate limiting use the standard library. Explain the need when a new runtime dependency is justified.
- **Use typed boundaries:** add type hints to public functions and Pydantic models for data crossing module boundaries.
- **Use structured logging:** prefer `logging.getLogger(__name__)` over prints in application code.
- **Test regressions:** add a focused test for corrected behavior; prefer fixtures and temporary paths over network calls or repository-root databases.

## Before opening a pull request

1. Run tests and the demo benchmark with disposable paths.
2. Review changed files, generated artifacts, and any database changes; do not include data files unless explicitly intended.
3. Update documentation when public endpoints, configuration, operational behavior, or user-facing limitations change.
4. Describe the motivation, behavior, evidence, and remaining limitations.

The project is currently a local/portfolio application, not an authenticated multi-user production service. See [limitations and future scope](docs/architecture.md#limitations-and-trust-boundaries) before proposing deployment-related work.
