import html
from typing import Any

from src.schemas.financial import SearchResultItem
from src.schemas.reports import (
    FinancialMetricComparison,
    VisualArtifact,
    VisualArtifactType,
)


def _parse_period_sort_key(period_str: str) -> tuple[int, int]:
    """Parse period string (e.g. '2023-FY', '2023-Q1') safely into (year, quarter_order)."""
    parts = period_str.split("-")
    try:
        year = int(parts[0])
    except (ValueError, IndexError):
        year = 0
    if len(parts) > 1:
        sub = parts[1].strip().upper()
        if sub == "FY":
            order = 5
        elif sub.startswith("Q") and sub[1:].isdigit():
            order = int(sub[1:])
        else:
            order = 0
    else:
        order = 0
    return (year, order)


class MultimodalVisualizerAgent:
    """Agent responsible for synthesizing multimodal visual artifacts.

    Generates publication-quality, standalone SVG financial charts and
    structured financial statement tables representing filing data for
    visual inspection and dashboards.
    """

    def __init__(self):
        pass

    def generate_artifacts(
        self,
        tickers: list[str],
        metrics: list[FinancialMetricComparison],
        chunks: list[SearchResultItem] | None = None,
    ) -> list[VisualArtifact]:
        artifacts: list[VisualArtifact] = []
        ticker_str = ", ".join(tickers) if tickers else "Entity"

        # 1. Generate Multi-Period Financial Performance Chart (SVG)
        rev_metric = next((m for m in metrics if m.concept == "Revenues"), None)
        ni_metric = next((m for m in metrics if m.concept == "NetIncomeLoss"), None)

        if rev_metric and rev_metric.periods:
            chart_svg = self._render_performance_chart_svg(
                ticker_str, rev_metric, ni_metric
            )
            artifacts.append(
                VisualArtifact(
                    artifact_id=f"chart-perf-{tickers[0] if tickers else 'default'}",
                    title=f"{ticker_str} Financial Performance & Profitability Trend",
                    artifact_type=VisualArtifactType.BAR_CHART,
                    caption=(
                        f"Multi-period comparison of total revenues and net income "
                        f"for {ticker_str} based on reported SEC XBRL filings."
                    ),
                    svg_content=chart_svg,
                    mime_type="image/svg+xml",
                )
            )

        # 2. Generate Structured Financial Statement Table
        table_artifact = self._build_statement_table(ticker_str, metrics, chunks)
        if table_artifact:
            artifacts.append(table_artifact)

        return artifacts

    def _render_performance_chart_svg(
        self,
        ticker: str,
        rev_metric: FinancialMetricComparison,
        ni_metric: FinancialMetricComparison | None,
    ) -> str:
        """Render a standalone, responsive SVG bar/line comparison chart."""
        # Sort periods chronologically
        periods = sorted(
            rev_metric.periods.keys(),
            key=_parse_period_sort_key,
        )

        width = 720
        height = 360
        margin_left = 70
        margin_right = 30
        margin_top = 60
        margin_bottom = 50

        chart_w = width - margin_left - margin_right
        chart_h = height - margin_top - margin_bottom

        rev_vals = [rev_metric.periods.get(p, 0.0) for p in periods]
        ni_vals = (
            [ni_metric.periods.get(p, 0.0) for p in periods]
            if ni_metric
            else [0.0] * len(periods)
        )

        max_val = max(max(rev_vals, default=1.0), 1.0)
        # Determine scale divisor ($B vs $M)
        if max_val >= 1_000_000_000.0:
            divisor = 1_000_000_000.0
            unit_suffix = "$B"
        else:
            divisor = 1_000_000.0
            unit_suffix = "$M"

        scaled_max = (max_val / divisor) * 1.15
        if scaled_max <= 0:
            scaled_max = 10.0

        n = len(periods)
        group_w = chart_w / max(1, n)
        bar_w = min(28.0, group_w * 0.35)

        svg_parts = [
            (
                f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
                f'width="100%" height="100%" style="font-family: -apple-system, BlinkMacSystemFont, '
                f"'Segoe UI', Roboto, sans-serif; background: #0f172a; border-radius: 8px;\">"
            ),
            # Defs & Gradients
            "<defs>",
            '  <linearGradient id="revGrad" x1="0" y1="0" x2="0" y2="1">',
            '    <stop offset="0%" stop-color="#38bdf8" />',
            '    <stop offset="100%" stop-color="#0284c7" />',
            "  </linearGradient>",
            '  <linearGradient id="niGrad" x1="0" y1="0" x2="0" y2="1">',
            '    <stop offset="0%" stop-color="#34d399" />',
            '    <stop offset="100%" stop-color="#059669" />',
            "  </linearGradient>",
            "</defs>",
            # Header Title
            (
                f'<text x="{margin_left}" y="32" fill="#f8fafc" font-size="16" font-weight="600">'
                f"{html.escape(ticker)} - Revenue &amp; Net Income Trajectory</text>"
            ),
            (
                f'<text x="{width - margin_right}" y="32" fill="#94a3b8" font-size="12" text-anchor="end">'
                f"Values in {unit_suffix}</text>"
            ),
            # Legend
            f'<rect x="{margin_left}" y="42" width="12" height="12" rx="2" fill="url(#revGrad)" />',
            f'<text x="{margin_left + 18}" y="52" fill="#cbd5e1" font-size="11">Revenue</text>',
            f'<rect x="{margin_left + 90}" y="42" width="12" height="12" rx="2" fill="url(#niGrad)" />',
            f'<text x="{margin_left + 108}" y="52" fill="#cbd5e1" font-size="11">Net Income</text>',
        ]

        # Horizontal Gridlines & Y-Axis labels
        ticks = 5
        for i in range(ticks + 1):
            tick_val = (scaled_max / ticks) * i
            y_pos = margin_top + chart_h - (chart_h / ticks) * i
            svg_parts.append(
                f'<line x1="{margin_left}" y1="{y_pos}" x2="{width - margin_right}" y2="{y_pos}" '
                f'stroke="#334155" stroke-dasharray="3,3" stroke-width="1" />'
            )
            svg_parts.append(
                f'<text x="{margin_left - 10}" y="{y_pos + 4}" fill="#94a3b8" font-size="11" text-anchor="end">'
                f"{tick_val:,.1f}</text>"
            )

        # Baseline Axis
        base_y = margin_top + chart_h
        svg_parts.append(
            f'<line x1="{margin_left}" y1="{base_y}" x2="{width - margin_right}" y2="{base_y}" '
            f'stroke="#64748b" stroke-width="1.5" />'
        )

        # Draw Bars and Labels
        for idx, p in enumerate(periods):
            cx = margin_left + idx * group_w + group_w / 2.0
            r_val = rev_vals[idx] / divisor
            n_val = max(0.0, ni_vals[idx] / divisor)

            r_bar_h = (r_val / scaled_max) * chart_h
            n_bar_h = (n_val / scaled_max) * chart_h

            r_x = cx - bar_w - 2
            n_x = cx + 2

            r_y = base_y - r_bar_h
            n_y = base_y - n_bar_h

            # Revenue bar
            svg_parts.append(
                f'<rect x="{r_x:.1f}" y="{r_y:.1f}" width="{bar_w:.1f}" height="{r_bar_h:.1f}" '
                f'rx="3" fill="url(#revGrad)">'
                f"<title>{html.escape(p)} Revenue: ${r_val:.2f}{unit_suffix}</title></rect>"
            )

            # Net income bar
            svg_parts.append(
                f'<rect x="{n_x:.1f}" y="{n_y:.1f}" width="{bar_w:.1f}" height="{n_bar_h:.1f}" '
                f'rx="3" fill="url(#niGrad)">'
                f"<title>{html.escape(p)} Net Income: ${n_val:.2f}{unit_suffix}</title></rect>"
            )

            # Period label
            svg_parts.append(
                f'<text x="{cx:.1f}" y="{base_y + 20}" fill="#cbd5e1" font-size="11" text-anchor="middle">'
                f"{html.escape(p)}</text>"
            )

        svg_parts.append("</svg>")
        return "\n".join(svg_parts)

    def _build_statement_table(
        self,
        ticker: str,
        metrics: list[FinancialMetricComparison],
        chunks: list[SearchResultItem] | None = None,
    ) -> VisualArtifact | None:
        """Construct a structured consolidated operations table artifact."""
        if not metrics:
            return None

        # Collect all periods represented across metrics
        all_periods: set[str] = set()
        for m in metrics:
            all_periods.update(m.periods.keys())

        if not all_periods:
            return None

        sorted_periods = sorted(
            all_periods,
            key=_parse_period_sort_key,
            reverse=True,
        )[:6]  # Most recent 6 periods

        rows: list[dict[str, Any]] = []
        for m in metrics:
            row_data: dict[str, Any] = {
                "metric": m.metric_name,
                "concept": m.concept,
                "unit": m.unit,
                "yoy_change_pct": m.yoy_change_pct,
                "values": {},
            }
            for p in sorted_periods:
                val = m.periods.get(p)
                if val is not None:
                    if m.unit == "USD":
                        row_data["values"][p] = f"${val / 1_000_000.0:,.1f}M"
                    else:
                        row_data["values"][p] = f"{val:,.2f}"
                else:
                    row_data["values"][p] = "-"
            rows.append(row_data)

        data_table = {
            "entity": ticker,
            "periods": sorted_periods,
            "rows": rows,
        }

        # Also render a clean visual SVG representation of the table
        svg_table = self._render_table_svg(ticker, sorted_periods, rows)

        return VisualArtifact(
            artifact_id=f"table-ops-{ticker.replace(', ', '-')}",
            title=f"{ticker} Consolidated Statement of Operations",
            artifact_type=VisualArtifactType.FINANCIAL_TABLE,
            caption=f"Standardized multi-period operations metrics and YoY changes for {ticker}.",
            svg_content=svg_table,
            data_table=data_table,
            mime_type="image/svg+xml",
        )

    def _render_table_svg(
        self,
        ticker: str,
        periods: list[str],
        rows: list[dict[str, Any]],
    ) -> str:
        """Render a styled SVG card containing the operations table."""
        width = 720
        row_h = 32
        header_h = 70
        height = header_h + len(rows) * row_h + 30

        svg_parts = [
            (
                f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
                f'width="100%" height="100%" style="font-family: -apple-system, BlinkMacSystemFont, '
                f"'Segoe UI', Roboto, sans-serif; background: #0f172a; border-radius: 8px;\">"
            ),
            (
                f'<text x="24" y="32" fill="#f8fafc" font-size="15" font-weight="600">'
                f"{html.escape(ticker)} - Consolidated Financial Summary Table</text>"
            ),
            '<text x="24" y="50" fill="#94a3b8" font-size="11">Extracted from SEC XBRL disclosures &amp; Statements</text>',
        ]

        # Table Header
        y = header_h
        svg_parts.append(
            f'<rect x="20" y="{y - 18}" width="{width - 40}" height="28" fill="#1e293b" rx="4" />'
        )
        svg_parts.append(
            f'<text x="32" y="{y}" fill="#94a3b8" font-size="11" font-weight="600">Metric</text>'
        )

        col_w = (width - 240) / max(1, len(periods))
        for idx, p in enumerate(periods):
            px = 220 + idx * col_w
            svg_parts.append(
                f'<text x="{px + col_w - 10}" y="{y}" fill="#94a3b8" font-size="11" font-weight="600" text-anchor="end">'
                f"{html.escape(p)}</text>"
            )

        svg_parts.append(
            f'<text x="{width - 32}" y="{y}" fill="#94a3b8" font-size="11" font-weight="600" text-anchor="end">YoY %</text>'
        )

        # Table Rows
        for r_idx, row in enumerate(rows):
            ry = header_h + 10 + (r_idx + 1) * row_h
            bg = "#1e293b" if r_idx % 2 == 1 else "transparent"
            if bg != "transparent":
                svg_parts.append(
                    f'<rect x="20" y="{ry - 18}" width="{width - 40}" height="{row_h}" fill="{bg}" />'
                )

            svg_parts.append(
                f'<text x="32" y="{ry}" fill="#f1f5f9" font-size="12" font-weight="500">'
                f"{html.escape(row['metric'])}</text>"
            )

            for idx, p in enumerate(periods):
                px = 220 + idx * col_w
                val_str = row["values"].get(p, "-")
                svg_parts.append(
                    f'<text x="{px + col_w - 10}" y="{ry}" fill="#cbd5e1" font-size="11" text-anchor="end">'
                    f"{html.escape(val_str)}</text>"
                )

            yoy = row.get("yoy_change_pct")
            if yoy is not None:
                color = "#34d399" if yoy >= 0 else "#f87171"
                prefix = "+" if yoy > 0 else ""
                yoy_str = f"{prefix}{yoy:.1f}%"
            else:
                color = "#94a3b8"
                yoy_str = "-"

            svg_parts.append(
                f'<text x="{width - 32}" y="{ry}" fill="{color}" font-size="11" font-weight="600" text-anchor="end">'
                f"{html.escape(yoy_str)}</text>"
            )

        svg_parts.append("</svg>")
        return "\n".join(svg_parts)
