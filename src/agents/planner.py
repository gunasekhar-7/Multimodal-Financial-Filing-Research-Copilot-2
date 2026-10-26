import re
from typing import List
from src.schemas.agents import ResearchPlan
from src.schemas.financial import CompanyInfo
from src.ingestion.companies import TARGET_COMPANIES

class PlannerAgent:
    def __init__(self):
        pass

    def plan(self, question: str, default_ticker: str = "AAPL") -> ResearchPlan:
        # Detect ticker in question or default
        tickers = []
        for comp in TARGET_COMPANIES:
            if re.search(r'\b' + comp.ticker + r'\b', question, re.IGNORECASE) or comp.name.lower() in question.lower():
                tickers.append(comp.ticker)

        if not tickers:
            tickers = [default_ticker]

        search_queries = [
            f"{q_term} {' '.join(tickers)}" for q_term in ["revenue growth financial performance", "risk factors MD&A", "net income profitability"]
        ]

        sub_tasks = [
            f"Retrieve financial filings for {', '.join(tickers)}",
            "Extract quarterly revenues, net income, and EPS metrics",
            "Perform YoY and QoQ trend analysis",
            "Verify claims against XBRL facts",
            "Generate structured research report with citations"
        ]

        return ResearchPlan(
            question=question,
            tickers=tickers,
            required_periods=["2023-Q1", "2023-Q2", "2023-Q3", "2023-FY", "2024-Q1", "2024-Q2", "2024-Q3", "2024-FY"],
            sub_tasks=sub_tasks,
            search_queries=search_queries
        )
