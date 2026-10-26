import json
import os
from src.ingestion.companies import TARGET_COMPANIES
from src.ingestion.sec_client import BASE_FINANCIALS

def generate_golden_dataset():
    dataset = []

    qid = 1
    for comp in TARGET_COMPANIES:
        base_info = BASE_FINANCIALS.get(comp.ticker, {"base_rev": 10000.0, "base_ni": 2000.0, "growth": 0.03})
        base_rev = base_info["base_rev"]
        base_ni = base_info["base_ni"]
        growth = base_info["growth"]

        # 2023-FY Facts
        rev_23 = round(base_rev * ((1 + growth) ** 3), 2) * 1000000.0
        rev_24 = round(base_rev * ((1 + growth) ** 7), 2) * 1000000.0

        # Q1: Revenue question
        dataset.append({
            "id": f"eval-{qid:03d}",
            "ticker": comp.ticker,
            "company_name": comp.name,
            "category": "numerical_extraction",
            "question": f"What was {comp.name} ({comp.ticker}) total revenue in fiscal year 2024?",
            "expected_ticker": comp.ticker,
            "expected_concept": "Revenues",
            "expected_year": 2024,
            "expected_period": "FY",
            "expected_numerical_value": rev_24,
            "tolerance_pct": 0.01,
            "expected_item_section": "Item 8. Financial Statements and Supplementary Data"
        })
        qid += 1

        # Q2: Net income question
        dataset.append({
            "id": f"eval-{qid:03d}",
            "ticker": comp.ticker,
            "company_name": comp.name,
            "category": "numerical_extraction",
            "question": f"What was {comp.name}'s net income in FY 2023?",
            "expected_ticker": comp.ticker,
            "expected_concept": "NetIncomeLoss",
            "expected_year": 2023,
            "expected_period": "FY",
            "expected_numerical_value": round(base_ni * ((1 + growth) ** 3), 2) * 1000000.0,
            "tolerance_pct": 0.01,
            "expected_item_section": "Item 8. Financial Statements and Supplementary Data"
        })
        qid += 1

        # Q3: Risk disclosure question
        dataset.append({
            "id": f"eval-{qid:03d}",
            "ticker": comp.ticker,
            "company_name": comp.name,
            "category": "risk_classification",
            "question": f"What key operational and market risks were disclosed in {comp.ticker}'s Item 1A?",
            "expected_ticker": comp.ticker,
            "expected_concept": None,
            "expected_year": 2024,
            "expected_period": "FY",
            "expected_numerical_value": None,
            "tolerance_pct": 0.0,
            "expected_item_section": "Item 1A. Risk Factors"
        })
        qid += 1

        # Q4: YoY comparison question
        dataset.append({
            "id": f"eval-{qid:03d}",
            "ticker": comp.ticker,
            "company_name": comp.name,
            "category": "yoy_comparison",
            "question": f"Compare year-over-year revenue growth for {comp.ticker} between 2023 and 2024.",
            "expected_ticker": comp.ticker,
            "expected_concept": "Revenues",
            "expected_year": 2024,
            "expected_period": "FY",
            "expected_numerical_value": rev_24,
            "tolerance_pct": 0.01,
            "expected_item_section": "Item 7. Management's Discussion and Analysis of Financial Condition and Results of Operations"
        })
        qid += 1

        # Q5: MD&A strategic overview
        dataset.append({
            "id": f"eval-{qid:03d}",
            "ticker": comp.ticker,
            "company_name": comp.name,
            "category": "mda_analysis",
            "question": f"What strategic investments in artificial intelligence and software architecture were outlined by {comp.name}?",
            "expected_ticker": comp.ticker,
            "expected_concept": None,
            "expected_year": 2024,
            "expected_period": "FY",
            "expected_numerical_value": None,
            "tolerance_pct": 0.0,
            "expected_item_section": "Item 7. Management's Discussion and Analysis of Financial Condition and Results of Operations"
        })
        qid += 1

        # Q6: Q1 2024 quarterly revenue
        dataset.append({
            "id": f"eval-{qid:03d}",
            "ticker": comp.ticker,
            "company_name": comp.name,
            "category": "quarterly_performance",
            "question": f"What was {comp.ticker}'s Q1 2024 reported revenue?",
            "expected_ticker": comp.ticker,
            "expected_concept": "Revenues",
            "expected_year": 2024,
            "expected_period": "Q1",
            "expected_numerical_value": round(base_rev * ((1 + growth) ** 4), 2) * 1000000.0,
            "tolerance_pct": 0.01,
            "expected_item_section": "Item 8. Financial Statements and Supplementary Data"
        })
        qid += 1

    eval_dir = os.path.join(os.path.dirname(__file__), "..", "src", "eval")
    os.makedirs(eval_dir, exist_ok=True)
    file_path = os.path.join(eval_dir, "golden_dataset.json")

    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(dataset, f, indent=2)

    print(f"Generated golden evaluation dataset with {len(dataset)} items at {file_path}")

if __name__ == "__main__":
    generate_golden_dataset()
