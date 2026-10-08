"""Filling-dynamics figures: each parameter against dosing time, one figure per group."""
from __future__ import annotations

import math

import plotly.graph_objects as go
from plotly.subplots import make_subplots

PRIMARY = "#E1251B"
DA_THRESHOLDS = (0.1, 1.0)


def filling_group(time_min: list[float], series: list[dict], group: str) -> go.Figure:
    """Small multiples of ``series`` (``{label, values}``) against time; Da panels use a log
    axis with the 0.1 / 1 thresholds."""
    cols = 3 if len(series) > 4 else 2 if len(series) > 1 else 1
    rows = math.ceil(len(series) / cols)
    fig = make_subplots(rows=rows, cols=cols, subplot_titles=[s["label"] for s in series],
                        vertical_spacing=min(0.12, 0.5 / rows), horizontal_spacing=0.08)
    for i, s in enumerate(series):
        r, c = i // cols + 1, i % cols + 1
        fig.add_trace(go.Scatter(x=time_min, y=s["values"], mode="lines",
                                 line={"color": PRIMARY, "width": 2}, showlegend=False,
                                 hovertemplate="t = %{x:.3g} min<br>%{y:.4g}<extra>"
                                               + s["label"] + "</extra>"), row=r, col=c)
        finite = [v for v in s["values"] if v is not None and math.isfinite(v)]
        if group != "damkohler" and finite and max(finite) - min(finite) <= 1e-9 * abs(max(finite)):
            # A constant series: stop autoscaling from magnifying float noise.
            mid = finite[0]
            fig.update_yaxes(range=[mid - 0.1 * abs(mid), mid + 0.1 * abs(mid)], row=r, col=c)
        if group == "damkohler":
            values = [v for v in s["values"] if v is not None]
            if values and min(values) > 0:
                fig.update_yaxes(type="log", row=r, col=c)
            for y in DA_THRESHOLDS:
                fig.add_hline(y=y, line={"color": "#5C6670", "dash": "dash", "width": 1},
                              row=r, col=c)
        if r == rows or i + cols >= len(series):
            fig.update_xaxes(title_text="Time (min)", row=r, col=c)
    fig.update_annotations(font_size=12)
    fig.update_yaxes(exponentformat="e")
    fig.update_layout(height=230 * rows + 50, margin={"l": 60, "r": 20, "t": 30, "b": 50},
                      plot_bgcolor="rgba(225,37,27,0.04)")
    return fig


def temperature_profile(res: dict) -> go.Figure:
    """Batch temperature, heat flows and (with a reaction) conversion against time."""
    t = res["time_min"]
    reaction = any(x for x in res["conversion"] if x)
    rows = 3 if reaction else 2
    titles = ["Batch temperature (°C)", "Heat flows into the batch (W)", "Conversion (%)"][:rows]
    fig = make_subplots(rows=rows, cols=1, shared_xaxes=True, subplot_titles=titles,
                        vertical_spacing=0.08)
    fig.add_trace(go.Scatter(x=t, y=res["T_C"], name="Batch T", mode="lines",
                             line={"color": PRIMARY, "width": 2.5}), row=1, col=1)
    fig.add_hline(y=res["T_coolant_C"], line={"color": "#1f77b4", "dash": "dash", "width": 1},
                  annotation_text="Coolant", annotation_position="bottom right", row=1, col=1)
    if res["dT_ad_K"]:
        fig.add_hline(y=res["T_ad_C"], line={"color": "#5C6670", "dash": "dot", "width": 1},
                      annotation_text="No-cooling end T", annotation_position="top right",
                      row=1, col=1)
    for key, name, color in (("Q_rxn_W", "Reaction", PRIMARY), ("Q_feed_W", "Feed sensible", "#ff7f0e"),
                             ("Q_jacket_W", "Jacket", "#1f77b4")):
        if any(x for x in res[key] if x):
            fig.add_trace(go.Scatter(x=t, y=res[key], name=name, mode="lines",
                                     line={"color": color, "width": 2}), row=2, col=1)
    if reaction:
        fig.add_trace(go.Scatter(x=t, y=[100 * x if x is not None else None for x in res["conversion"]],
                                 name="Conversion", mode="lines", showlegend=False,
                                 line={"color": "#2ca02c", "width": 2}), row=3, col=1)
    fig.update_xaxes(title_text="Time (min)", row=rows, col=1)
    fig.update_annotations(font_size=12)
    fig.update_layout(height=260 * rows + 60, margin={"l": 60, "r": 20, "t": 30, "b": 50},
                      plot_bgcolor="rgba(225,37,27,0.04)",
                      legend={"orientation": "h", "y": -0.08 - 0.04 * (3 - rows)})
    return fig
