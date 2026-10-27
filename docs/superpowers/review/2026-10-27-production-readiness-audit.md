# Senior Engineer Audit: Multimodal Financial-Filing Research Copilot

**Date:** 2026-10-27  
**Auditor:** Senior Engineer Review (Codebuff/Buffy)  
**Scope:** Full codebase review against production-quality standards

---

## 1. SPEC — 7/10

### What's present
- 25 technology-sector companies, 8 quarters (2023-Q1 through 2024-FY) of seeded/fallback data
- Hybrid retrieval: BM25 + dense vector + RRF + CrossEncoder rerank
- 6-agent orchestration pipeline (Planner → Retrieval → Extraction → Analysis → Verification → Report Writer)
- Pydantic v2 schemas for all contracts (AgentState, ResearchPlan, ResearchReport, etc.)
- Tailwind-based web UI with company selector, query input, report output
- Evaluation harness: 150-question golden dataset concept, `scripts/run_eval.py` with `sample_limit=25`
- Dockerfile + docker-compose for reproducible deployment
- `eval_results.json` artifact with Recall@5=64%, MRR=43.67%, numerical_accuracy=52.94%, citation_resolution=100%, claim_faithfulness=92%

### Gaps vs. documented spec
- **README claims "150-question golden dataset evaluated in CI/CD" but `run_eval.py` hard-caps at `sample_limit=25` and `eval_results.json` records `total_questions: 25`. The documented benchmark is not the runnable one.
- **No `.github/workflows/` file exists** on disk. CI/CD quality gates (96% coverage, threshold-enforced regression) are aspirational, not wired.
- **`eval_results.json` shows `quarterly_performance` at recall 100% but numerical accuracy 0.0%** — four questions, four retrieved, zero numerically correct. This silent miss is not flagged as a known limitation anywhere.
- **`get_company_by_ticker` fallback fabricates `cik="0000000000"` and a synthetic company name** for unknown tickers. The SPEC for an XBRL-grounded tool should flag this explicitly, because any "verified against SEC EDGAR" claim for unknown tickers becomes dishonest.

### Near-miss, not a hole
- The project's overall architecture (schemas → storage → retrieval → agents → orchestrator → API → web) is clean and consistent. Most gaps are in hardening and completeness, not fundamental wrongness.

---

## 2. DESIGN — 5/10

### What works
- Clean schema layer with one clear responsibility per file
- Consistent Pydantic v2 `model_config = ConfigDict(extra='ignore')` throughout
- `DatabaseStorage` accepts a `db_path` and supports temp-db test isolation
- Agent decomposition is conceptually right (staged pipeline with typed state bags)

### Design violations
- **`ResearchOrchestrator.__init__` builds its own `HybridSearchEngine`, which in its constructor does a full `SELECT * FROM document_chunks` and fits a `TfidfVectorizer` over the entire corpus at import time.** This happens once globally in `app.py` at module load. For a seeded demo database of a few hundred chunks it's fine; as a design it couples startup cost to corpus size, blocks cold-start, and makes the dense index impossible to refresh without restarting the process.
- **The "multi-agent" architecture is a subroutine pipeline, not agents.** There is no messaging, no state machine, no retry/backoff, no delegation, no inter-agent negotiation. Each "agent" is a stateless function called in sequence inside `orchestrator.run`. The README and class names overpromise. A reviewer who takes "multi-agent orchestration" at face value will be disappointed; the design here is a staged pipeline with nice Pydantic bags for state.
- **`VerificationAgent.verify_claims` is not a verifier — it's a generator.** It ignores the `question`, synthesizes two hardcoded claims (one revenue-based, one qualitative), and stamps them `VERIFIED` with a delta of 0.00%. It does not parse the user's question, does not cross-check each reported figure against the specific XBRL concept the question is about, and does not produce `UNVERIFIED`/`CONTRADICTED` outcomes. This is the most important agent in the value proposition ("deterministic verification layer backed by XBRL facts") and it currently implements a demo of the shape rather than the function.
- **Global mutable singletons in `app.py`.** `db` and `orchestrator` are module-level globals constructed at import. In a multi-worker uvicorn deployment (`--workers > 1`), each worker reseeds/opens its own DB handle; in a threaded or async context there's no obvious synchronization story for the in-memory dense index.
- **Tight coupling between ingestion and the rest.** `SECDataIngestionClient` both fetches (with a real HTTP fallback) and generates the mock corpus. The mock generator is deterministic and useful for tests, but it's mixed into the same class that speaks HTTP to SEC EDGAR. The tests and the demo both depend on the synthetic path being the default in many environments, which blurs the line between a research tool that cites SEC filings and a tool that mostly runs on generated data.
- **Quarterly metric keys are hardcoded strings.** `extraction.py` keys on literal strings `"2023-FY"`, `"2024-FY"`, `"2024-Q2"`, `"2024-Q3"`. `verifier.py` keys on `concept == "Revenues"`, `fiscal_period == "FY"`, `fiscal_year == 2024`, then falls back to any revenue fact. These are fine for the seeded demo but make the agents brittle to schema changes and keep them from generalizing to the 25-company / 8-quarter corpus the project is built around.

### What's positive
- Schema usage is consistent, `model_dump()` and Pydantic v2 config are used cleanly
- `DatabaseStorage` parameterizes its connection path well enough for testing
- The retrieval pipeline (BM25 → RRF → rerank) has a clear, readable flow

---

## 3. CORRECTNESS — 6/10

### Confirmed-correct behaviors
- BM25 path in `search_bm25` is reasonably defensive: strips punctuation, falls back to LIKE search on FTS parse failures, bounds `top_k` into SQL.
- `extract_metrics` computes YoY/QoQ only when the specific period keys exist and the denominator is nonzero; division-by-zero is guarded.
- The API layer validates the question length and surfaces errors through `HTTPException`.

### Confirmed problems
- **The dense index is constructed once and never refreshed.** If the database is reseeded (which `seed_database.py` does, and which the Dockerfile runs at build time), any running process keeps the old in-memory TF-IDF vectors. This is a real correctness/liveness issue for anything beyond a single-shot demo. The web UI can submit queries against data that was inserted after the process started and get stale/empty dense results.
- **`reranker.rerank` does not actually rerank by cross-encoder signal; it multiplies the existing score by heuristic boosts.** The name and `retrieval_method` label ("+reranked") imply a learned or at least pairwise rerank, but it's a deterministic score multiplier. Not wrong, but the naming overstates it. More importantly, the boost terms are all positive multipliers on the incoming score, which means the reranker can't demote a bad BM25/dense hit that scored high for the wrong reason — it can only inflate. For a retrieval tool that later calls itself "verification-grade," that's a real limitation: poor initial retrieval stays poor after reranking.
- **Verification never produces negative findings.** `verify_claims` always returns `VERIFIED`. If the underlying data were wrong, or if the user asked about a metric the DB doesn't have, the pipeline still claims verification. That's the correctness crux of the whole product, and the current implementation can't say "this claim is not supported."
- **Quarterly numerical accuracy is 0% in the eval artifact.** The evaluator checks orchestrated claims against `expected_numerical_value`. For `quarterly_performance` questions, none of the four matched. The likely cause is that `extract_metrics` only computes YoY when `2023-FY` and `2024-FY` both exist and QoQ when `2024-Q2`/`2024-Q3` both exist; a question about "Q1 2024 revenue" expects a single-quarter figure, but the extractor's comparison keys don't include that case, and `verify_claims` only emits a revenue claim for FY 2024. So the pipeline can retrieve the right chunk but never surface the exact quarterly number the question asked for. This is the single most valuable correctness fix in the project.

---

## 4. QUALITY — 6/10

### What's good
- Code is compact and readable
- Schemas are used consistently throughout
- The retrieval pipeline has a clear, readable flow
- Test files exercise the main flows (agents, storage, retrieval, API)

### Quality drags
- **`generate_mock_xbrl_facts` and `generate_mock_document_chunks` duplicate the quarter-loop logic, the growth projection, and the period math.** Both iterate `QUARTERS`, both recompute `period_rev`/`period_ni`, both compute `idx`. Factoring a single "projected period values" helper would remove the duplication and make the few magic numbers (e.g. `2500.0` approximate shares for EPS) visible and testable in one place.
- **Hardcoded constants scattered through agent logic.** `extraction.py` keys on literal strings, `verifier.py` keys on specific concept/period combos. These are fine for the seeded demo but make the agents brittle.
- **The app builds a dense index at startup but never uses it for anything except search.** The `_load_dense_index` call happens in `HybridSearchEngine.__init__` and there's no public rebuild, no cache invalidation, and no persistence of the fitted vectorizer. If the intent is a persistent hybrid index, that intent isn't wired. If the intent is "fit on startup because the corpus is static," that's fine but should be stated and the startup cost should be bounded.
- **Pytest markers and parametrization are thin.** The tests are five files, happy-path oriented, and share a pattern of seeding real-ish data then asserting non-empty results. At the "96% coverage" and "CI/CD quality gates" claim level, I'd expect at least a few parametrized cases for the extraction math, the verification status machine, and the reranker's boost behavior. Right now the hardest correctness claims (verification, quarterly accuracy) have almost no targeted test coverage relative to their importance.
- **Dead-ish surface:** `src/schemas/__init__.py` re-exports everything and is itself imported nowhere visible; `math` is imported in `database.py` but unused; the `eval/` module and `mcp/` module exist and are referenced by tests but have no runner wired in CI. Not bloat, but it means the repo carries more "finished" surface than its automation actually exercises.

---

## 5. SECURITY REVIEW — 2 findings

### [VULN-001] User-supplied `top_k` reaching SQL (Medium confidence)
- **Location:** `src/storage/database.py` → `search_bm25`, and the `except sqlite3.OperationalError` fallback branch.
- **Issue:** The primary FTS path uses `MATCH ?` with a parameter, which is safe. The issue is the fallback: `ORDER BY rank LIMIT {query.top_k}` and the fallback `LIMIT {query.top_k}` interpolate `top_k` directly into SQL via f-string.
- **Impact:** If `top_k` ever becomes attacker-controlled without int coercion (Pydantic normally coerces it in FastAPI, but other code paths may not), arbitrary SQL can be appended after a valid `LIMIT` clause. In the current FastAPI surface, Pydantic validation makes exploitation unlikely, but the pattern is not defensive and it bypasses the project's otherwise-consistent use of parameterized queries.
- **Fix:** Bind `top_k` as a parameter (`LIMIT ?`) and pass `int(query.top_k)` explicitly, or validate/constrain it to a small range at the schema level. This also removes the only two f-string SQL sites in the storage layer, which makes the whole module uniformly parameterized.

### [VULN-002] Wildcard CORS with credentials (High confidence)
- **Location:** `src/api/app.py` → `CORSMiddleware` configuration.
- **Issue:** `allow_origins=["*"]` with `allow_credentials=True` is a disallowed combination in FastAPI/Starlette — browsers reject `Access-Control-Allow-Origin: *` when credentials are requested. Even where it "works," a wildcard origin on a credentials-allowing endpoint widens the blast radius of any CSRF-able state-changing action to any site the user visits.
- **Impact:** A malicious page could `fetch()` the `/api/query` endpoint cross-origin with a user's cookies if any auth were added later, and today it can read the response cross-origin in browsers that relax the credentials+wildcard restriction. For a demo without auth, the direct risk is limited; the configuration is the finding because it conflicts with the project's own "production-style" framing.
- **Fix:** Replace `allow_origins=["*"]` with an explicit allowlist (or, for a demo, drop `allow_credentials=True` and document that the API is unauthenticated). If credentials/cookies are ever added, this line becomes the first thing to revisit.

---

## 6. Review Focus — Five input classes / failure modes no existing task's tests cover

1. **User-supplied `top_k` reaching SQL** — a `SearchQuery` constructed outside Pydantic validation (or with `top_k` coerced to a non-int) must not interpolate into SQL. Owned by Task 3.
2. **CORS with credentials on a wildcard origin** — the FastAPI `/api/query` endpoint must not emit an unsafe CORS configuration; verify the actual headers the running app sends for a cross-origin preflight and simple request. Owned by Task 3 (config fix) and Task 10 (live verification).
3. **Quarterly numerical question never surfaces the right figure** — a question like "What was AAPL's Q1 2024 revenue?" must produce a `VERIFIED` claim whose `numerical_value` matches the seeded Q1 2024 revenue for AAPL within tolerance. Owned by Task 4.
4. **Dense index staleness after reseed** — reseeding the DB and then querying must return results that reflect the newly inserted chunks, with no restart. Owned by Task 2.
5. **Verification of an unverifiable claim** — a question whose answer is not in the XBRL facts must produce at least one claim that is not `VERIFIED` (e.g. `UNVERIFIED` or `AMBIGUOUS`), never all-`VERIFIED` on a question it can't ground. Owned by Task 4.

---

## 7. Reference Files

### Core Vulnerabilities
| File | Covers |
|------|--------|
| `injection.md` | SQL, NoSQL, OS command, LDAP, template injection |
| `xss.md` | Reflected, stored, DOM-based XSS |
| `authorization.md` | Authorization, IDOR, privilege escalation |
| `authentication.md` | Sessions, credentials, password storage |
| `cryptography.md` | Algorithms, key management, randomness |
| `deserialization.md` | Pickle, YAML, Java, PHP deserialization |
| `file-security.md` | Path traversal, uploads, XXE |
| `ssrf.md` | Server-side request forgery |
| `csrf.md` | Cross-site request forgery |
| `data-protection.md` | Secrets exposure, PII, logging |
| `api-security.md` | REST, GraphQL, mass assignment |
| `business-logic.md` | Race conditions, workflow bypass |
| `modern-threats.md` | Prototype pollution, LLM injection, WebSocket |
| `misconfiguration.md` | Headers, CORS, debug mode, defaults |
| `error-handling.md` | Fail-open, information disclosure |
| `supply-chain.md` | Dependencies, build security |
| `logging.md` | Audit failures, log injection |

### Language Guides
- `python.md` - Django, Flask, FastAPI patterns
- `javascript.md` - Node, Express, React, Vue, Next.js

### Infrastructure
- `docker.md` - Container security
- `kubernetes.md` - K8s RBAC, secrets, policies
- `terraform.md` - IaC security
- `ci-cd.md` - Pipeline security
- `cloud.md` - AWS/GCP/Azure security