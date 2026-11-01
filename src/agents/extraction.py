from src.schemas.financial import XBRLFact
from src.schemas.reports import FinancialMetricComparison


class FinancialExtractionAgent:
    def __init__(self):
        pass

    def extract_metrics(self, facts: list[XBRLFact]) -> list[FinancialMetricComparison]:
        metrics_by_concept: dict[str, dict[str, float]] = {}
        unit_by_concept: dict[str, str] = {}
        label_by_concept: dict[str, str] = {}

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
            yoy_change: float | None = None
            qoq_change: float | None = None

            # Calculate YoY if 2023-FY and 2024-FY exist or 2023-Q1 vs 2024-Q1
            annual_periods = sorted(
                (key for key in period_values if key.endswith("-FY")),
                key=lambda key: int(key.split("-", 1)[0]),
            )
            if len(annual_periods) >= 2:
                previous, current = (
                    period_values[annual_periods[-2]],
                    period_values[annual_periods[-1]],
                )
                if previous != 0:
                    yoy_change = round(
                        ((current - previous) / abs(previous)) * 100.0, 2
                    )
            else:
                comparable_quarters = sorted(
                    (
                        key
                        for key in period_values
                        if key.split("-", 1)[1] in {"Q1", "Q2", "Q3", "Q4"}
                    ),
                    key=lambda key: (
                        int(key.split("-", 1)[0]),
                        int(key.split("-", 1)[1][1:]),
                    ),
                )
                if comparable_quarters:
                    latest = comparable_quarters[-1]
                    year, quarter = latest.split("-", 1)
                    current = period_values[latest]
                    prev_quarter: float | None = period_values.get(
                        f"{int(year) - 1}-{quarter}"
                    )
                    if prev_quarter is not None and prev_quarter != 0:
                        yoy_change = round(
                            ((current - prev_quarter) / abs(prev_quarter)) * 100.0, 2
                        )

            q_periods = sorted(
                (
                    key
                    for key in period_values
                    if key.split("-", 1)[1] in {"Q1", "Q2", "Q3", "Q4"}
                ),
                key=lambda key: (
                    int(key.split("-", 1)[0]),
                    int(key.split("-", 1)[1][1:]),
                ),
            )
            if len(q_periods) >= 2:
                previous, current = (
                    period_values[q_periods[-2]],
                    period_values[q_periods[-1]],
                )
                if previous != 0:
                    qoq_change = round(
                        ((current - previous) / abs(previous)) * 100.0, 2
                    )

            comparisons.append(
                FinancialMetricComparison(
                    metric_name=label_by_concept.get(concept, concept),
                    concept=concept,
                    unit=unit_by_concept.get(concept, "USD"),
                    periods=period_values,
                    yoy_change_pct=yoy_change,
                    qoq_change_pct=qoq_change,
                    notes=f"Extracted from {len(period_values)} indexed XBRL reporting periods; source provenance is carried by the report.",
                )
            )

        return comparisons
