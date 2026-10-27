# Contributing to the Financial-Filing Research Copilot

Thanks for your interest in improving the project. This document covers the
setup, the commands you need, and the conventions we follow.

## Getting started

Requirements: Python 3.11+ and pip. No database server is needed — the
project runs on an embedded SQLite database (`financial_copilot.db`).

1. Clone the repository and create a virtual environment:

   ```bash
   python -m venv .venv
   # Windows
   .venv\Scripts\activate
   # macOS / Linux
   source .venv/bin/activate
   ```

2. Install the dependencies:

   ```bash
   pip install -r requirements.txt
   ```

3. Seed the demonstration corpus (10 technology companies, 8 quarters
   2023-Q1 through 2024-FY):

   ```bash
   python scripts/seed_database.py
   ```

4. Run the API + web dashboard locally (hot reload for UI changes):

   ```bash
   uvicorn src.api.app:app --reload --port 8000
   ```

   Then open http://localhost:8000. The API docs live at `/docs`.

## Test and quality commands

Run the full suite before every PR — CI runs the same commands:

```bash
# All tests
python -m pytest tests/ -v

# Evaluation benchmark (recall / MRR / accuracy / latency thresholds)
python scripts/run_eval.py
```

Keep changes covered: new behavior needs a matching test in `tests/`,
and regression fixes should include the failing case as a test first.

## Project conventions

- **Architecture**: schema models (`src/schemas` → `src/agents`) → storage and
  retrieval (`src/storage`, `src/retrieval`) → agents (`src/agents`) →
  orchestrator → API (`src/api`) → web templates (`src/web`). Each concern
  stays in its own package; see [ARCHITECTURE.md](ARCHITECTURE.md).
- **Honest scoping**: the corpus is a seeded demonstration dataset. Do not
  describe demo numbers as live SEC EDGAR data in code, docs, or commits.
- **No new hard dependencies for cross-cutting concerns**: logging,
  metrics, and rate limiting are standard-library based. If a feature
  genuinely needs a library, say so in the PR description.
- **Claim verification**: claims only ever become VERIFIED when grounded in
  indexed XBRL facts or financial filing text. Out-of-domain questions
  yield UNVERIFIED claims — keep that invariant when touching the verifier.
- **Style**: type hints on public functions, Pydantic models for anything
  crossing a module boundary, and `logging.getLogger(__name__)` rather than
  print statements.

## Submitting changes

1. Create a feature branch from `main`.
2. Make the change small and focused — one behavior per PR.
3. Run `python -m pytest tests/ -v` and `python scripts/run_eval.py` locally.
4. Open a pull request describing the why, not just the what.

CI runs the test suite and evaluation gates on every push; a PR is merged
only when both are green.
