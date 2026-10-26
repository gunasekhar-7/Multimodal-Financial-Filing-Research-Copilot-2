from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field, ConfigDict
from src.schemas.financial import SearchResultItem, XBRLFact
from src.schemas.reports import ResearchReport, VerifiedClaim, FinancialMetricComparison, RiskFactorAnalysis

class ResearchPlan(BaseModel):
    question: str
    tickers: List[str]
    required_periods: List[str]
    sub_tasks: List[str]
    search_queries: List[str]

class AgentState(BaseModel):
    model_config = ConfigDict(extra='ignore')
    question: str
    tickers: List[str]
    plan: Optional[ResearchPlan] = None
    retrieved_chunks: List[SearchResultItem] = []
    retrieved_facts: List[XBRLFact] = []
    extracted_metrics: List[FinancialMetricComparison] = []
    risk_analysis: List[RiskFactorAnalysis] = []
    claims: List[VerifiedClaim] = []
    final_report: Optional[ResearchReport] = None
    logs: List[str] = []
