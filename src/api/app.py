import os
import logging
from typing import List, Optional, Dict, Any
from fastapi import FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from src.storage.database import DatabaseStorage
from src.retrieval.hybrid_search import HybridSearchEngine
from src.agents.orchestrator import ResearchOrchestrator
from src.schemas.financial import SearchQuery, SearchResultItem, CompanyInfo, XBRLFact
from src.schemas.reports import ResearchReport

logger = logging.getLogger(__name__)

app = FastAPI(
    title="Multimodal Financial-Filing Research Copilot API",
    description="Production-style AI research copilot for SEC filings, XBRL structured data, and claim verification.",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global DB and Orchestrator instances
db = DatabaseStorage(db_path="financial_copilot.db")
orchestrator = ResearchOrchestrator(db=db)

class ResearchRequest(BaseModel):
    question: str
    ticker: Optional[str] = "AAPL"

@app.get("/health")
def health_check():
    return {
        "status": "healthy",
        "database": "connected",
        "companies_count": len(db.get_all_companies()),
        "xbrl_facts_count": db.get_fact_count(),
        "document_chunks_count": db.get_chunk_count()
    }

@app.get("/api/companies", response_model=List[CompanyInfo])
def get_companies():
    return db.get_all_companies()

@app.get("/api/facts", response_model=List[XBRLFact])
def get_xbrl_facts(
    ticker: str,
    concept: Optional[str] = None,
    year: Optional[int] = None,
    period: Optional[str] = None
):
    facts = db.query_xbrl_facts(ticker=ticker, concept=concept, year=year, period=period)
    if not facts:
        return []
    return facts

@app.post("/api/search", response_model=List[SearchResultItem])
def search_filings(query: SearchQuery):
    return orchestrator.search_engine.search(query)

@app.post("/api/query", response_model=ResearchReport)
def run_research_query(req: ResearchRequest):
    if not req.question or len(req.question.strip()) < 3:
        raise HTTPException(status_code=400, detail="Research question must be at least 3 characters.")

    try:
        report = orchestrator.run(question=req.question, default_ticker=req.ticker or "AAPL")
        return report
    except Exception as e:
        logger.error(f"Error processing research query: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# Static web app serving
static_dir = os.path.join(os.path.dirname(__file__), "..", "web")
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=os.path.join(static_dir, "static")), name="static")

@app.get("/", response_class=HTMLResponse)
def serve_index():
    index_path = os.path.join(os.path.dirname(__file__), "..", "web", "templates", "index.html")
    if os.path.exists(index_path):
        with open(index_path, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse(content="<h1>Financial Research Copilot API is running.</h1>")
