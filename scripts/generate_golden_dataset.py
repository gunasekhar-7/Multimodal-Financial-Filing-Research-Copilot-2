import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.ingestion.companies import TARGET_COMPANIES
from src.ingestion.sec_client import generate_mock_xbrl_facts


def generate_golden_dataset():
    dataset = []
    qid = 1
    for company in TARGET_COMPANIES:
        facts = generate_mock_xbrl_facts(company)
        questions = [
            (
                "numerical_extraction",
                f"What was {company.name} ({company.ticker}) total revenue in fiscal year 2024?",
                "Revenues",
                2024,
                "FY",
                "Item 8. Financial Statements and Supplementary Data",
            ),
            (
                "numerical_extraction",
                f"What was {company.name}'s net income in FY 2023?",
                "NetIncomeLoss",
                2023,
                "FY",
                "Item 8. Financial Statements and Supplementary Data",
            ),
            (
                "risk_classification",
                f"What key operational and market risks were disclosed in {company.ticker}'s Item 1A?",
                None,
                2024,
                "FY",
                "Item 1A. Risk Factors",
            ),
            (
                "yoy_comparison",
                f"Compare year-over-year revenue growth for {company.ticker} between 2023 and 2024.",
                "Revenues",
                2024,
                "FY",
                "Item 7. Management's Discussion and Analysis of Financial Condition and Results of Operations",
            ),
            (
                "mda_analysis",
                f"What strategic investments in artificial intelligence and software architecture were outlined by {company.name}?",
                None,
                2024,
                "FY",
                "Item 7. Management's Discussion and Analysis of Financial Condition and Results of Operations",
            ),
            (
                "quarterly_performance",
                f"What was {company.ticker}'s Q1 2024 reported revenue?",
                "Revenues",
                2024,
                "Q1",
                "Item 8. Financial Statements and Supplementary Data",
            ),
        ]
        for category, question, concept, year, period, section in questions:
            expected = (
                next(
                    (
                        fact.value
                        for fact in facts
                        if fact.concept == concept
                        and fact.fiscal_year == year
                        and fact.fiscal_period == period
                    ),
                    None,
                )
                if concept
                else None
            )
            dataset.append(
                {
                    "id": f"eval-{qid:03d}",
                    "ticker": company.ticker,
                    "company_name": company.name,
                    "category": category,
                    "question": question,
                    "expected_ticker": company.ticker,
                    "expected_concept": concept,
                    "expected_year": year,
                    "expected_period": period,
                    "expected_numerical_value": expected,
                    "tolerance_pct": 0.01,
                    "expected_item_section": section,
                    "expected_data_source": "demo",
                }
            )
            qid += 1

    output_path = os.path.join(
        os.path.dirname(__file__), "..", "src", "eval", "golden_dataset.json"
    )
    with open(output_path, "w", encoding="utf-8") as output:
        json.dump(dataset, output, indent=2)
    print(
        f"Generated {len(dataset)} deterministic demo evaluation items at {output_path}"
    )


if __name__ == "__main__":
    generate_golden_dataset()
