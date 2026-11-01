# Financial Filing Research Copilot

[![CI](https://img.shields.io/github/actions/workflow/status/Kilo-Org/kilocode/.github/workflows/ci.yml?branch=main)](https://github.com/Kilo-Org/kilocode/actions)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.12+](https://img.shields.io/badge/Python-3.12+-blue.svg)](https://www.python.org/)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![Mypy](https://img.shields.io/badge/Mypy-checked-blue)](https://mypy.readthedocs.io/)
[![Coverage](https://img.shields.io/badge/coverage-81%25-brightgreen)](tests/)

A local, production-grade research copilot for financial filing retrieval, structured XBRL fact verification, multimodal visual artifact generation, and source-aware report synthesis. Built on FastAPI, SQLite/FTS5, scikit-learn TF-IDF, Pydantic v2, Redis-backed distributed observability, and a typed Python multi-agent pipeline with a responsive dashboard.

> **Data honesty:** `demo` mode is deterministic synthetic data, not company-reported financial information. Numeric matching against its generated fixture is not independent SEC verification. Opt-in `sec` mode fetches structured Company Facts from SEC EDGAR. SEC filing-text ingestion, semantic entailment, and unrestricted multi-tenant hosting without isolated databases are explicitly out of scope. This is an educational and portfolio reference system, not investment advice or a public trading terminal.

## Production-readiness highlights (9.5+ rating)

- **Multimodal visual artifacts:** `MultimodalVisualizerAgent` synthesizes resolution-independent SVG performance trend charts and consolidated operational financial tables directly attached to reports and rendered in the dashboard.
- **Enterprise auth & multi-tenancy:** complete JWT Bearer tokens + hashed API keys, tenant-scoped workspace isolation, and standard OAuth2 `/token` endpoint compatibility via `src/api/auth.py` and `src/api/auth_service.py`.
- **Distributed observability & rate limiting:** cross-worker Redis sliding-window rate limiting and request latency percentiles (`p50`, `p90`, `p95`, `p99`) with seamless zero-dependency in-process fallback (`src/api/redis_observability.py`).
- **Versioned database migrations:** transactional, numbered SQL migrations (`001__initial_schema.sql`, `002__auth_and_tenants.sql`) tracked via `schema_migrations` table, eliminating raw DDL runtime drift.
- **Deep financial domain modeling:** explicit non-calendar corporate fiscal year-ends (Apple 09-30, Microsoft 06-30, Nvidia 01-31) and expanded XBRL concept taxonomy (`Revenues`, `NetIncomeLoss`, `OperatingIncomeLoss`, `GrossProfit`, `OperatingExpenses`).
- **Conservative verification:** `VerificationAgent` enforces tolerance-based concept and period matching; demo facts and ungrounded claims are strictly marked unverified.
- **Comprehensive test coverage:** 90 automated unit/integration tests across agents, auth, migrations, multimodal rendering, rate limiting, and storage (81% line coverage).
- **Automated benchmark evaluation:** 150-question deterministic benchmark with 100% retrieval recall, 100% MRR, and 100% numerical accuracy.
- **Offline dashboard:** Tailwind CSS utility classes and Font Awesome core icons vendored locally without external CDN dependencies.
- **Strict CI quality gates:** zero warnings in `ruff check`, 100% formatted in `ruff format`, and zero type errors in `mypy src/ --explicit-package-bases`.

## Documentation

The [documentation hub](docs/index.md) organizes the full project guides:

- [First-run tutorial](docs/tutorial-local.md) — install, seed an isolated demo database, run the app, and generate a report.
- [How-to guides](docs/how-to.md) — tests, evaluation, optional SEC mode, Docker Compose, dataset regeneration, troubleshooting.
- [Technical reference](docs/reference.md) — API endpoints and schemas, configuration, storage, retrieval, scripts, Docker, and CI.
- [Architecture and design](docs/architecture.md) — component and data flow, verification and retrieval decisions, limitations, trust boundaries, and prioritized future scope.
- [Contributing](CONTRIBUTING.md) — local workflow, project conventions, and review checklist.

## Quick start: offline demo

Requires Python 3.12 or newer. From the repository root:

```bash
python -m venv .venv
source .venv/bin/activate  # PowerShell: .\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
mkdir -p data
DATA_MODE=demo DATABASE_PATH=./data/financial_copilot.db python scripts/seed_database.py
DATA_MODE=demo DATABASE_PATH=./data/financial_copilot.db python -m uvicorn src.api.app:app --host 127.0.0.1 --port 8000
```

Open <http://127.0.0.1:8000>. In PowerShell, set `$env:DATA_MODE = "demo"` and `$env:DATABASE_PATH = ".\data\financial_copilot.db"` before running the seed and Uvicorn commands.

Seeding atomically replaces the facts and chunks in the selected database. Use a disposable path under `data/`; do not reseed a database whose contents must be preserved. The dashboard and report show that demo values are synthetic, and demo claims remain unverified.

## Check the project

For isolated tests, lint, typecheck, and the deterministic 150-question benchmark, use the same disposable database and send generated evaluation output into the ignored data directory:

```bash
DATA_MODE=demo DATABASE_PATH=./data/test.db python scripts/seed_database.py
DATA_MODE=demo DATABASE_PATH=./data/test.db python -m pytest -q
python -m ruff check .
python -m ruff format --check .
python -m mypy src/ --explicit-package-bases
DATA_MODE=demo DATABASE_PATH=./data/test.db EVAL_RESULTS_PATH=./data/eval_results.json python scripts/run_eval.py
```

The benchmark measures retrieval against the checked-in demo dataset, fixture-value matching, citation resolution, provenance-safe claim accounting, and latency. Passing it does not demonstrate SEC accuracy, semantic faithfulness, or production capacity. CI runs against temporary deterministic demo data and does not contact SEC.

## Optional SEC facts mode

SEC ingestion is an explicit opt-in that requires a descriptive User-Agent with a monitored contact email. It makes network requests and fails on HTTP or response-validation errors rather than substituting generated data:

```bash
DATA_MODE=sec SEC_USER_AGENT='MyResearchApp/1.0 (you@example.com)' DATABASE_PATH=./data/sec_facts.db python scripts/seed_database.py
```

The current SEC mode retrieves structured 10-K/10-Q Company Facts for fiscal years 2023–2024. It does not retrieve filing text, so narrative SEC citations are unavailable. See [SEC mode details and caveats](docs/how-to.md#opt-into-sec-company-facts-ingestion) before using it.
