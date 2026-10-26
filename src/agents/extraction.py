from typing import List, Dict, Any
from src.schemas.financial import XBRLFact
from src.schemas.reports import FinancialMetricComparison

class FinancialExtractionAgent:
    def __init__(self):
        pass

    def extract_metrics(self, facts: List[XBRLFact]) -> List[FinancialMetricComparison]:
        metrics_by_concept: Dict[str, Dict[str, float]] = {}
        unit_by_concept: Dict[str, str] = {}
        label_by_concept: Dict[str, str] = {}

        for fact in facts:
            concept = fact.concept
            period_key = f"{fact.fiscal_year}-{fact.fiscal_period}"
            if concept not in metrics_by_concept:
                metrics_by_concept[concept] = {}
                unit_by_concept[concept] = fact.unit
                label_by_concept[concept] = fact.label

            metrics_by_concept[concept][period_key] = fact.value

        comparisons = []
        for concept, period_values in metrics_by_concept.items():
            sorted_periods = sorted(period_values.keys())

            yoy_change = None
            qoq_change = None

            # Calculate YoY if 2023-FY and 2024-FY exist or 2023-Q1 vs 2024-Q1
            if "2023-FY" in period_values and "2024-FY" in period_values:
                val_23 = period_values["2023-FY"]
                val_24 = period_values["2024-FY"]
                if val_23 != 0:
                    yoy_change = round(((val_24 - val_23) / abs(val_23)) * 100.0, 2)

            if "2024-Q2" in period_values and "2024-Q3" in period_values:
                val_q2 = period_values["2024-Q2"]
                val_q3 = period_values["2024-Q3"]
                if val_q2 != 0:
                    qoq_change = round(((val_q3 - val_q2) / abs(val_q2)) * 100.0, 2)

            comparisons.append(FinancialMetricComparison(
                metric_name=label_by_concept.get(concept, concept),
                concept=concept,
                unit=unit_by_concept.get(concept, "USD"),
                periods=period_values,
                yoy_change_pct=yoy_change,
                qoq_change_pct=qoq_change,
                notes=f"Extracted from {len(period_values)} SEC XBRL reporting periods."
            ))

        return comparisons
