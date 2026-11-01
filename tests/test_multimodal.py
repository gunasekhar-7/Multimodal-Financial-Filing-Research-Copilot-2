from src.agents.visualizer import MultimodalVisualizerAgent
from src.schemas.reports import (
    FinancialMetricComparison,
    ResearchReport,
    VisualArtifactType,
)


class TestMultimodalVisualizer:
    def test_visualizer_generates_chart_and_table(self):
        agent = MultimodalVisualizerAgent()
        metrics = [
            FinancialMetricComparison(
                metric_name="Revenues",
                concept="Revenues",
                unit="USD",
                periods={
                    "2023-Q1": 90000000000.0,
                    "2023-Q2": 92000000000.0,
                    "2023-Q3": 94000000000.0,
                    "2023-FY": 380000000000.0,
                    "2024-Q1": 98000000000.0,
                    "2024-FY": 400000000000.0,
                },
                yoy_change_pct=5.26,
            ),
            FinancialMetricComparison(
                metric_name="Net Income",
                concept="NetIncomeLoss",
                unit="USD",
                periods={
                    "2023-Q1": 22000000000.0,
                    "2023-FY": 96000000000.0,
                    "2024-Q1": 24000000000.0,
                    "2024-FY": 102000000000.0,
                },
                yoy_change_pct=6.25,
            ),
        ]

        artifacts = agent.generate_artifacts(["AAPL"], metrics)
        assert len(artifacts) >= 2

        # Check Performance Chart
        chart = next(
            a for a in artifacts if a.artifact_type == VisualArtifactType.BAR_CHART
        )
        assert chart.artifact_id.startswith("chart-perf-")
        assert "AAPL" in chart.title
        assert chart.svg_content is not None
        assert "<svg" in chart.svg_content
        assert "</svg>" in chart.svg_content
        assert "Revenue" in chart.svg_content
        assert "Net Income" in chart.svg_content

        # Check Statement Table
        table = next(
            a
            for a in artifacts
            if a.artifact_type == VisualArtifactType.FINANCIAL_TABLE
        )
        assert table.artifact_id.startswith("table-ops-")
        assert table.data_table is not None
        assert table.data_table["entity"] == "AAPL"
        assert len(table.data_table["rows"]) == 2
        assert table.svg_content is not None
        assert "<svg" in table.svg_content

    def test_visualizer_handles_empty_metrics(self):
        agent = MultimodalVisualizerAgent()
        artifacts = agent.generate_artifacts(["AAPL"], [])
        assert artifacts == []

    def test_visualizer_handles_non_standard_periods(self):
        agent = MultimodalVisualizerAgent()
        metrics = [
            FinancialMetricComparison(
                metric_name="Revenues",
                concept="Revenues",
                unit="USD",
                periods={
                    "2023": 100000000.0,
                    "2023-H1": 50000000.0,
                    "FY2024": 120000000.0,
                },
                yoy_change_pct=20.0,
            )
        ]
        artifacts = agent.generate_artifacts(["TEST"], metrics)
        assert len(artifacts) >= 1
        assert artifacts[0].svg_content is not None

    def test_report_includes_visual_artifacts(self):
        from src.agents.orchestrator import ResearchOrchestrator

        orchestrator = ResearchOrchestrator()
        report = orchestrator.run("What was Apple's total revenue in 2024?")
        assert isinstance(report, ResearchReport)
        assert len(report.visual_artifacts) >= 1
        assert any(
            a.artifact_type == VisualArtifactType.BAR_CHART
            for a in report.visual_artifacts
        )
