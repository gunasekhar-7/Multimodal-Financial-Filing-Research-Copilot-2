from pydantic import BaseModel, ConfigDict, Field

from src.schemas.financial import SearchResultItem, XBRLFact
from src.schemas.reports import (
    FinancialMetricComparison,
    ResearchReport,
    RiskFactorAnalysis,
    VerifiedClaim,
    VisualArtifact,
)


class ResearchPlan(BaseModel):
    question: str
    tickers: list[str]
    required_periods: list[str]
    sub_tasks: list[str]
    search_queries: list[str]
    # Filing-section prefixes (e.g. "Item 8.") the retrieval layer should
    # prioritize for this question. Empty for qualitative questions.
    section_hints: list[str] = []


class AgentState(BaseModel):
    model_config = ConfigDict(extra="ignore")
    question: str
    tickers: list[str]
    data_mode: str = "demo"
    plan: ResearchPlan | None = None
    retrieved_chunks: list[SearchResultItem] = []
    retrieved_facts: list[XBRLFact] = []
    extracted_metrics: list[FinancialMetricComparison] = []
    risk_analysis: list[RiskFactorAnalysis] = []
    claims: list[VerifiedClaim] = []
    visual_artifacts: list[VisualArtifact] = Field(default_factory=list)
    final_report: ResearchReport | None = None
    logs: list[str] = []
