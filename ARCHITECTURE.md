# Technical Architecture & System Design

This file is a concise map of the Financial Filing Research Copilot. The end-to-end data flow, design choices, trust boundaries, limitations, and prioritized future scope are documented in [docs/architecture.md](docs/architecture.md).

## System overview

The application is a local FastAPI service with a vanilla JavaScript dashboard, SQLite storage with versioned SQL migrations, FTS5 lexical retrieval, a scikit-learn TF-IDF retrieval channel, Redis-backed sliding-window rate limiting & metrics (with zero-dependency local fallback), JWT/API-key multi-tenant authentication, and a typed Python agent pipeline featuring multimodal SVG chart & financial statement synthesis. It does not use an LLM service in its query path.

The default `demo` mode is deterministic generated data. The opt-in `sec` mode fetches SEC Company Facts structured data for supported companies/periods; live filing-text ingestion is not implemented. SEC fetch failures are explicit and do not substitute demo content.

## Component flow

```text
Seed script → demo generator OR SEC Company Facts client → SQLite (Migrations 001, 002)
Browser → FastAPI (Redis/Local Metrics & Sliding Rate Limiter + Auth Middleware)
            └─ ResearchOrchestrator
                 ├─ PlannerAgent
                 ├─ RetrievalAgent (FTS5 + TF-IDF → RRF → heuristic reranker)
                 ├─ FinancialExtractionAgent
                 ├─ FinancialAnalysisAgent
                 ├─ VerificationAgent
                 ├─ MultimodalVisualizerAgent (SVG Performance Charts & Statements)
                 └─ ReportWriterAgent
Evaluator → demo golden dataset → retrieval + orchestrator → metrics JSON
```

## Package map

- `src/api`: FastAPI routes, CORS, Redis-backed sliding-window rate limiting & latency percentiles (with zero-dependency local fallback), JWT/API-key auth service & routes.
- `src/schemas`: Pydantic models for facts, chunks, plans, citations, claims, reports, and multimodal visual artifacts.
- `src/ingestion`: supported company list with fiscal year-end specifications, deterministic demo generator, opt-in SEC structured-facts client.
- `src/storage`: SQLite persistence, schema migrations (`001__initial_schema.sql`, `002__auth_and_tenants.sql`), provenance filters, FTS5 maintenance, and search queries.
- `src/retrieval`: TF-IDF cosine search, BM25/RRF fusion, and query-conditional heuristic reranking.
- `src/agents`: planning, retrieval, extraction, risk-passage selection, conservative verification, multimodal SVG chart & table synthesis, and report writing.
- `src/eval` and `scripts`: deterministic demo benchmark and its runner/generator.
- `src/web`: dashboard template and static browser code with client-side visual artifact rendering.

## Important invariants

1. Provenance is carried through facts, chunks, citations, reports, and visual artifacts; selected data mode filters retrieval before top-k selection.
2. Demo values and qualitative excerpts are not labeled SEC-verified; synthetic visual artifacts carry explicit `demo` badges.
3. An explicitly requested but unavailable fiscal period remains unverified rather than borrowing another period.
4. FTS is derived from canonical `document_chunks`; storage replacement and initialization maintain/rebuild the index.
5. All schema changes are applied through versioned, idempotent SQL migration files (`schema_migrations`).
6. Observability and rate limiting use Redis when configured (`REDIS_URL`) and gracefully degrade to deterministic in-process structures when Redis is offline.

For setup, endpoints, configuration, CI, Docker, and script contracts, see the [documentation hub](docs/index.md).
