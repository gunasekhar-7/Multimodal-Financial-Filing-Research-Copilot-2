# Production/Resume-Readiness Plan: Financial Filing Research Copilot

**Target rating:** 9.5/10 (production-grade local research copilot)
**Current rating:** 6.5/10 (solid portfolio prototype; not production-ready)
**Plan file:** `plans/1793449090300-production-readiness.md`
**Executor:** implementation-capable agent (this plan agent cannot mutate files)

---

## Goal

Transform the Financial Filing Research Copilot from a local/portfolio prototype into a resume-ready, production-grade application. The plan closes every P0 correctness gap, hardens security/ops, matures CI, and polishes the developer experience so a reviewer can verify: real XBRL-backed verification, correct quarterly accuracy, fresh retrieval after reseed, honest CI gates, and no auth/z or SQL-injection regressions.

## Current State (from senior-engineer review)

| Category | Rating | Key gaps |
|----------|--------|----------|
| Architecture & Design | 7/10 | "Multi-agent" is a subroutine pipeline; global singletons; dense index stale after reseed |
| Correctness | 5/10 | VerificationAgent does not verify; quarterly numerical accuracy 0%; stale dense index |
| Code Quality | 7/10 | Duplicated quarter/growth math; dead surface (`src/schemas/__init__.py`); unused `math` import; `model_construct` wrap-mode bypasses validation |
| Security | 7/10 | CORS and SQL paramization are correct; no auth/z (acknowledged local-only limitation) |
| Testing | 7/10 | Happy-path coverage; lacks targeted tests for verification status machine and quarterly extraction |
| Documentation | 8/10 | Architecture/how-to/tutorial/reference/contributing present and honest |
| Deployment / Ops | 6/10 | Docker + Compose good; metrics/rate limiting are in-process only; no migrations, backups, secrets mgmt |
| **Overall** | **6.5/10** | |

---

## Guiding Principles (for the implementing agent)

- **Fail honestly:** missing/ambiguous data stays unverified; never borrow another ticker/period or fabricate a CIK/company name.
- **Provenance is data:** `data_source` flows consistently from ingestion → storage → retrieval → citations → reports. Demo is never presented as SEC evidence.
- **No silent degradation:** an explicitly requested but unavailable period stays unverified rather than substituting another period.
- **Parameterized SQL only:** no f-string interpolation into SQL, including `LIMIT` fallbacks.
- **Validate at boundaries:** Pydantic models for all data crossing module boundaries; avoid `model_construct` wrap-mode unless validated round-trip tests exist.
- **Local-only scope:** this plan does not add multi-tenant auth, durable observability, or cross-worker coordination beyond what's needed for honest local production behavior. Auth/z is added as opt-in middleware, not a full identity system.

---

## Stage 1: Core Verification & Retrieval Correctness (P0)

**Entry criteria:** None (start now).
**Exit criteria:** VerificationAgent emits `VERIFIED`/`CONTRADICTED`/`UNVERIFIED`/`AMBIGUOUS` based on exact XBRL lookup; quarterly accuracy ≥95% on the full demo dataset; dense index refreshes after reseed without process restart; CI gates pass against the full 150-question dataset.

### Stage 1 Tasks

**1.1 Implement real claim verification** (`src/agents/verifier.py`)
- Parse the question's requested XBRL concept (extend `_detect_concept` to cover Revenues, NetIncomeLoss, EarningsPerShareDiluted, and any concept explicitly named) and requested fiscal year/period (extend `_parse_requested_period`).
- Look up the exact fact matching concept + ticker + year + period. If exact match absent, return `UNVERIFIED` (never borrow a different period).
- Compare the claim's numerical value against the XBRL fact within tolerance (default 1%). Emit:
  - `VERIFIED` when value matches within tolerance and a same-source/same-period citation exists.
  - `CONTRADICTED` when value exists but differs beyond tolerance.
  - `UNVERIFIED` when no grounding fact exists (demo data stays unverified; SEC data without citation stays unverified per existing conservative policy).
  - `AMBIGUOUS` when multiple facts match and no unique selection is possible.
- Remove the hardcoded "always VERIFIED" behavior. The qualitative claim path stays `UNVERIFIED` with source-context notes (no semantic entailment).
- Add `target_tickers` filtering completeness so ticker-scoped questions don't leak facts for other companies.

**1.2 Fix quarterly numerical accuracy** (`src/agents/extraction.py`, `src/agents/verifier.py`)
- `extract_metrics` must surface exact per-period values (including single quarters like Q1 2024) as comparable periods, not only YoY/QoQ deltas.
- `verify_claims` must emit a numerical claim for the exact requested quarter/year when the fact exists, with `numerical_value` matching the seeded fixture within tolerance.
- Target: quarterly_performance category recall 100% and numerical accuracy ≥95%.

**1.3 Refresh dense index after reseed without restart** (`src/retrieval/hybrid_search.py`, `src/storage/database.py`)
- Expose a public `rebuild_index()` / `refresh_if_changed()` on `HybridSearchEngine` that checks the SQLite `search_index_state` revision fingerprint on every search (or after known mutation) and re-fits the TF-IDF vectorizer when the revision changed.
- Ensure `DatabaseStorage.replace_seed_data` bumps the revision counter (triggers already do this for inserts/updates/deletes; verify `replace_seed_data` path also advances it).
- Add a test: seed DB → search → reseed with different data → search (same process) → results reflect new chunks.

**1.4 Reconcile CI quality gates with the real benchmark** (`.github/workflows/ci.yml`, `scripts/run_eval.py`, `src/eval/golden_dataset.json`)
- Confirm `run_eval.py` runs the full dataset (no hidden 25-question cap). Remove any `sample_limit` that silently truncates.
- Regenerate `src/eval/golden_dataset.json` to 150 items (6 questions × 25 companies) and verify `total_questions == 150`.
- Update CI gates to realistic, enforced thresholds consistent with the post-fix metrics: recall@k ≥ 50%, numerical_accuracy ≥ 95%, citation_resolution ≥ 90%, claim_faithfulness == 0% for demo.
- Commit a fresh `eval_results.json` artifact produced from the full dataset so the checked-in artifact matches what CI computes.

**Stage 1 Validation:**
- `pytest tests/` passes (all existing tests + new verification/quarterly tests).
- `scripts/run_eval.py` produces `total_questions: 150`, `numerical_accuracy_pct >= 95`, `recall_at_k >= 50`, `citation_resolution_rate_pct >= 90`, `claim_faithfulness_rate_pct == 0.0`.
- CI quality-gate assertion block passes against the artifact.
- New test: reseeded DB searched in same process returns fresh chunks.

---

## Stage 2: Ingestion Architecture & Data Integrity (P1)

**Entry criteria:** Stage 1 complete and validated.
**Exit criteria:** Ingestion split into demo generator + SEC client; quarter/growth math centralized; unknown-ticker lookup raises/returns None instead of fabricating CIK; wrap-mode eliminated or validated; targeted tests for verification status machine and quarterly extraction.

### Stage 2 Tasks

**2.1 Split `SECDataIngestionClient`** (`src/ingestion/sec_client.py`)
- Create `DemoDataGenerator` (deterministic mock facts + chunks, `generate_mock_xbrl_facts`, `generate_mock_document_chunks`).
- Create `SecCompanyFactsClient` (HTTP to SEC Company Facts, requires `SEC_USER_AGENT`, filters 10-K/10-Q for FY 2023–2024, raises on network/validation failure, never substitutes demo data).
- Update `seed_database.py` to select the generator/client by `DATA_MODE`.
- Keep `fetch_company_facts` / `fetch_document_chunks` entry points for backward compatibility, delegating to the split implementations.

**2.2 Centralize quarter/growth projection math** (`src/ingestion/sec_client.py`)
- Extract a single `projected_period_values(base_rev, base_ni, growth, quarters)` helper used by both fact and chunk generators.
- Make the EPS approximate-shares constant (`2500.0`) a named module constant with a comment.
- Remove duplicated `QUARTERS` loop logic between the two generators.

**2.3 Fix `get_company_by_ticker` fabrication** (`src/ingestion/companies.py`)
- For unknown tickers, return `None` or raise `ValueError` instead of fabricating `cik="0000000000"` and a synthetic name.
- Update all callers (`planner.py`, API, tests) to handle `None`/missing company gracefully (default ticker fallback or 400/404).

**2.4 Eliminate `model_construct` wrap-mode or add round-trip validation** (`src/retrieval/dense_search.py`, `src/retrieval/reranker.py`)
- Replace `SearchResultItem.model_construct(...)` with validated `SearchResultItem(...)` construction, OR keep the performance optimization but add tests asserting every produced item round-trips through `SearchResultItem.model_validate(item.model_dump())` without error.
- Remove unused `math` import in `src/storage/database.py`.
- Audit `src/schemas/__init__.py`: if re-exports are unused, remove or document.

**2.5 Add targeted tests** (`tests/test_verification.py`, `tests/test_extraction_quarterly.py`)
- Parametrized tests for the verification status machine: exact match → VERIFIED; mismatch → CONTRADICTED; missing fact → UNVERIFIED; multiple matches → AMBIGUOUS; demo data → UNVERIFIED even when numerically equal.
- Parametrized tests for quarterly extraction: Q1/Q2/Q3/Q4/FY values surface correctly; YoY/QoQ only when periods exist; division-by-zero guarded.
- Reranker boost contract tests (already exist; keep and extend).

**Stage 2 Validation:**
- `pytest tests/` passes including new verification/quarterly test files.
- No `model_construct` usage without a corresponding round-trip validation test.
- `get_company_by_ticker("NONEXISTENT")` does not return a fabricated CIK.
- `DemoDataGenerator` and `SecCompanyFactsClient` are separately importable and testable without network (SEC client tests use `responses`/monkeypatch or httpx mock).

---

## Stage 3: Production Hardening & Observability (P2)

**Entry criteria:** Stage 2 complete and validated.
**Exit criteria:** Auth/z middleware present (opt-in); rate limiter/metrics work across workers or are explicitly documented as single-process; SQLite schema migration tooling; dashboard assets vendored for offline use; health check is a real DB connectivity probe.

### Stage 3 Tasks

**3.1 Add opt-in API authentication/authorization** (`src/api/app.py`, new `src/api/auth.py`)
- API-key or bearer-token middleware gating state-changing/`/api/query` endpoints, enabled via `ENABLE_AUTH` env var.
- When disabled (default for local demo), behavior is unchanged; when enabled, missing/invalid token returns 401.
- Document in `docs/reference.md` and `docs/how-to.md`.
- Do not implement full identity/tenant management; note it as out of scope for local production.

**3.2 Make rate limiter and metrics cross-process or document single-process boundary** (`src/api/ratelimit.py`, `src/api/metrics.py`, `src/api/app.py`)
- Option A: Redis-backed sliding window counter and metrics (add `redis` to requirements, fallback to in-process when Redis unavailable).
- Option B: Keep in-process but explicitly document that `--workers > 1` requires an external store; add a startup warning when multiple workers are detected without Redis.
- Choose Option A if Redis is already acceptable; otherwise Option B with clear documentation. Either way, the `/api/metrics` endpoint must not claim cross-worker accuracy it doesn't have.

**3.3 Add SQLite schema migration tooling** (new `src/storage/migrations.py` or scripts)
- Schema version table (`schema_migrations` with `version` + `applied_at`).
- Migration runner that applies numbered SQL migration files in order, idempotently.
- At least one migration representing the current schema as v1 so future changes have a path.
- Document migration workflow in `docs/how-to.md`.

**3.4 Vendoring dashboard assets for offline use** (`src/web/static/`, `src/web/templates/index.html`)
- Replace Tailwind CDN script and Font Awesome CDN stylesheet with pinned, locally vendored copies (or inline minimal CSS).
- Verify dashboard loads without external network access.
- Update `docs/architecture.md` limitations section to reflect offline capability.

**3.5 Harden health check** (`src/api/app.py`)
- `GET /health` performs an actual SQLite connectivity probe (`SELECT 1`) and reports `database: connected` only if the probe succeeds, plus honest row counts.
- Add `database` latency or error detail when the probe fails.

**Stage 3 Validation:**
- Auth middleware returns 401 without token when `ENABLE_AUTH=true`; unchanged behavior when unset.
- Rate limiter/metrics behave consistently under the chosen cross-process or documented single-process model.
- Migration runner applies v1 schema idempotently to a fresh DB.
- Dashboard loads offline (no CDN requests in browser DevTools network tab).
- `/health` fails gracefully when the DB file is missing or locked.

---

## Stage 4: Resume-Ready Polish & CI Maturity (P3)

**Entry criteria:** Stage 3 complete and validated.
**Exit criteria:** OpenAPI docs enriched, API versioning, structured JSON logging, graceful shutdown, README badges, CONTRIBUTING review checklist updated, CI runs lint/typecheck, project presents as a credible senior-engineer portfolio piece.

### Stage 4 Tasks

**4.1 Enrich OpenAPI / interactive docs** (`src/api/app.py`)
- Add `summary`, `description`, `response_description`, and `examples` to all endpoints.
- Tag endpoints (`companies`, `facts`, `search`, `query`, `metrics`, `health`).
- Add a `422`/`400`/`500` response schema to `/api/query` and `/api/search`.
- Verify `/docs` and `/openapi.json` render correctly.

**4.2 API versioning** (`src/api/app.py`)
- Add `/api/v1/` prefix route mounting or `X-API-Version` header; document versioning policy in `docs/reference.md`.

**4.3 Structured logging & graceful shutdown** (`src/api/app.py`, `src/storage/database.py`)
- JSON-structured logs (or at minimum consistent `logging.getLogger(__name__)` usage with correlated request IDs).
- Graceful shutdown on SIGTERM: close DB connections, flush metrics.
- Startup log: version, data mode, DB path, company/fact/chunk counts.

**4.4 CI lint & typecheck** (`.github/workflows/ci.yml`, `requirements.txt`)
- Add `ruff` (lint + format check) and `mypy` (typecheck) to requirements and CI.
- CI job: `ruff check .`, `ruff format --check`, `mypy src/`.
- Fix any lint/type errors introduced by prior stages.

**4.5 README & CONTRIBUTING polish**
- Add build/CI status badges, quick-start copy-paste commands for Windows PowerShell and Bash, and a "production readiness" section stating what is and isn't production-grade.
- Update CONTRIBUTING review checklist with the new quality gates (lint, typecheck, full benchmark, offline dashboard).
- Add `AGENTS.md` or `.kilo/` guidance if the repo adopts Kilo tooling (optional, per repo conventions).

**4.6 Final full-repo verification**
- Run `pytest tests/` → 100% pass.
- Run full eval → gates pass.
- Run `ruff` + `mypy` → clean.
- Build Docker image + `docker compose up` → `/health` returns 200, dashboard loads.
- Generate a fresh `eval_results.json` and commit it.

**Stage 4 Validation:**
- `pytest`, `ruff`, `mypy`, CI pipeline all green.
- Docker build + compose smoke test passes.
- `/docs` OpenAPI UI loads; `/openapi.json` valid.
- README accurately describes production boundaries.

---

## Risks & Rollback

| Risk | Likelihood | Impact | Mitigation / Rollback |
|------|------------|--------|----------------------|
| Verification rewrite breaks existing demo expectations | Medium | High | Keep existing tests as regression baseline; add new status-machine tests before removing old behavior; run full eval after each change |
| Dense-index refresh adds startup latency | Low | Medium | Lazy refresh only on revision change; benchmark hot path stays <25ms (existing perf test) |
| Auth middleware breaks local demo UX | Low | Low | Opt-in via env var; default unchanged |
| Redis dependency adds operational complexity | Medium | Medium | Fallback to in-process with explicit single-process warning; document clearly |
| Vendored assets drift from CDN versions | Low | Low | Pin exact versions; document upgrade path |
| CI gates too strict/loose after fixes | Medium | Medium | Base thresholds on measured post-fix metrics, not aspirational targets |

Rollback strategy: each stage is committed as its own PR/branch. If a stage fails validation, revert that branch and re-scope before proceeding. No stage depends on unverified output from a later stage.

---

## Open Questions / Decisions Needed (resolve before implementation)

1. **Auth scope:** Add API-key bearer auth (opt-in) or keep the API unauthenticated with explicit local-only documentation? Recommendation: opt-in API-key middleware via `ENABLE_AUTH`/`API_KEY` env vars.
2. **Rate limiter/metrics:** Redis-backed cross-process or documented single-process with in-process fallback? Recommendation: try Redis with graceful in-process fallback; if Redis is undesirable, document single-process boundary clearly.
3. **Agent naming:** Rename `ResearchOrchestrator`/`*Agent` to pipeline semantics (`ResearchPipeline`/`*Step`) or implement real agent messaging? Recommendation: keep class names but add a comment/docstring clarifying it's a staged pipeline; full agent messaging is out of scope for this plan.
4. **Plan file location:** This plan is written to `plans/1793449090300-production-readiness.md`. Confirm this location is acceptable, or move to `.kilo/plans/` if the repo adopts Kilo tooling conventions.

---

## Implementation Handoff

This plan is implementation-ready. An implementation-capable agent should:
1. Execute Stage 1 tasks in order, validating after each task.
2. Proceed to Stage 2 only after Stage 1 exit criteria are met.
3. Update this plan file with completion notes and any scope changes as stages complete.
4. Call `plan_exit` with this path when all stages are done, or keep refining if open questions remain.

**Plan file:** `plans/1793449090300-production-readiness.md`