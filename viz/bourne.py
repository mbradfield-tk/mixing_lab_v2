"""Bourne Protocol figures."""
from __future__ import annotations

import plotly.graph_objects as go

from viz import theme

T1_LINE_COLORS = ("#9AA3AB", theme.PRIMARY, theme.DARK_RED)


def t1_speed_plan(plan: dict) -> go.Figure:
    """Impeller speed vs fill volume at constant P/m (``core.bourne_plan.t1_speed_plan``)."""
    fig = go.Figure()
    for line, color in zip(plan["lines"], T1_LINE_COLORS):
        fig.add_trace(go.Scatter(x=plan["volumes"], y=line["rpm"], mode="lines",
                                 name=line["label"], line=dict(color=color, width=2)))
    v_c, rpm_c = plan["centre"]
    fig.add_trace(go.Scatter(
        x=[v_c], y=[rpm_c], mode="markers", name=f"Centre ({v_c:g} L)",
        marker=dict(color=theme.TEXT, size=11, symbol="circle", line=dict(color="#FFFFFF", width=2))))
    if plan["adj_volumes"]:
        for i, (line, color) in enumerate(zip(plan["lines"], T1_LINE_COLORS)):
            fig.add_trace(go.Scatter(
                x=plan["adj_volumes"], y=line["adj_rpm"], mode="markers",
                name="Fed-batch set-points" if i == 0 else None,
                showlegend=(i == 0),
                marker=dict(color=color, size=10, symbol="diamond",
                            line=dict(color=theme.TEXT, width=1)),
                hovertemplate="%{x:.3g} L → %{y:.1f} RPM<extra></extra>"))
    limit = {"line_dash": "dash", "line_color": theme.SLATE, "line_width": 1.2,
             "annotation_font": {"size": 11, "color": theme.SLATE}}
    if plan["n_min"] > 0:
        fig.add_hline(y=plan["n_min"], annotation_text=f"Min RPM ({plan['n_min']:.0f})",
                      annotation_position="top left", **limit)
    if plan["n_max"] > 0:
        fig.add_hline(y=plan["n_max"], annotation_text=f"Max RPM ({plan['n_max']:.0f})",
                      annotation_position="bottom left", **limit)
    fig.update_layout(xaxis_title="Fill volume (L)", yaxis_title="Impeller speed (RPM)")
    return fig
