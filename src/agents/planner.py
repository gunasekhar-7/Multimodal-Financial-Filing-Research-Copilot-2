import re
from typing import List, Optional
from src.schemas.agents import ResearchPlan
from src.schemas.financial import CompanyInfo
from src.ingestion.companies import TARGET_COMPANIES

# A question asking for a precise quantitative figure should retrieve the
# filing sections that carry those figures as primary data (the consolidated
# statements, Item 8), not just narrative mentions of the metric.
NUMERIC_METRIC_SIGNALS = re.compile(
    r"\b(revenue|income|eps|profit|margin|earnings|cash|growth|yoy)\b",
    re.IGNORECASE,
)

# Question-side qualitative signals: when these dominate the question, the
# statements filter must NOT fire, or risk/risk/M&A content would be hidden
# from genuinely mixed questions.
QUALITATIVE_SIGNALS = re.compile(
    r"\b(risk|risks|mda|outlook|guidance|strategy|strategic|disclosure|disclosures|"
    r"commentary|describe|discuss|discloses|says|about)\b",
    re.IGNORECASE,
)


def classify_question(question: str) -> str:
    """Coarse intent classification used by the planner.

    Returns 'numerical' when the question asks for a quantitative figure and
    carries no qualitative framing, 'mixed'/'qualitative' otherwise.
    """
    if NUMERIC_METRIC_SIGNALS.search(question or "") and not QUALITATIVE_SIGNALS.search(question or ""):
        return "numerical"
    return "qualitative"


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
            "Generate structured research report with citations",
        ]

        # The retrieval layer prioritizes the filing sections that carry the
        # figures as primary data only for purely numerical questions.
        section_hints: List[str] = []
        if classify_question(question) == "numerical":
            section_hints = ["Item 8."]

        return ResearchPlan(
            question=question,
            tickers=tickers,
            required_periods=["2023-Q1", "2023-Q2", "2023-Q3", "2023-FY", "2024-Q1", "2024-Q2", "2024-Q3", "2024-FY"],
            sub_tasks=sub_tasks,
            search_queries=search_queries,
            section_hints=section_hints,
        )
