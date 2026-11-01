from datetime import datetime, timezone

from src.schemas.agents import AgentState
from src.schemas.reports import Citation, ResearchReport


class ReportWriterAgent:
    def __init__(self):
        pass

    def generate_report(self, state: AgentState) -> ResearchReport:
        tickers_str = ", ".join(state.tickers)

        # Collect citations
        all_citations: list[Citation] = []
        citation_ids = set()

        for claim in state.claims:
            for c in claim.citations:
                if c.citation_id not in citation_ids:
                    all_citations.append(c)
                    citation_ids.add(c.citation_id)

        for risk in state.risk_analysis:
            for c in risk.citations:
                if c.citation_id not in citation_ids:
                    all_citations.append(c)
                    citation_ids.add(c.citation_id)

        summary_claims = " ".join([c.claim_text for c in state.claims])
        verified_count = sum(
            1 for claim in state.claims if claim.status.value == "verified"
        )
        provenance_summary = (
            "Deterministic demo corpus; figures are synthetic and not SEC-reported."
            if state.data_mode == "demo"
            else "SEC EDGAR XBRL facts; filing-text retrieval is not available in SEC mode."
        )
        verification_summary = (
            f"{verified_count} claim(s) verified against indexed structured facts."
            if verified_count
            else "No requested figures could be verified in the indexed corpus."
        )
        exec_summary = (
            f"Financial Research Report on {tickers_str}.\n"
            f"Question: '{state.question}'\n\n"
            f"Key Findings:\n"
            f"{summary_claims}\n\n"
            f"{verification_summary} {provenance_summary}"
        )

        uncertainties = [
            "This tool is for educational research only and does not provide investment advice.",
        ]
        if state.data_mode == "demo":
            uncertainties.append(
                "Demo mode uses synthetic generated data; it is not a substitute for SEC filings."
            )
        else:
            uncertainties.append(
                "SEC mode currently fetches structured XBRL facts only; filing-text ingestion and semantic claim verification are not implemented."
            )

        generated_at = datetime.now(timezone.utc)
        return ResearchReport(
            report_id=f"report-{generated_at.strftime('%Y%m%d%H%M%S%f')}",
            question=state.question,
            target_tickers=state.tickers,
            executive_summary=exec_summary,
            metric_comparisons=state.extracted_metrics,
            risk_analysis=state.risk_analysis,
            claims=state.claims,
            citations=all_citations,
            visual_artifacts=state.visual_artifacts,
            uncertainty_disclosures=uncertainties,
            generated_at=generated_at.isoformat(),
            data_mode=state.data_mode,
            data_sources=sorted(
                {fact.data_source for fact in state.retrieved_facts}
                | {chunk.chunk.data_source for chunk in state.retrieved_chunks},
                key=lambda source: source.value,
            ),
        )
