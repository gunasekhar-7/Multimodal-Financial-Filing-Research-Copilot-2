from typing import List
from src.schemas.financial import SearchResultItem
from src.schemas.reports import RiskFactorAnalysis, Citation

class FinancialAnalysisAgent:
    def __init__(self):
        pass

    def analyze_risk_disclosures(self, chunks: List[SearchResultItem]) -> List[RiskFactorAnalysis]:
        risk_analyses = []
        for item in chunks:
            if "Risk Factors" in item.chunk.item_section or "risk" in item.chunk.content.lower():
                citation = Citation(
                    citation_id=f"cite-{item.chunk.chunk_id}",
                    ticker=item.chunk.ticker,
                    filing_type=item.chunk.filing_type.value,
                    fiscal_year=item.chunk.fiscal_year,
                    fiscal_period=item.chunk.fiscal_period,
                    page_number=item.chunk.page_number,
                    item_section=item.chunk.item_section,
                    source_url=item.chunk.source_url,
                    excerpt=item.chunk.content[:180] + "..."
                )

                risk_analyses.append(RiskFactorAnalysis(
                    category="Market & Regulatory Risk",
                    risk_title="Evolution & Competition in Technology Infrastructure",
                    description=item.chunk.content,
                    trend="escalating" if "ai" in item.chunk.content.lower() else "stable",
                    citations=[citation]
                ))

        if not risk_analyses:
            risk_analyses.append(RiskFactorAnalysis(
                category="General Operations",
                risk_title="General Industry & Supply Chain Risks",
                description="Macroeconomic volatility, foreign currency fluctuations, and global trade policies.",
                trend="stable",
                citations=[]
            ))

        return risk_analyses
