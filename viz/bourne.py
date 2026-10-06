"""Bourne Protocol figures."""
from __future__ import annotations

import plotly.graph_objects as go

T1_LINE_COLORS = ("#9E9E9E", "#E1251B", "#7A1008")


def t1_speed_plan(plan: dict) -> go.Figure:
    """Impeller speed vs fill volume at constant P/m (``core.bourne_plan.t1_speed_plan``)."""
    fig = go.Figure()
    for line, color in zip(plan["lines"], T1_LINE_COLORS):
        fig.add_trace(go.Scatter(x=plan["volumes"], y=line["rpm"], mode="lines",
                                 name=line["label"], line=dict(color=color, width=2)))
    v_c, rpm_c = plan["centre"]
    fig.add_trace(go.Scatter(
        x=[v_c], y=[rpm_c], mode="markers", name=f"Centre ({v_c:g} L)",
        marker=dict(color="black", size=12, symbol="circle")))
    if plan["adj_volumes"]:
        for i, (line, color) in enumerate(zip(plan["lines"], T1_LINE_COLORS)):
            fig.add_trace(go.Scatter(
                x=plan["adj_volumes"], y=line["adj_rpm"], mode="markers",
                name="Fed-batch set-points" if i == 0 else None,
                showlegend=(i == 0),
                marker=dict(color=color, size=11, symbol="diamond",
                            line=dict(color="black", width=1)),
                hovertemplate="%{x:.3g} L → %{y:.1f} RPM<extra></extra>"))
    if plan["n_min"] > 0:
        fig.add_hline(y=plan["n_min"], line_dash="dash", line_color="gray",
                      annotation_text=f"Min RPM ({plan['n_min']:.0f})",
                      annotation_position="top left")
    if plan["n_max"] > 0:
        fig.add_hline(y=plan["n_max"], line_dash="dash", line_color="gray",
                      annotation_text=f"Max RPM ({plan['n_max']:.0f})",
                      annotation_position="bottom left")
    fig.update_layout(
        xaxis_title="Fill volume (L)", yaxis_title="Impeller speed (RPM)",
        # Dark legend text: the box stays white-ish even in dark mode.
        legend=dict(x=0.01, y=0.99, bgcolor="rgba(255,255,255,0.75)",
                    font=dict(color="#2A2E33")),
        margin=dict(l=10, r=10, t=30, b=10))
    return fig
