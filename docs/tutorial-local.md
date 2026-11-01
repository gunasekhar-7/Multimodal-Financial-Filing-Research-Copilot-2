# Tutorial: run the offline demo locally

This tutorial takes a new developer from a clean checkout to a generated research report. It uses the deterministic synthetic corpus and keeps the working database under the ignored `data/` directory.

## Prerequisites

- Python 3.12 or newer.
- `pip` and a shell (PowerShell, Bash, or a compatible terminal).
- No SEC account, API key, or network access is needed for demo mode. Package installation does require access to your configured Python package index unless dependencies are already available.

## 1. Create and activate a virtual environment

From the repository root:

```bash
python -m venv .venv
```

Activate it in PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
```

Or in Bash / macOS / Linux:

```bash
source .venv/bin/activate
```

Install the pinned project dependencies:

```bash
python -m pip install -r requirements.txt
```

## 2. Create an isolated demo database

Make a local data directory and seed it explicitly in offline demo mode:

```bash
mkdir -p data
DATA_MODE=demo DATABASE_PATH=./data/financial_copilot.db python scripts/seed_database.py
```

PowerShell equivalent:

```powershell
New-Item -ItemType Directory -Force data | Out-Null
$env:DATA_MODE = "demo"
$env:DATABASE_PATH = ".\data\financial_copilot.db"
python scripts/seed_database.py
```

The seed script replaces facts and document chunks in that database atomically. Re-running it is supported. Do not point `DATABASE_PATH` at a database you need to preserve; seeding replaces the indexed corpus.

## 3. Start the API and dashboard

Keep the same environment settings in the server's shell:

```bash
DATA_MODE=demo DATABASE_PATH=./data/financial_copilot.db python -m uvicorn src.api.app:app --host 127.0.0.1 --port 8000
```

PowerShell:

```powershell
$env:DATA_MODE = "demo"
$env:DATABASE_PATH = ".\data\financial_copilot.db"
python -m uvicorn src.api.app:app --host 127.0.0.1 --port 8000
```

Open <http://127.0.0.1:8000>. The dashboard status badge should identify the demo corpus as synthetic. API documentation is available at <http://127.0.0.1:8000/docs> and the health response at <http://127.0.0.1:8000/health>.

## 4. Generate your first report

Choose a sample question in the dashboard, or submit this request in another terminal:

```bash
curl -sS http://127.0.0.1:8000/api/query \
  -H 'Content-Type: application/json' \
  -d '{"question":"What was Apple revenue in FY 2024?","ticker":"AAPL"}'
```

The response is a structured report. Inspect `data_mode`, `data_sources`, each claim's `status`, `verification_notes`, and citations. Demo numeric matching is intentionally `unverified`; it must not be read as confirmation of company-reported figures. Narrative excerpts are source context, not semantically verified conclusions.

## 5. Explore the interface and API

- Change the company and question in the dashboard.
- Use `GET /api/companies` to discover the supported ticker list.
- Use `GET /api/facts?ticker=AAPL` to inspect indexed facts and their provenance.
- Use `POST /api/search` to inspect retrieved passages.
- Use `GET /api/metrics` for process-local request and retrieval-index signals.

Continue with [how-to guides](how-to.md) for testing, evaluation, Docker, and optional SEC facts mode, or consult the [technical reference](reference.md) for precise schemas and configuration.
