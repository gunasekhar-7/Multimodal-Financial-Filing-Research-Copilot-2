import asyncio
import logging
import os
import time
import uuid

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from src.agents.orchestrator import ResearchOrchestrator
from src.api.auth import (
    AuthMiddleware,
)
from src.api.auth_models import AuthContext
from src.api.auth_routes import router as auth_router
from src.api.auth_service import AuthService
from src.api.redis_observability import (
    RedisRequestMetrics,
    RedisSlidingWindowRateLimiter,
    get_redis,
)
from src.schemas.financial import (
    CompanyInfo,
    DataSource,
    SearchQuery,
    SearchResultItem,
    XBRLFact,
)
from src.schemas.reports import ResearchReport
from src.storage.database import DatabaseStorage

logger = logging.getLogger(__name__)

app = FastAPI(
    title="Multimodal Financial-Filing Research Copilot API",
    description=(
        "Local research copilot for SEC filings, XBRL structured data, and "
        "claim verification. Demo mode uses deterministic synthetic data; "
        "SEC mode reads structured Company Facts from SEC EDGAR only. "
        "Not investment advice."
    ),
    version="1.2.0",
    contact={
        "name": "Financial Filing Research Copilot",
        "url": "https://github.com/Kilo-Org/kilocode",
    },
    openapi_tags=[
        {"name": "health", "description": "Service health and connectivity probes."},
        {
            "name": "auth",
            "description": "User registration, login, tokens, and API keys.",
        },
        {
            "name": "companies",
            "description": "List supported companies and their CIK metadata.",
        },
        {
            "name": "facts",
            "description": "Query structured XBRL facts by ticker, concept, and period.",
        },
        {
            "name": "search",
            "description": "Hybrid retrieval (BM25 + TF-IDF) over filing document chunks.",
        },
        {
            "name": "query",
            "description": "Run a full research query through the agent pipeline.",
        },
        {
            "name": "metrics",
            "description": "Operational counters and latency percentiles.",
        },
    ],
)

# CORS: explicit localhost origins only — never wildcard with credentials.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost",
        "http://localhost:3000",
        "http://127.0.0.1",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global DB and Orchestrator instances
db = DatabaseStorage(db_path=os.getenv("DATABASE_PATH", "financial_copilot.db"))
orchestrator = ResearchOrchestrator(db=db)
request_metrics = RedisRequestMetrics()
rate_limiter = RedisSlidingWindowRateLimiter()
auth_service = AuthService(db)

# Endpoints the per-IP budget and latency tracking apply to.
TRACKED_POST_PATHS = {"/api/query", "/api/search"}
V1_TRACKED_POST_PATHS = {"/api/v1/query", "/api/v1/search"}

# Paths requiring authentication when AUTH_REQUIRED is set.
AUTH_PROTECTED_POST_PATHS = {"/api/query", "/api/search", "/api/auth/keys"}
AUTH_PROTECTED_GET_PATHS = {"/api/facts", "/api/companies", "/api/auth/me"}

APP_VERSION = "1.2.0"


def _auth_required() -> bool:
    return os.getenv("AUTH_REQUIRED", "").strip().lower() in {"1", "true", "yes", "on"}


def _is_public_path(path: str) -> bool:
    return path in {
        "/",
        "/health",
        "/api/metrics",
        "/docs",
        "/openapi.json",
    } or path.startswith(("/static", "/api/v1/health", "/api/auth"))


# Add the full auth middleware.
app.add_middleware(AuthMiddleware, db=db, auth_service=auth_service)

# Include auth routes.
app.include_router(auth_router)


@app.middleware("http")
async def request_id_and_logging(request: Request, call_next):
    """Assign a request ID, log structured request/response, and track rate/latency."""
    request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
    start = time.perf_counter()
    path = request.url.path
    method = request.method
    client_ip = request.client.host if request.client else "unknown"

    # Attach auth context to request state for downstream use.
    request.state.auth = getattr(request.state, "auth", None)

    # Rate limit tracked POST paths before processing.
    tracked = TRACKED_POST_PATHS | V1_TRACKED_POST_PATHS
    if method == "POST" and path in tracked:
        allowed, retry_after = rate_limiter.check(client_ip)
        if not allowed:
            logger.warning(
                "rate_limit_exceeded",
                extra={
                    "request_id": request_id,
                    "client_ip": client_ip,
                    "path": path,
                    "retry_after": retry_after,
                },
            )
            return JSONResponse(
                status_code=429,
                content={
                    "detail": "Rate limit exceeded. Try again later.",
                    "request_id": request_id,
                },
                headers={"Retry-After": str(retry_after), "X-Request-Id": request_id},
            )

    response = await call_next(request)

    latency_ms = round((time.perf_counter() - start) * 1000.0, 2)
    response.headers["X-Request-Id"] = request_id

    if method == "POST" and path in tracked:
        request_metrics.note_request()
        request_metrics.record(path, latency_ms)

    logger.info(
        "request",
        extra={
            "request_id": request_id,
            "method": method,
            "path": path,
            "status_code": response.status_code,
            "latency_ms": latency_ms,
            "client_ip": client_ip,
        },
    )
    return response


@app.get(
    "/health",
    tags=["health"],
    summary="Health check",
    description="Probe SQLite connectivity and report service status.",
)
def health_check():
    """Health check with real SQLite connectivity probe."""
    db_ok = False
    db_error = None
    try:
        with db.get_connection() as conn:
            conn.execute("SELECT 1").fetchone()
        db_ok = True
    except Exception as exc:  # noqa: BLE001
        db_error = str(exc)

    data_mode = os.getenv("DATA_MODE", "demo").lower()
    status_val = "healthy" if db_ok else "degraded"
    return {
        "status": status_val,
        "version": APP_VERSION,
        "database": "connected" if db_ok else "disconnected",
        "database_error": db_error,
        "companies_count": len(db.get_all_companies()) if db_ok else 0,
        "xbrl_facts_count": db.get_fact_count() if db_ok else 0,
        "document_chunks_count": db.get_chunk_count() if db_ok else 0,
        "data_mode": data_mode,
        "demo_data": data_mode == "demo",
        "auth_required": _auth_required(),
    }


@app.get(
    "/api/metrics",
    tags=["metrics"],
    summary="Operational metrics",
    description="Process uptime, request count, p50/p95 latency, and dense-index freshness.",
)
def get_metrics():
    """Operational signal: uptime, request counters, p50/p95 latency, index freshness.

    Metrics and rate limits are process-local. In multi-worker deployments
    each worker maintains its own counters; use an external store for
    coordinated observability.
    """
    dense = orchestrator.search_engine.dense_search
    return {
        "uptime_seconds": round(time.time() - request_metrics.started_at, 1),
        "request_count": request_metrics.request_count,
        "latency_ms": {
            path: request_metrics.summary(path)
            for path in sorted(TRACKED_POST_PATHS | V1_TRACKED_POST_PATHS)
        },
        "dense_index": {
            "initialized": dense.doc_vectors is not None,
            "last_refresh": orchestrator.search_engine.last_index_refresh,
        },
        "process_local": get_redis() is None,
        "redis_connected": get_redis() is not None,
        "version": APP_VERSION,
    }


class ResearchRequest(BaseModel):
    question: str = Field(
        ...,
        description="Research question (min 3 characters)",
        json_schema_extra={
            "example": "What was Apple's total revenue in 2024 compared to 2023?"
        },
    )
    ticker: str | None = Field(
        default="AAPL",
        description="Target company ticker symbol",
        json_schema_extra={"example": "AAPL"},
    )


def _get_auth_context(request: Request) -> AuthContext | None:
    auth = getattr(request.state, "auth", None)
    if auth is None and _auth_required():
        raise HTTPException(
            status_code=401,
            detail="Authentication required.",
            headers={"WWW-Authenticate": 'Bearer realm="financial-copilot"'},
        )
    return auth


@app.get(
    "/api/companies",
    tags=["companies"],
    response_model=list[CompanyInfo],
    summary="List companies",
    description="Return all supported companies with CIK, sector, and industry metadata.",
)
def get_companies(
    request: Request,
    page: int = Query(default=1, ge=1, description="Page number (1-indexed)"),
    size: int = Query(default=100, ge=1, le=500, description="Page size"),
):
    _get_auth_context(request)
    all_companies = db.get_all_companies()
    start = (page - 1) * size
    end = start + size
    return all_companies[start:end]


@app.get(
    "/api/facts",
    tags=["facts"],
    response_model=list[XBRLFact],
    summary="Query XBRL facts",
    description="Query structured XBRL facts filtered by ticker, concept, fiscal year, and period.",
)
def get_xbrl_facts(
    request: Request,
    ticker: str = Query(..., description="Company ticker symbol", examples=["AAPL"]),
    concept: str | None = Query(
        default=None, description="XBRL concept name", examples=["Revenues"]
    ),
    year: int | None = Query(default=None, description="Fiscal year", examples=[2024]),
    period: str | None = Query(
        default=None, description="Fiscal period (e.g. Q1, FY)", examples=["Q1"]
    ),
    page: int = Query(default=1, ge=1, description="Page number (1-indexed)"),
    size: int = Query(default=50, ge=1, le=500, description="Page size"),
):
    _get_auth_context(request)
    source = (
        DataSource.SEC_EDGAR
        if os.getenv("DATA_MODE", "demo").lower() == "sec"
        else DataSource.DEMO
    )
    facts = db.query_xbrl_facts(
        ticker=ticker, concept=concept, year=year, period=period, data_source=source
    )
    start = (page - 1) * size
    end = start + size
    paginated = facts[start:end]
    return paginated


@app.post(
    "/api/search",
    tags=["search"],
    response_model=list[SearchResultItem],
    summary="Search filing chunks",
    description="Hybrid retrieval (BM25 + TF-IDF + RRF + rerank) over document chunks.",
)
async def search_filings(request: Request, query: SearchQuery):
    _get_auth_context(request)
    source = (
        DataSource.SEC_EDGAR
        if os.getenv("DATA_MODE", "demo").lower() == "sec"
        else DataSource.DEMO
    )
    return await asyncio.to_thread(
        orchestrator.search_engine.search, query, data_source=source
    )


@app.post(
    "/api/query",
    tags=["query"],
    response_model=ResearchReport,
    summary="Run research query",
    description="Execute a full research query through the agent pipeline: plan, retrieve, extract, analyze, verify, and write a structured report.",
)
async def run_research_query(request: Request, req: ResearchRequest):
    _get_auth_context(request)
    if not req.question or len(req.question.strip()) < 3:
        raise HTTPException(
            status_code=400, detail="Research question must be at least 3 characters."
        )
    allowed_tickers = {company.ticker for company in db.get_all_companies()}
    if req.ticker and req.ticker.upper() not in allowed_tickers:
        raise HTTPException(
            status_code=400, detail="Choose a company from the supported company list."
        )

    try:
        report = await asyncio.to_thread(
            orchestrator.run,
            question=req.question,
            default_ticker=req.ticker or "AAPL",
        )
        return report
    except Exception:
        logger.exception("Error processing research query")
        raise HTTPException(
            status_code=500,
            detail="Research query failed. Check the server logs and confirm the selected data mode is configured.",
        )


# Static web app serving
static_dir = os.path.join(os.path.dirname(__file__), "..", "web")
if os.path.exists(static_dir):
    app.mount(
        "/static",
        StaticFiles(directory=os.path.join(static_dir, "static")),
        name="static",
    )


@app.get(
    "/",
    response_class=HTMLResponse,
    tags=["health"],
    summary="Dashboard",
    description="Serve the vanilla JavaScript research dashboard.",
)
def serve_index():
    index_path = os.path.join(
        os.path.dirname(__file__), "..", "web", "templates", "index.html"
    )
    if os.path.exists(index_path):
        with open(index_path, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse(content="<h1>Financial Research Copilot API is running.</h1>")


# API versioning: v1 sub-app mounted at /api/v1, mirroring the /api routes.
# Clients should prefer /api/v1/ for version-stable integrations.
v1_app = FastAPI(
    title="Multimodal Financial-Filing Research Copilot API v1",
    description="Versioned API surface (v1) for the Financial Filing Research Copilot.",
    version="1.0.0",
    openapi_tags=app.openapi_tags,
)


@v1_app.get("/health", tags=["health"], include_in_schema=False)
def v1_health_check():
    return health_check()


@v1_app.get("/api/metrics", tags=["metrics"], include_in_schema=False)
def v1_get_metrics():
    return get_metrics()


@v1_app.get("/api/companies", tags=["companies"], response_model=list[CompanyInfo])
def v1_get_companies(request: Request):
    return get_companies(request)


@v1_app.get("/api/facts", tags=["facts"], response_model=list[XBRLFact])
def v1_get_xbrl_facts(
    request: Request,
    ticker: str = Query(..., examples=["AAPL"]),
    concept: str | None = Query(None, examples=["Revenues"]),
    year: int | None = Query(None, examples=[2024]),
    period: str | None = Query(None, examples=["Q1"]),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=50, ge=1, le=500),
):
    return get_xbrl_facts(
        request=request,
        ticker=ticker,
        concept=concept,
        year=year,
        period=period,
        page=page,
        size=size,
    )


@v1_app.post("/api/search", tags=["search"], response_model=list[SearchResultItem])
async def v1_search_filings(request: Request, query: SearchQuery):
    return await search_filings(request, query)


@v1_app.post("/api/query", tags=["query"], response_model=ResearchReport)
async def v1_run_research_query(request: Request, req: ResearchRequest):
    return await run_research_query(request, req)


app.mount("/api/v1", v1_app)
