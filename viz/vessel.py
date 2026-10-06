"""Operating-envelope and response-surface figures (Vessel Assessment / Comparison)."""
from __future__ import annotations

import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots

DA_THRESHOLDS = ((0.1, "orange"), (1.0, "red"))
# Damköhler numbers: log axes with the 0.1 / 1 regime thresholds.
LOG_PARAMS = frozenset({"Da_macro", "Da_micro", "Da_meso", "Da_GL", "Da_SL"})
PALETTE = ["#E1251B", "#1f77b4", "#2ca02c", "#9467bd", "#ff7f0e",
           "#17becf", "#8c564b", "#e377c2", "#5C6670", "#bcbd22"]
DISPLAY_NAMES = {
    "Da_macro": "Macromixing (Da_macro)",
    "Da_micro": "Micromixing (Da_micro)",
    "Da_meso": "Mesomixing (Da_meso)",
    "Da_GL": "Gas–liquid transfer (Da_GL)",
    "Da_SL": "Solid–liquid transfer (Da_SL)",
    "Q_gen/Q_cool (%)": "Heat capacity (Q_gen/Q_cool %)",
}


def display_name(p: str) -> str:
    return DISPLAY_NAMES.get(p, p)


def _grid(n: int, max_cols: int) -> tuple[int, int, list[tuple[int, int]]]:
    cols = min(max_cols, n)
    rows = int(np.ceil(n / cols))
    return rows, cols, [(i // cols + 1, i % cols + 1) for i in range(n)]


def _legend_above(fig_height: int, t_margin: int = 90) -> float:
    # Legend y is a fraction of the plot-area height, so keep it ~45 px above.
    plot_area = max(fig_height - t_margin - 40, 120)
    return 1 + 45 / plot_area


def assessment_envelope(n_rpm, curves_hi: dict, curves_lo: dict, v_min: float, v_max: float,
                        params: list[str], op_rpm: float, op_values: dict,
                        log_params=()) -> tuple[go.Figure, int]:
    """(figure, subplot rows): per-parameter RPM sweeps bounded by V_max (solid) and
    V_min (dotted), the region between shaded, and the operating point starred."""
    n = len(params)
    rows, cols, positions = _grid(n, 3)
    # Inter-row gap must fit the lower row's x title and the next row's subplot title.
    vspace = min(0.22, 0.6 / max(rows - 1, 1))
    fig = make_subplots(rows=rows, cols=cols, subplot_titles=params,
                        vertical_spacing=vspace, horizontal_spacing=0.08)
    for p, (r, c) in zip(params, positions):
        first = (p == params[0])
        y_hi, y_lo = curves_hi[p], curves_lo[p]
        fig.add_trace(go.Scatter(
            x=np.concatenate([n_rpm, n_rpm[::-1]]),
            y=np.concatenate([y_hi, y_lo[::-1]]),
            fill="toself", fillcolor="rgba(92,102,112,0.22)",
            line={"width": 0}, hoverinfo="skip", showlegend=False), row=r, col=c)
        # Mid gray stays visible on both the light and dark chart backgrounds.
        fig.add_trace(go.Scatter(
            x=n_rpm, y=y_hi, mode="lines", line={"width": 2, "color": "#808080"},
            name=f"V_max = {v_max:.0f} L", legendgroup="vmax",
            showlegend=first), row=r, col=c)
        fig.add_trace(go.Scatter(
            x=n_rpm, y=y_lo, mode="lines",
            line={"width": 2, "color": "#808080", "dash": "dot"},
            name=f"V_min = {v_min:.0f} L", legendgroup="vmin",
            showlegend=first), row=r, col=c)
        fig.add_trace(go.Scatter(
            x=[op_rpm], y=[op_values[p]], mode="markers",
            marker={"symbol": "star", "size": 15, "color": "red",
                    "line": {"width": 1, "color": "black"}},
            name="Operating point", legendgroup="op",
            showlegend=first), row=r, col=c)
        fig.update_xaxes(title_text="N (RPM)", row=r, col=c)
        if p in log_params:
            fig.update_yaxes(type="log", row=r, col=c)
            for thr, col_ in DA_THRESHOLDS:
                fig.add_hline(y=thr, line_dash="dash", line_color=col_, row=r, col=c)
    fig_height = max(360, rows * 360)
    fig.update_layout(
        height=fig_height, margin={"t": 90, "b": 40},
        # No explicit paper/font colors: the host UI swaps the plotly template per
        # theme, so legends/titles/axes stay legible in light and dark mode.
        plot_bgcolor="rgba(225,37,27,0.06)",
        legend={"orientation": "h", "y": _legend_above(fig_height), "yanchor": "bottom",
                "x": 0.5, "xanchor": "center"})
    return fig, rows


def assessment_envelope_caption(v_min: float, v_max: float) -> str:
    return f"**Operating envelope** — RPM sweep across V = {v_min:.3g}–{v_max:.3g} L"


def assessment_surfaces(n_rpm, v_l, z: dict, params: list[str], op_rpm: float, op_v: float,
                        op_values: dict, log_params=()) -> tuple[go.Figure, int]:
    """(figure, subplot rows): 3D surfaces z = f(N, V) per parameter, with the
    operating point marked and translucent Da threshold planes on log panels."""
    n = len(params)
    rows, cols, _ = _grid(n, 3)
    fig = make_subplots(
        rows=rows, cols=cols, subplot_titles=params,
        specs=[[{"type": "surface"}] * cols for _ in range(rows)],
        vertical_spacing=0.06, horizontal_spacing=0.03)
    for idx, p in enumerate(params):
        r, c = idx // cols + 1, idx % cols + 1
        zp = z[p]
        log_z = p in log_params and bool(np.all(zp > 0))
        fig.add_trace(go.Surface(
            x=n_rpm, y=v_l, z=zp, colorscale="Viridis", showscale=False,
            opacity=0.9, name=p, showlegend=False,
            hovertemplate=("N = %{x:.0f} RPM<br>V = %{y:.3g} L<br>"
                           + p + " = %{z:.3g}<extra></extra>"),
            contours={"z": {"show": True, "usecolormap": True,
                            "project": {"z": True}}},
        ), row=r, col=c)
        if log_z:
            for thr, col_ in DA_THRESHOLDS:
                fig.add_trace(go.Surface(
                    x=n_rpm, y=v_l, z=np.full_like(zp, thr),
                    colorscale=[[0, col_], [1, col_]], showscale=False,
                    opacity=0.25, hoverinfo="skip", showlegend=False), row=r, col=c)
        fig.add_trace(go.Scatter3d(
            x=[op_rpm], y=[op_v], z=[op_values[p]], mode="markers",
            marker={"symbol": "diamond", "size": 7, "color": "red",
                    "line": {"width": 1, "color": "black"}},
            name="Operating point", legendgroup="op", showlegend=(idx == 0),
        ), row=r, col=c)
        fig.update_scenes(
            xaxis={"title": "N (RPM)"}, yaxis={"title": "V (L)"},
            zaxis={"title": p, "type": "log" if log_z else "linear"},
            camera={"eye": {"x": 1.6, "y": -1.6, "z": 0.9}},
            row=r, col=c)
    fig.update_layout(
        height=max(360, rows * 360), margin={"t": 60, "b": 10, "l": 0, "r": 0},
        legend={"orientation": "h", "y": 1.02, "yanchor": "bottom",
                "x": 0.5, "xanchor": "center"})
    return fig, rows


def assessment_surfaces_caption(n_rpm, v_min: float, v_max: float, n_pts: int, v_pts: int) -> str:
    return (f"**Response surfaces** — N = {n_rpm[0]:.0f}–{n_rpm[-1]:.0f} RPM × "
            f"V = {v_min:.3g}–{v_max:.3g} L ({n_pts}×{v_pts} grid)")


def comparison_envelope(curve_data: dict, reactors: list[str], params: list[str],
                        log_params=()) -> tuple[go.Figure, int]:
    """(figure, subplot rows): one shaded V_min–V_max band per vessel and parameter
    against stir speed as % of each vessel's max RPM."""
    n = len(params)
    rows, cols, positions = _grid(n, 2)
    vspace = min(0.22, 0.6 / max(rows - 1, 1))
    fig = make_subplots(rows=rows, cols=cols, subplot_titles=[display_name(p) for p in params],
                        vertical_spacing=vspace, horizontal_spacing=0.08)
    for pi, (param, (r, c)) in enumerate(zip(params, positions)):
        first_param = (pi == 0)
        for i, name in enumerate(reactors):
            color = PALETTE[i % len(PALETTE)]
            curves = curve_data[name]
            pct = curves["pct_arr"]
            y_hi = curves["maxV"][param]
            y_lo = curves["minV"][param]
            poly_x = np.concatenate([pct, pct[::-1], [pct[0]]])
            poly_y = np.concatenate([y_hi, y_lo[::-1], [y_hi[0]]])
            fig.add_trace(go.Scatter(
                x=poly_x, y=poly_y, fill="toself", fillcolor=color, opacity=0.18,
                line={"width": 0}, mode="lines", legendgroup=name,
                showlegend=False, hoverinfo="skip"), row=r, col=c)
            fig.add_trace(go.Scatter(
                x=pct, y=y_hi, mode="lines", line={"color": color, "width": 2},
                name=name, legendgroup=name, showlegend=first_param,
                hoverinfo="skip"), row=r, col=c)
            fig.add_trace(go.Scatter(
                x=pct, y=y_lo, mode="lines",
                line={"color": color, "width": 2, "dash": "dot"},
                legendgroup=name, showlegend=False, hoverinfo="skip"), row=r, col=c)
        fig.update_xaxes(title_text="Stir speed (% of max RPM)", range=[0, 105], row=r, col=c)
        if param in log_params:
            fig.update_yaxes(type="log", row=r, col=c)
            for thr, col_ in DA_THRESHOLDS:
                fig.add_hline(y=thr, line_dash="dash", line_color=col_, row=r, col=c)
        if param == "N/N_js":
            fig.add_hline(y=1.0, line_dash="dash", line_color="red", row=r, col=c)
        if param == "Q_gen/Q_cool (%)":
            fig.add_hline(y=100.0, line_dash="dash", line_color="red", row=r, col=c)
    fig_height = max(360, rows * 360)
    fig.update_layout(height=fig_height, margin={"t": 90, "b": 40},
                      plot_bgcolor="rgba(225,37,27,0.06)",
                      legend={"title": "Vessel", "orientation": "h",
                              "y": _legend_above(fig_height),
                              "yanchor": "bottom", "x": 0.5, "xanchor": "center"})
    return fig, rows
