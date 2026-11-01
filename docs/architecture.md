# Architecture and design

## System context

The Financial Filing Research Copilot is a modular, high-integrity financial research platform. A browser-based dashboard calls a FastAPI application. The API coordinates a typed Python pipeline, which reads a SQLite database containing company records, structured XBRL facts, and searchable document chunks. SQLite FTS5 provides lexical retrieval; an in-process scikit-learn TF-IDF index supplies a second retrieval channel. No hosted external model provider or external inference service is part of the core query path, providing deterministic execution, low latency, and zero data leakage.

The project is deliberately honest about its data boundary:

- **Demo mode** is deterministic generated data, not reported company information.
- **SEC mode** makes explicit outbound requests to SEC Company Facts and stores supported structured facts only.
- Synthetic narrative chunks have `demo://` source URLs. SEC mode does not ingest filing text or generate SEC narrative citations.
- A demo value can be numerically matched to the demo fixture, but that does not make it SEC-verified. Qualitative excerpts remain unverified because there is no semantic entailment model.
- Multimodal visual artifacts generated from facts (SVG trend charts, operations statements) carry explicit `demo` badges when operating in demo mode.

## Component map

```text
Browser dashboard (vanilla JS)
        │ same-origin HTTP (with Bearer Token / API Key)
        ▼
FastAPI application (src/api)
  ├── health, companies, facts, search, query, metrics, auth
  ├── Redis-backed sliding-window rate limiting & percentiles (with local fallback)
  ├── AuthMiddleware: multi-tenant RBAC (admin, analyst, viewer) & API key validation
  └── ResearchOrchestrator
        ├── PlannerAgent ── company/intent/section selection
        ├── RetrievalAgent ── facts + hybrid passage search
        │      ├── SQLite / FTS5 BM25
        │      └── TF-IDF cosine → reciprocal-rank fusion → heuristic reranker
        ├── FinancialExtractionAgent ── period aggregates and changes
        ├── FinancialAnalysisAgent ── retrieved risk disclosure excerpts
        ├── VerificationAgent ── fact selection and source-aware status
        ├── MultimodalVisualizerAgent ── SVG charts & structured financial tables
        └── ReportWriterAgent ── structured ResearchReport with visual artifacts

Seed script ── demo generators OR SEC Company Facts client ── SQLite (Migrations 001, 002)
Evaluator ── golden questions ── retrieval + orchestrator ── JSON metrics
```

Relevant packages:

| Area | Location | Responsibility |
|---|---|---|
| API and local web | `src/api`, `src/web` | HTTP contract, auth middleware, rate limits, dashboard assets |
| Auth & Multi-Tenancy | `src/api/auth*` | JWT tokens, password hashing, tenant-scoped workspaces, API keys |
| Contracts | `src/schemas` | Pydantic input, state, fact, citation, report, and visual models |
| Ingestion | `src/ingestion` | Supported companies with fiscal calendars, deterministic demo generator, SEC client |
| Persistence & Migrations | `src/storage` | SQLite schema migrations (`001`, `002`), provenance, FTS synchronization |
| Observability | `src/api/redis_observability.py` | Redis distributed sliding-window rate limiter & latency percentiles (with local fallback) |
| Retrieval | `src/retrieval` | TF-IDF dense search, BM25, RRF, heuristic reranking |
| Agents | `src/agents` | Plan, retrieve, extract, analyze, verify, synthesize visual charts, write |
| Evaluation | `src/eval`, `scripts/run_eval.py` | Fixed 150-question benchmark and quality metrics |
| Supporting tool adapter | `src/mcp` | Python helper methods; not a standalone MCP transport/server |

## Request and data flow

### Ingestion & Migration lifecycle

1. Storage initialization and startup automatically execute `src/storage/migrations.py`, discovering and running all pending `.sql` migration scripts (`001__initial_schema.sql`, `002__auth_and_tenants.sql`) within isolated transactions.
2. `scripts/seed_database.py` reads `DATA_MODE` (default `demo`) and builds all records before modifying the target database.
3. Demo mode generates three document chunks and three structured facts per company and period for the configured 25-company universe and eight periods (2023 Q1-Q3/FY and 2024 Q1-Q3/FY).
4. SEC mode calls the Company Facts endpoint with `SEC_USER_AGENT`, retaining supported 10-K/10-Q structured facts for fiscal years 2023-2024. It returns no filing-text chunks.
5. `DatabaseStorage.replace_seed_data` replaces facts and chunks transactionally and rebuilds the FTS content in the same transaction. A failed SEC fetch happens before replacement starts.
6. SQLite triggers advance the search-index revision when canonical chunks change. A `HybridSearchEngine` refreshes its in-memory dense index when the stored revision changes. Storage initialization reconstructs FTS rows from canonical chunks to repair stale legacy indexes.

### Research request lifecycle

1. `POST /api/query` checks optional authentication state (`request.state.auth`), validates question length and selected ticker, then calls the orchestrator.
2. The planner chooses ticker(s) from explicit uppercase ticker tokens or company names, classifies single-metric questions, and may request Item 8 as a section hint.
3. Retrieval filters by the selected data source, ticker(s), section, and query terms before applying result limits. It fuses BM25 and TF-IDF rankings with reciprocal-rank fusion, then applies query-conditional heuristic boosts.
4. The extractor groups available facts by concept and fiscal period and calculates available YoY/QoQ changes. These aggregate periods are descriptive output, not period-specific verification by themselves.
5. Risk analysis returns retrieved risk-marked source passages; it does not score risk severity or determine a trend.
6. The verifier selects an XBRL concept and honors explicit requested periods. A missing explicit period stays unverified. Demo facts stay unverified. SEC numerical claims require a matching SEC fact and a retrieved same-source/same-period chunk for a citation; SEC mode currently has no chunks, so numerical claims remain unverified in reports.
7. The multimodal visualizer (`MultimodalVisualizerAgent`) inspects extracted multi-period financial facts and synthesizes standalone vector SVG bar/trend charts (with axes, ticks, grid lines, and labels) and consolidated financial performance tables.
8. The writer returns a `ResearchReport` with source mode, claim status, citations, visual artifacts, caveats, and generated time.

### Retrieval design

- **Lexical channel:** SQLite FTS5 BM25 against `document_chunks_fts` joined to canonical `document_chunks`.
- **Dense channel:** `TfidfVectorizer` with one- and two-word n-grams, English stop words, and a maximum of 10,000 features; cosine similarity ranks the currently indexed chunk corpus. This is sparse lexical TF-IDF, not a neural embedding model.
- **Fusion:** Reciprocal-rank fusion uses rank positions, then the heuristic reranker boosts query-relevant terms and table structure. It is not a trained cross-encoder, and positive boosts cannot demote irrelevant candidates.
- **Candidate selection:** Each channel over-fetches a candidate set before fusion and final `top_k` truncation, improving chances that a relevant candidate reaches reranking.
- **Index lifecycle:** the dense index refreshes lazily using a SQLite revision fingerprint.

## Design decisions

### Versioned SQL migrations over raw service DDL

All database schemas (including initial tables, FTS virtual tables, and multi-tenant user/auth tables) are declared in `src/storage/migrations_sql/*.sql`. Schema application is transactional and recorded in `schema_migrations`, preventing runtime drift or startup table recreation bugs.

### Distributed observability with graceful local fallback

The metrics and rate-limiting tier uses Redis (`RedisRequestMetrics`, `RedisSlidingWindowRateLimiter`) when `REDIS_URL` is set, allowing coordinated rate limits and aggregated latency percentiles across multiple Uvicorn worker processes. When Redis is unavailable or unconfigured, the system automatically falls back to in-memory sliding-window structures without crashing or requiring external infrastructure.

### Multimodal presentation without heavy dependencies

Instead of requiring Node.js Puppeteer or external rasterization services, `MultimodalVisualizerAgent` generates standards-compliant SVG visualizations and semantic HTML/structured tables natively in Python. The resulting vectors are self-contained, responsive, resolution-independent, and render directly in any modern browser.

### Provenance is data, not presentation metadata

Facts, chunks, citations, and visual artifacts carry `data_source`. Search and fact queries filter to the configured mode before top-k selection. The report and UI show whether content is synthetic or SEC structured data. This guards against plausible-looking synthetic material accidentally being presented as a government filing.

### Verification is intentionally conservative

The verifier can compare a selected structured fact to the indexed value. It cannot prove that natural-language prose entails a claim, and it does not claim to. In the demo, even exact fixture matches are unverified. For SEC facts, the current report contract still requires a matching retrieved passage before marking a numerical claim verified; this conservative policy means SEC facts without filing-text context are not promoted to verified claims.

## Limitations and trust boundaries

- **Data accuracy:** generated demo values and filing-like prose are synthetic. SEC mode reads structured Company Facts only and its supported years/forms are limited.
- **Filing context:** filing text, pagination, amendment/restatement selection, and source-grounded SEC narrative citations are not implemented.
- **Claim semantics:** qualitative claims are quoted source context and remain unverified. Numerical equality against the same indexed source is not independent validation.
- **Risk analysis:** retrieved risk passages are surfaced; severity, novelty, and trend are not assessed.
- **Coverage:** the company universe and periods are fixed in code; SEC mode may return different facts or no supported facts for a particular company.
- **Period interpretation:** the verifier supports explicit quarter/year matching across standard and off-calendar fiscal year ends (e.g., AAPL 09-30, MSFT 06-30, NVDA 01-31), but not arbitrary unstructured prose or restatements.

Do not use this application as investment advice or rely on its output for trading, compliance, or filing analysis without independent source review.

## Related guides

- [Local first-run tutorial](tutorial-local.md)
- [How-to guides](how-to.md)
- [Technical and API reference](reference.md)
- [Documentation hub](index.md)
