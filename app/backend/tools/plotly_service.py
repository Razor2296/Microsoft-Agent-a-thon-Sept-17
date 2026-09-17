"""
app/backend/plotly_service.py
Skill 2.7 — Interactive Dashboards (Plotly Charts Service)

Generates standalone interactive Plotly.js HTML chart widgets for rendering
inside PyWebView container iframe widgets.

LLM Reference: See app/skills/02_core_features/SKILLS_CORE.md § 2.7
"""
from __future__ import annotations

import json
import logging
from typing import List, Literal, Optional

from backend.core.libraries import get_assistant_logger
from backend.core.schemas import PlotlyChartRequest, PlotlyChartResult

logger = get_assistant_logger("plotly_service")


class PlotlyService:
    """
    Generates interactive Plotly HTML chart widgets.
    """

    def generate_chart_html(
        self,
        labels: List[str],
        values: List[float],
        title: str = "Chart",
        chart_type: Literal["bar", "line", "pie", "scatter"] = "bar",
        series_name: str = "Values",
    ) -> PlotlyChartResult:
        """
        Build an interactive Plotly HTML chart widget.

        Args:
            labels: List of X-axis categories or slice titles.
            values: List of numeric values.
            title: Header title of the chart.
            chart_type: Type of Plotly chart ("bar", "line", "pie", "scatter").
            series_name: Label for data series.

        Returns:
            PlotlyChartResult containing HTML widget string.
        """
        try:
            req = PlotlyChartRequest(
                chart_type=chart_type,
                title=title,
                labels=labels,
                values=values,
                series_name=series_name,
            )

            html_snippet = self._build_plotly_html(
                chart_type=req.chart_type,
                title=req.title,
                labels=req.labels,
                values=req.values,
                series_name=req.series_name,
            )

            logger.info(f"Generated Plotly {req.chart_type} chart '{req.title}' ({len(req.labels)} points)")
            return PlotlyChartResult(
                success=True,
                chart_type=req.chart_type,
                title=req.title,
                html_widget=html_snippet,
            )
        except Exception as err:
            logger.error(f"Plotly chart generation error: {err}", exc_info=True)
            return PlotlyChartResult(
                success=False,
                chart_type=chart_type,
                title=title,
                error=f"Plotly error: {str(err)}",
            )

    def _build_plotly_html(
        self,
        chart_type: str,
        title: str,
        labels: List[str],
        values: List[float],
        series_name: str,
    ) -> str:
        """Construct self-contained Plotly HTML document."""
        if chart_type == "pie":
            data_dict = [
                {
                    "labels": labels,
                    "values": values,
                    "type": "pie",
                    "textinfo": "label+percent",
                    "hoverinfo": "label+value+percent",
                }
            ]
        else:
            trace_type = "scatter" if chart_type in ("line", "scatter") else "bar"
            mode = "lines+markers" if chart_type == "line" else ("markers" if chart_type == "scatter" else None)

            trace = {
                "x": labels,
                "y": values,
                "type": trace_type,
                "name": series_name,
                "marker": {"color": "#4f46e5"},
            }
            if mode:
                trace["mode"] = mode
            data_dict = [trace]

        layout = {
            "title": {"text": title, "font": {"family": "Segoe UI, sans-serif", "size": 16}},
            "paper_bgcolor": "rgba(0,0,0,0)",
            "plot_bgcolor": "rgba(0,0,0,0)",
            "font": {"color": "#e2e8f0"},
            "margin": {"l": 40, "r": 20, "t": 40, "b": 40},
            "autosize": True,
        }

        data_json = json.dumps(data_dict)
        layout_json = json.dumps(layout)

        html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8" />
    <script src="https://cdn.plot.ly/plotly-2.27.0.min.js"></script>
    <style>
        body {{ margin: 0; padding: 0; background: transparent; overflow: hidden; }}
        #plotly-div {{ width: 100vw; height: 100vh; }}
    </style>
</head>
<body>
    <div id="plotly-div"></div>
    <script>
        var data = {data_json};
        var layout = {layout_json};
        Plotly.newPlot('plotly-div', data, layout, {{responsive: true, displayModeBar: false}});
    </script>
</body>
</html>"""
        return html
