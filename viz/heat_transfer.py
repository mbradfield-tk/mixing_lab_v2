"""Heat Transfer page figures: batch/reaction temperature profiles, jacket duty,
resistance breakdown, UA sweeps and U/UA response surfaces."""
from __future__ import annotations

import numpy as np
import plotly.graph_objects as go
from plotly.colors import get_colorscale
from plotly.subplots import make_subplots

from viz import theme


def sweep_colorscale(theme_name: str) -> list[list[float | str]]:
    if theme_name == "Cool/Warm":
        scale = get_colorscale("rdbu")
        return [[1.0 - position, color] for position, color in reversed(scale)]
    if theme_name == "Takeda":
        return theme.SEQUENTIAL
    name = {"Turbo": "turbo", "Viridis": "viridis", "X-ray": "greys"}.get(theme_name, "turbo")
    return get_colorscale(name)


def _ref_line(label: str, color: str = theme.REFERENCE) -> dict:
    return {"line_dash": "dot", "line_color": color, "line_width": 1.2, "annotation_text": label,
            "annotation_font": {"size": 11, "color": color}}


def reaction_profile(t, T, conversion_pct, t_label: str, t_jacket: float,
                     T_adiabatic: float) -> go.Figure:
    """Batch temperature (left axis) and conversion (right axis) vs time."""
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_trace(go.Scatter(x=t, y=T, mode="lines", name="Batch temperature",
                             line={"color": theme.PRIMARY, "width": 2}), secondary_y=False)
    fig.add_trace(go.Scatter(x=t, y=conversion_pct, mode="lines", name="Conversion",
                             line={"color": theme.SLATE, "width": 2, "dash": "dash"}), secondary_y=True)
    fig.add_hline(y=t_jacket, **_ref_line(f"Coolant {t_jacket:.1f} °C", theme.BLUE))
    if np.isfinite(T_adiabatic):
        fig.add_hline(y=T_adiabatic, **_ref_line(f"Adiabatic {T_adiabatic:.1f} °C"))
    fig.update_xaxes(title_text=f"Time ({t_label})")
    fig.update_yaxes(title_text="Temperature (°C)", secondary_y=False)
    fig.update_yaxes(title_text="Conversion (%)", range=[0, 105], secondary_y=True, showgrid=False)
    fig.update_layout(title="Reaction Temperature Profile", height=460)
    return fig


def batch_temperature(t_const, T_const, t_var, T_var, Tj_out, t_label: str,
                      t_target: float, t_jacket: float) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=t_const, y=T_const, mode="lines", name="Batch (const jacket)",
                             line={"color": theme.PRIMARY, "width": 2}))
    fig.add_trace(go.Scatter(x=t_var, y=T_var, mode="lines", name="Batch (variable jacket)",
                             line={"color": theme.SLATE, "width": 2}))
    fig.add_trace(go.Scatter(x=t_var, y=Tj_out, mode="lines", name="Jacket outlet",
                             line={"color": theme.BLUE, "width": 1.6, "dash": "dash"}))
    fig.add_hline(y=t_target, **_ref_line(f"Target {t_target:.1f} °C", theme.GREEN))
    fig.add_hline(y=t_jacket, **_ref_line(f"Jacket {t_jacket:.1f} °C", theme.BLUE))
    fig.update_layout(
        title="Batch Temperature Profile",
        xaxis_title=f"Time ({t_label})",
        yaxis_title="Temperature (°C)",
        height=460,
    )
    return fig


def jacket_duty(t_const, q_const, t_var, q_var, t_label: str) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=t_const, y=np.abs(q_const), mode="lines", name="|Q| const jacket",
                             line={"color": theme.PRIMARY, "width": 2}))
    fig.add_trace(go.Scatter(x=t_var, y=np.abs(q_var), mode="lines", name="|Q| variable jacket",
                             line={"color": theme.SLATE, "width": 2}))
    fig.update_layout(
        title="Jacket Heat Duty over Time",
        xaxis_title=f"Time ({t_label})",
        yaxis_title="|Q| (W)",
        height=380,
    )
    return fig


def resistance_bars(breakdown: list[tuple[str, float, float]]) -> go.Figure:
    """Horizontal bars of each resistance's share of the total (``resistance_breakdown``)."""
    labels = [name for name, _, _ in breakdown]
    pct = [p for _, _, p in breakdown]
    fig = go.Figure(go.Bar(
        x=pct, y=labels, orientation="h", marker_color=theme.PRIMARY,
        text=[f"{p:.1f}%" for p in pct], textposition="outside", cliponaxis=False,
        hovertemplate="%{y}: %{x:.1f}%<extra></extra>",
    ))
    fig.update_layout(
        title="Heat Transfer Resistance Contributions",
        xaxis_title="Contribution to total resistance (%)",
        xaxis={"range": [0, max(pct, default=100) * 1.18]},
        yaxis={"autorange": "reversed"},
        height=360,
    )
    return fig


def ua_vs_speed(rpm, ua, n_rpm: float, v_l: float) -> go.Figure:
    fig = go.Figure(go.Scatter(x=rpm, y=ua, mode="lines",
                               line={"color": theme.PRIMARY, "width": 2}, name="UA"))
    fig.add_vline(x=n_rpm, **_ref_line(f"{n_rpm:.0f} rpm"))
    fig.update_layout(title=f"UA vs Stir Speed (at {v_l:.3g} L)",
                      xaxis_title="Stir speed (rpm)", yaxis_title="UA (W/K)", height=360)
    return fig


def ua_vs_volume(volume, ua, v_l: float, n_rpm: float) -> go.Figure:
    fig = go.Figure(go.Scatter(x=volume, y=ua, mode="lines",
                               line={"color": theme.SLATE, "width": 2}, name="UA"))
    fig.add_vline(x=v_l, **_ref_line(f"{v_l:.3g} L"))
    fig.update_layout(title=f"UA vs Volume (at {n_rpm:.0f} rpm)",
                      xaxis_title="Liquid volume (L)", yaxis_title="UA (W/K)", height=360)
    return fig


def sweep_surface(x, y, z, x_name: str, y_name: str, limits: tuple[float, float],
                  colorscale, title: str, z_title: str) -> go.Figure:
    fig = go.Figure(go.Surface(
        x=x,
        y=y,
        z=z,
        colorscale=colorscale,
        cmin=limits[0],
        cmax=limits[1],
        colorbar={"title": z_title},
        hovertemplate=(f"{x_name}: %{{x:.4g}}<br>"
                       f"{y_name}: %{{y:.4g}}<br>"
                       f"{z_title}: %{{z:.4g}}<extra></extra>"),
    ))
    fig.update_layout(
        title=title,
        scene={
            "xaxis_title": x_name,
            "yaxis_title": y_name,
            "zaxis_title": z_title,
        },
        height=520,
        margin={"l": 0, "r": 0, "t": 50, "b": 0},
    )
    return fig
