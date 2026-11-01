from src.schemas.financial import SearchResultItem
from src.schemas.reports import Citation, RiskFactorAnalysis


class FinancialAnalysisAgent:
    def __init__(self):
        pass

    def analyze_risk_disclosures(
        self, chunks: list[SearchResultItem]
    ) -> list[RiskFactorAnalysis]:
        risk_analyses = []
        for item in chunks:
            if (
                "Risk Factors" in item.chunk.item_section
                or "risk" in item.chunk.content.lower()
            ):
                citation = Citation(
                    citation_id=f"cite-{item.chunk.chunk_id}",
                    ticker=item.chunk.ticker,
                    filing_type=item.chunk.filing_type.value,
                    fiscal_year=item.chunk.fiscal_year,
                    fiscal_period=item.chunk.fiscal_period,
                    page_number=item.chunk.page_number,
                    item_section=item.chunk.item_section,
                    source_url=item.chunk.source_url,
                    excerpt=item.chunk.content[:180],
                    data_source=item.chunk.data_source,
                )

                risk_analyses.append(
                    RiskFactorAnalysis(
                        category="Market & Regulatory Risk",
                        risk_title="Source-disclosed risk factors",
                        description=item.chunk.content,
                        trend="not_assessed",
                        citations=[citation],
                    )
                )

        return risk_analyses
