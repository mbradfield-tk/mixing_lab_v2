"""Fluid Database figures: solvent property curves and blend phase stratification."""
from __future__ import annotations

import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from viz import theme

PHASE_COLORS = theme.SERIES


def property_curves(name: str, curves: dict, T_C: float) -> go.Figure:
    """3x2 property-vs-temperature panels (``core.solvents.property_curves``) with T marked."""
    titles = [title for title, _ in curves["series"]]
    fig = make_subplots(rows=3, cols=2, subplot_titles=titles,
                        vertical_spacing=0.12, horizontal_spacing=0.10)
    T_arr = curves["T"]
    idx = int(np.argmin(np.abs(T_arr - T_C)))
    for i, (_, y_arr) in enumerate(curves["series"]):
        r, c = i // 2 + 1, i % 2 + 1
        fig.add_trace(go.Scatter(x=T_arr, y=y_arr, mode="lines",
                                 line={"width": 2, "color": theme.PRIMARY}, showlegend=False), row=r, col=c)
        fig.add_trace(go.Scatter(x=[T_C], y=[y_arr[idx]], mode="markers",
                                 marker={"size": 9, "color": theme.TEXT, "line": {"width": 2, "color": "#FFFFFF"}},
                                 showlegend=False),
                      row=r, col=c)
        fig.update_xaxes(title_text="T (°C)", row=r, col=c)
    fig.update_layout(height=780, title=f"{name} — properties vs temperature")
    return fig


def message(msg: str) -> go.Figure:
    """Blank axes carrying a centred note (placeholder chart)."""
    fig = go.Figure()
    fig.add_annotation(x=0.5, y=0.5, text=msg, showarrow=False, font={"size": 13})
    fig.update_xaxes(visible=False, range=[0, 1])
    fig.update_yaxes(visible=False, range=[0, 1])
    fig.update_layout(height=430, margin={"t": 30, "b": 10})
    return fig


def phase_stack(phases: list[dict], unknown_split: bool) -> go.Figure:
    """Vessel diagram of settled liquid phases stacked bottom-up (``core.miscibility.settled_phases``),
    layer height proportional to volume fraction."""
    x0, x1 = 0.22, 0.78
    liquid_top = 0.82  # liquid fills 82% of vessel height (headspace above)
    fig = go.Figure()
    y = 0.0
    for i, ph in enumerate(phases):
        h = ph["vol"] * liquid_top
        fig.add_shape(type="rect", x0=x0, x1=x1, y0=y, y1=y + h,
                      fillcolor=PHASE_COLORS[i % len(PHASE_COLORS)],
                      opacity=0.55, line={"width": 0}, layer="below")
        fig.add_annotation(
            x=(x0 + x1) / 2, y=y + h / 2,
            text=(f"<b>{ph['label']}</b><br>"
                  f"{ph['vol'] * 100:.1f} vol% · ρ ≈ {ph['rho']:.0f} kg/m³"),
            showarrow=False, font={"size": 12, "color": "#2A2E33"},
            bgcolor="rgba(255,255,255,0.75)")
        y += h
    # Vessel outline (open top)
    for x0_, x1_, y0_, y1_ in ((x0, x1, 0, 0), (x0, x0, 0, 1.0), (x1, x1, 0, 1.0)):
        fig.add_shape(type="line", x0=x0_, x1=x1_, y0=y0_, y1=y1_,
                      line={"color": theme.SLATE, "width": 3})
    fig.add_shape(type="line", x0=x0, x1=x1, y0=liquid_top, y1=liquid_top,
                  line={"color": theme.SLATE, "width": 1, "dash": "dot"})

    n_ph = len(phases)
    title = ("Single-phase blend (settled)" if n_ph == 1
             else f"Predicted stratification — {n_ph} liquid phases (settled)")
    if unknown_split and n_ph > 1:
        fig.add_annotation(x=0.5, y=1.06, showarrow=False,
                           font={"size": 11},
                           text="❔ Some pairs lack miscibility data — split is indicative only.")
    fig.update_xaxes(visible=False, range=[0, 1])
    fig.update_yaxes(visible=False, range=[-0.04, 1.12])
    fig.update_layout(height=430, margin={"t": 40, "b": 10},
                      title={"text": title, "x": 0.5, "xanchor": "center"})
    return fig
