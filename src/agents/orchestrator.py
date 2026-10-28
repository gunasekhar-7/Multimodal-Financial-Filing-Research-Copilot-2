import logging
from typing import Optional
from src.schemas.agents import AgentState, ResearchPlan
from src.schemas.reports import ResearchReport
from src.storage.database import DatabaseStorage
from src.retrieval.hybrid_search import HybridSearchEngine
from src.agents.planner import PlannerAgent
from src.agents.retrieval_agent import RetrievalAgent
from src.agents.extraction import FinancialExtractionAgent
from src.agents.analysis import FinancialAnalysisAgent
from src.agents.verifier import VerificationAgent
from src.agents.writer import ReportWriterAgent

logger = logging.getLogger(__name__)

class ResearchOrchestrator:
    def __init__(self, db: Optional[DatabaseStorage] = None):
        self.db = db or DatabaseStorage()
        self.search_engine = HybridSearchEngine(self.db)

        self.planner = PlannerAgent()
        self.retrieval_agent = RetrievalAgent(self.db, self.search_engine)
        self.extraction_agent = FinancialExtractionAgent()
        self.analysis_agent = FinancialAnalysisAgent()
        self.verifier = VerificationAgent()
        self.writer = ReportWriterAgent()

    def run(self, question: str, default_ticker: str = "AAPL") -> ResearchReport:
        state = AgentState(question=question, tickers=[])
        state.logs.append(f"Received research question: {question}")

        # Step 1: Planning
        plan = self.planner.plan(question, default_ticker=default_ticker)
        state.plan = plan
        state.tickers = plan.tickers
        state.logs.append(f"Generated research plan for tickers: {plan.tickers}")
        logger.info("Plan generated for question %r: tickers=%s", question, plan.tickers)

        # Step 2: Retrieval
        chunks = self.retrieval_agent.retrieve_chunks(
            question, state.tickers, top_k=10, sections=plan.section_hints
        )
        facts = self.retrieval_agent.retrieve_facts(state.tickers)
        state.retrieved_chunks = chunks
        state.retrieved_facts = facts
        state.logs.append(f"Retrieved {len(chunks)} document chunks and {len(facts)} XBRL facts.")
        logger.info("Retrieval complete: chunks=%d facts=%d", len(chunks), len(facts))

        # Step 3: Financial Metric Extraction
        metrics = self.extraction_agent.extract_metrics(facts)
        state.extracted_metrics = metrics
        state.logs.append(f"Extracted {len(metrics)} financial metric comparisons.")
        logger.info("Extraction complete: metrics=%d", len(metrics))

        # Step 4: Risk Analysis
        risk_analysis = self.analysis_agent.analyze_risk_disclosures(chunks)
        state.risk_analysis = risk_analysis
        state.logs.append(f"Analyzed {len(risk_analysis)} risk disclosures.")
        logger.info("Risk analysis complete: disclosures=%d", len(risk_analysis))

        # Step 5: Verification
        claims = self.verifier.verify_claims(question, facts, chunks)
        state.claims = claims
        state.logs.append(f"Verified {len(claims)} numerical & qualitative claims against ground truth.")
        logger.info("Verification complete: claims=%d", len(claims))

        # Step 6: Report Writing
        report = self.writer.generate_report(state)
        state.final_report = report
        state.logs.append("Generated final structured research report.")
        logger.info("Report written for question %r", question)

        return report
