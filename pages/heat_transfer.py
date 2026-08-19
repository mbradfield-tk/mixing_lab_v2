"""Heat Transfer Tool page (Taipy).

Two modes: (1) heat/cool a vessel to a target temperature via the jacket, and
(2) model the batch temperature profile produced by an exo/endothermic reaction.
The numerical engine lives in the standalone :mod:`heat_transfer_core` backend;
this module owns the page state, handlers, and markdown layout.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from taipy.gui import Markdown, notify

from heat_transfer_core import (
    FOULING_DEFAULT,
    LINING_CONDUCTIVITY,
    LINING_THICKNESS_DEFAULT,
    NUSSELT_CORRELATIONS,
    WALL_CONDUCTIVITY,
    _heat_transfer_coeffs,
    compute_batch,
    compute_reaction_profile,
    estimate_jacket_area,
    find_best_material_key,
    liquid_height_from_volume,
    load_csvs,
    safe_float,
)
from utils.menu_icons import inject_icons
from utils.solvent_properties import get_properties, list_solvents, resolve_solvent_name

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

# Temperature at which built-in solvent properties are evaluated for the initial
# dropdown selection (handlers re-evaluate at the user's start temperature).
FLUID_REF_T_C = 25.0

reactors_df, fluids_df, htm_db = load_csvs(DATA_DIR)
reactions_df = pd.read_csv(DATA_DIR / "reactions.csv")

reactor_options = sorted(reactors_df["reactor_name"].dropna().unique().tolist())
# Built-in solvent library plus user custom fluids from fluids.csv.
_custom_fluid_names = fluids_df["fluid_name"].dropna().astype(str).tolist()
fluid_options = sorted(set(list_solvents()) | set(_custom_fluid_names))
reaction_options = sorted(reactions_df["reaction_name"].dropna().unique().tolist())
htm_options = list(htm_db.keys())
nusselt_options = list(NUSSELT_CORRELATIONS.keys())
wall_options = list(WALL_CONDUCTIVITY.keys())
lining_options = ["None"] + list(LINING_CONDUCTIVITY.keys())


def _reactor_row(reactor_name: str) -> pd.Series:
    row = reactors_df.loc[reactors_df["reactor_name"] == reactor_name]
    return row.iloc[0] if not row.empty else pd.Series(dtype=object)


def _fluid_row(fluid_name: str) -> pd.Series:
    row = fluids_df.loc[fluids_df["fluid_name"] == fluid_name]
    return row.iloc[0] if not row.empty else pd.Series(dtype=object)


def _fluid_properties(fluid_name: str, T_C: float) -> dict:
    """Props for a custom fluid (fixed) or a built-in solvent (evaluated at T_C)."""
    row = _fluid_row(fluid_name)
    if not row.empty:
        return {
            "rho": safe_float(row.get("rho_kg_m3"), 1000.0),
            "mu": safe_float(row.get("mu_Pa_s"), 0.001),
            "cp": safe_float(row.get("Cp_J_per_kgK"), 4182.0),
            "k": safe_float(row.get("k_W_per_mK"), 0.607),
        }
    canonical = resolve_solvent_name(fluid_name)
    if canonical:
        p = get_properties(canonical, T_C)
        return {"rho": p["rho_kg_m3"], "mu": p["mu_Pa_s"],
                "cp": p["Cp_J_per_kgK"], "k": p["k_W_per_mK"]}
    return {"rho": 1000.0, "mu": 0.001, "cp": 4182.0, "k": 0.607}


def _reaction_row(reaction_name: str) -> pd.Series:
    row = reactions_df.loc[reactions_df["reaction_name"] == reaction_name]
    return row.iloc[0] if not row.empty else pd.Series(dtype=object)


selected_reactor = reactor_options[0]
selected_fluid = fluid_options[0]
selected_htm = htm_options[0]
nusselt_correlation = nusselt_options[0]

_r = _reactor_row(selected_reactor)

d_tank = safe_float(_r.get("D_tank_m"), 0.1)
d_imp = safe_float(_r.get("D_imp_m"), 0.05)
n_rpm = safe_float(_r.get("N_rpm_max"), 300.0)
np_in = safe_float(_r.get("Np"), 1.27)
v_l = safe_float(_r.get("V_L"), 1.0)
h_max = safe_float(_r.get("H_max_m"), safe_float(_r.get("H_m"), 0.2))
h_liquid = liquid_height_from_volume(v_l, d_tank, h_max)
a_ht = estimate_jacket_area(d_tank, h_liquid, str(_r.get("bottom_dish", "")))

_f0 = _fluid_properties(selected_fluid, FLUID_REF_T_C)
rho = _f0["rho"]
mu = _f0["mu"]
cp = _f0["cp"]
k_fluid = _f0["k"]

wall_material = find_best_material_key(str(_r.get("shell_material", "stainless steel")), wall_options)
wall_k = WALL_CONDUCTIVITY.get(wall_material, 16.0)
wall_thickness_mm = safe_float(_r.get("wall_thickness_mm"), 5.0)
lining_material = "None"
lining_k = 0.0
lining_thickness_mm = 0.0

_htm = htm_db[selected_htm]
cp_jacket = safe_float(_htm.get("Cp_J_kgK"), 3500.0)
v_jacket = 1.0
d_hyd_jacket = 0.05
m_dot_jacket = 1.0

fouling = FOULING_DEFAULT
mu_wall = 0.0
include_agitator = True
q_rxn = 0.0
t_start = 25.0
t_target = 5.0
t_jacket = -10.0
time_unit = "Minutes"

# Tool mode: heat/cool a vessel, or model a reaction's temperature profile.
HT_MODE_HEAT = "Heat / cool vessel"
HT_MODE_RXN = "Reaction temperature profile"
ht_mode = HT_MODE_HEAT
ht_mode_options = [HT_MODE_HEAT, HT_MODE_RXN]

# Reaction kinetics + heat of reaction (mode 2)
selected_reaction = reaction_options[0] if reaction_options else ""
_x = _reaction_row(selected_reaction)
rxn_order_options = ["1", "2", "pseudo-1", "pseudo-2"]
rxn_order = str(_x.get("order", "2")) if not _x.empty else "2"
rxn_k = safe_float(_x.get("k_value"), 0.5)
rxn_c0 = safe_float(_x.get("C0_mol_L"), 1.0)
rxn_dH = safe_float(_x.get("delta_H_kJ_mol"), -50.0)


def _adiabatic_readout(rho: float, cp: float, c0: float, dH_kJ: float,
                       t_start: float) -> tuple[float, float]:
    """Adiabatic rise (signed K) and temperature; volume cancels out."""
    rise = (-dH_kJ * 1000.0 * c0 * 1000.0) / (rho * cp) if (rho > 0 and cp > 0) else 0.0
    return rise, t_start + rise


def _adiabatic_text(rho: float, cp: float, c0: float, dH_kJ: float,
                    t_start: float) -> str:
    rise, t_ad = _adiabatic_readout(rho, cp, c0, dH_kJ, t_start)
    thermal = "exothermic" if dH_kJ < 0 else ("endothermic" if dH_kJ > 0 else "athermal")
    return (f"**Adiabatic ({thermal}):** ΔT ≈ {rise:+.1f} °C → T_ad ≈ {t_ad:.1f} °C "
            f"(no cooling, from T_start = {t_start:.1f} °C).")


rxn_adiabatic_text = _adiabatic_text(rho, cp, rxn_c0, rxn_dH, t_start)

rxn_result_ready = False
rxn_summary_df = pd.DataFrame(columns=["Metric", "Value"])
rxn_fig = go.Figure()
rxn_fig.update_layout(title="Reaction Temperature Profile", xaxis_title="Time (min)",
                      yaxis_title="Temperature (C)")

status_message = "Set inputs and click Compute."
kpi_df = pd.DataFrame([{"Metric": "U (W/m2.K)", "Value": "-"}])
corr_df = pd.DataFrame(columns=["Correlation", "Nu", "h_i (W/m2.K)", "U (W/m2.K)", "UA (W/K)", "Time (min)"])
htm_compare_df = pd.DataFrame(columns=["Medium", "h_o (W/m2.K)", "U (W/m2.K)", "UA (W/K)", "Time (min)", "In range"])
summary_df = pd.DataFrame(columns=["Metric", "Value"])
result_ready = False

temp_fig = go.Figure()
temp_fig.update_layout(title="Batch Temperature Profile", xaxis_title="Time (min)", yaxis_title="Temperature (C)")
duty_fig = go.Figure()
duty_fig.update_layout(title="Heat Duty over Time", xaxis_title="Time (min)", yaxis_title="|Q| (W)")

res_fig = go.Figure()
res_fig.update_layout(title="Heat Transfer Resistance Contributions",
                      xaxis_title="Contribution to total resistance (%)")
agitator_text = ""

ua_rpm_fig = go.Figure()
ua_rpm_fig.update_layout(title="UA vs Stir Speed", xaxis_title="Stir speed (rpm)", yaxis_title="UA (W/K)")
ua_vol_fig = go.Figure()
ua_vol_fig.update_layout(title="UA vs Volume", xaxis_title="Liquid volume (L)", yaxis_title="UA (W/K)")


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------
def _time_factor(unit: str) -> float:
    return {"Seconds": 1.0, "Minutes": 60.0, "Hours": 3600.0}.get(unit, 60.0)


def on_reactor_change(state):
    row = _reactor_row(state.selected_reactor)
    state.d_tank = safe_float(row.get("D_tank_m"), state.d_tank)
    state.d_imp = safe_float(row.get("D_imp_m"), state.d_imp)
    state.n_rpm = safe_float(row.get("N_rpm_max"), state.n_rpm)
    state.np_in = safe_float(row.get("Np"), state.np_in)
    state.v_l = safe_float(row.get("V_L"), state.v_l)
    _refresh_area(state)
    shell = find_best_material_key(str(row.get("shell_material", "stainless steel")), wall_options)
    state.wall_material = shell
    state.wall_k = WALL_CONDUCTIVITY.get(shell, 16.0)
    state.wall_thickness_mm = safe_float(row.get("wall_thickness_mm"), state.wall_thickness_mm)
    notify(state, "I", "Reactor defaults loaded.")


def _refresh_area(state):
    """Recompute the jacket heat-transfer area from the current liquid volume."""
    row = _reactor_row(state.selected_reactor)
    h_max_val = safe_float(row.get("H_max_m"), safe_float(row.get("H_m"), 0.2))
    h = liquid_height_from_volume(state.v_l, state.d_tank, h_max_val)
    state.a_ht = estimate_jacket_area(state.d_tank, h, str(row.get("bottom_dish", "")))


def on_v_l_change(state):
    _refresh_area(state)


def on_wall_material_change(state):
    state.wall_k = WALL_CONDUCTIVITY.get(state.wall_material, state.wall_k)


def on_fluid_change(state):
    props = _fluid_properties(state.selected_fluid, state.t_start)
    state.rho = props["rho"]
    state.mu = props["mu"]
    state.cp = props["cp"]
    state.k_fluid = props["k"]
    _refresh_adiabatic(state)
    notify(state, "I", "Fluid properties loaded.")


def on_htm_change(state):
    entry = htm_db[state.selected_htm]
    state.cp_jacket = safe_float(entry.get("Cp_J_kgK"), state.cp_jacket)
    notify(state, "I", "HTM defaults loaded.")


def on_lining_change(state):
    if state.lining_material == "None":
        state.lining_k = 0.0
        state.lining_thickness_mm = 0.0
        return
    state.lining_k = LINING_CONDUCTIVITY.get(state.lining_material, 0.0)
    state.lining_thickness_mm = LINING_THICKNESS_DEFAULT.get(state.lining_material, 0.002) * 1000.0


def on_reaction_change(state):
    row = _reaction_row(state.selected_reaction)
    if row.empty:
        return
    state.rxn_order = str(row.get("order", state.rxn_order))
    state.rxn_k = safe_float(row.get("k_value"), state.rxn_k)
    state.rxn_c0 = safe_float(row.get("C0_mol_L"), state.rxn_c0)
    state.rxn_dH = safe_float(row.get("delta_H_kJ_mol"), state.rxn_dH)
    _refresh_adiabatic(state)
    notify(state, "I", "Reaction kinetics and heat of reaction loaded.")


def _refresh_adiabatic(state):
    state.rxn_adiabatic_text = _adiabatic_text(
        state.rho, state.cp, state.rxn_c0, state.rxn_dH, state.t_start)


def on_rxn_input_change(state):
    _refresh_adiabatic(state)


def on_ht_mode_change(state):
    if state.ht_mode == HT_MODE_RXN:
        state.status_message = "Select a reaction and coolant temperature, then Compute."
    else:
        state.status_message = "Set the start / target / jacket temperatures, then Compute."


def _shared_ht_data(state) -> dict:
    """Inputs common to both modes (geometry, materials, fluid, jacket)."""
    return {
        "rho": state.rho,
        "mu": state.mu,
        "cp": state.cp,
        "k_fluid": state.k_fluid,
        "d_tank": state.d_tank,
        "d_imp": state.d_imp,
        "n_rpm": state.n_rpm,
        "np_in": state.np_in,
        "v_l": state.v_l,
        "mu_wall": state.mu_wall,
        "nusselt_correlation": state.nusselt_correlation,
        "htm_name": state.selected_htm,
        "v_jacket": state.v_jacket,
        "d_hyd_jacket": state.d_hyd_jacket,
        "m_dot_jacket": state.m_dot_jacket,
        "cp_jacket": state.cp_jacket,
        "include_agitator": state.include_agitator,
        "wall_k": state.wall_k,
        "wall_thickness_mm": state.wall_thickness_mm,
        "lining_k": state.lining_k,
        "lining_thickness_mm": state.lining_thickness_mm,
        "fouling": state.fouling,
        "a_ht": state.a_ht,
    }


def _compute_reaction(state):
    if state.rxn_k <= 0 or state.rxn_c0 <= 0:
        state.status_message = "Reaction needs a rate constant k > 0 and C0 > 0."
        notify(state, "E", state.status_message)
        return

    data = _shared_ht_data(state)
    data.update({
        "t_start": state.t_start,
        "t_jacket": state.t_jacket,
        "rxn_order": state.rxn_order,
        "rxn_k": state.rxn_k,
        "rxn_c0": state.rxn_c0,
        "rxn_dH": state.rxn_dH,
    })
    result = compute_reaction_profile(data, htm_db)

    t_factor = _time_factor(state.time_unit)
    t_label = state.time_unit.lower()
    t = result.t / t_factor

    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_trace(go.Scatter(x=t, y=result.T, mode="lines", name="Batch temperature",
                             line={"color": "#E1251B", "width": 2}), secondary_y=False)
    fig.add_trace(go.Scatter(x=t, y=result.conversion * 100.0, mode="lines", name="Conversion",
                             line={"color": "#1f77b4", "width": 2, "dash": "dash"}), secondary_y=True)
    fig.add_hline(y=state.t_jacket, line_dash="dot", line_color="#5C6670",
                  annotation_text=f"Coolant {state.t_jacket:.1f} C")
    if np.isfinite(result.T_adiabatic_c):
        fig.add_hline(y=result.T_adiabatic_c, line_dash="dot", line_color="#888888",
                      annotation_text=f"Adiabatic {result.T_adiabatic_c:.1f} C")
    fig.update_xaxes(title_text=f"Time ({t_label})")
    fig.update_yaxes(title_text="Temperature (C)", secondary_y=False)
    fig.update_yaxes(title_text="Conversion (%)", range=[0, 105], secondary_y=True)
    fig.update_layout(title="Reaction Temperature Profile", height=460,
                      legend={"orientation": "h", "y": 1.02, "yanchor": "bottom",
                              "x": 0.5, "xanchor": "center"})
    state.rxn_fig = fig
    state.rxn_summary_df = result.summary
    state.rxn_result_ready = True

    _complete = ("not reached" if not np_is_finite(result.t_complete_s)
                 else f"{result.t_complete_s / 60.0:.2f} min")
    thermal = "exothermic" if state.rxn_dH < 0 else ("endothermic" if state.rxn_dH > 0 else "athermal")
    state.status_message = (
        f"Reaction simulated ({thermal}). Peak T = {result.T_peak_c:.1f} C, "
        f"adiabatic T = {result.T_adiabatic_c:.1f} C, time to 99% conversion = {_complete}."
    )
    notify(state, "S", "Reaction temperature profile computed.")


def on_compute(state):
    if state.ht_mode == HT_MODE_RXN:
        _compute_reaction(state)
        return
    if state.t_target < state.t_start and state.t_jacket >= state.t_start:
        state.status_message = "Invalid cooling setup: jacket temperature must be below start temperature."
        notify(state, "E", state.status_message)
        return
    if state.t_target > state.t_start and state.t_jacket <= state.t_start:
        state.status_message = "Invalid heating setup: jacket temperature must be above start temperature."
        notify(state, "E", state.status_message)
        return
    if state.t_target < state.t_start and state.t_target < state.t_jacket:
        state.status_message = "Cooling target is below jacket temperature and is unreachable."
        notify(state, "E", state.status_message)
        return
    if state.t_target > state.t_start and state.t_target > state.t_jacket:
        state.status_message = "Heating target is above jacket temperature and is unreachable."
        notify(state, "E", state.status_message)
        return

    data = {
        "rho": state.rho,
        "mu": state.mu,
        "cp": state.cp,
        "k_fluid": state.k_fluid,
        "d_tank": state.d_tank,
        "d_imp": state.d_imp,
        "n_rpm": state.n_rpm,
        "np_in": state.np_in,
        "v_l": state.v_l,
        "t_start": state.t_start,
        "t_target": state.t_target,
        "t_jacket": state.t_jacket,
        "mu_wall": state.mu_wall,
        "nusselt_correlation": state.nusselt_correlation,
        "htm_name": state.selected_htm,
        "v_jacket": state.v_jacket,
        "d_hyd_jacket": state.d_hyd_jacket,
        "m_dot_jacket": state.m_dot_jacket,
        "cp_jacket": state.cp_jacket,
        "q_rxn": state.q_rxn,
        "include_agitator": state.include_agitator,
        "wall_k": state.wall_k,
        "wall_thickness_mm": state.wall_thickness_mm,
        "lining_k": state.lining_k,
        "lining_thickness_mm": state.lining_thickness_mm,
        "fouling": state.fouling,
        "a_ht": state.a_ht,
    }
    result = compute_batch(data, htm_db)

    state.kpi_df = pd.DataFrame(
        [
            {"Metric": "h_i (W/m2.K)", "Value": round(result.h_i, 2)},
            {"Metric": "h_o (W/m2.K)", "Value": round(result.h_o, 2)},
            {"Metric": "U (W/m2.K)", "Value": round(result.u, 2)},
            {"Metric": "UA (W/K)", "Value": round(result.u * state.a_ht, 2)},
            {"Metric": "Nu", "Value": round(result.nu, 2)},
            {"Metric": "Re", "Value": round(result.re, 0)},
            {"Metric": "Pr", "Value": round(result.pr, 2)},
        ]
    )
    state.corr_df = result.corr_comparison
    state.htm_compare_df = result.htm_comparison
    state.summary_df = result.summary

    t_factor = _time_factor(state.time_unit)
    t_label = state.time_unit.lower()
    t_const = result.t_const / t_factor
    t_var = result.t_var / t_factor

    temp_fig_local = go.Figure()
    temp_fig_local.add_trace(go.Scatter(x=t_const, y=result.T_const, mode="lines", name="Batch (const jacket)"))
    temp_fig_local.add_trace(go.Scatter(x=t_var, y=result.T_var, mode="lines", name="Batch (variable jacket)"))
    temp_fig_local.add_trace(go.Scatter(x=t_var, y=result.Tj_out, mode="lines", name="Jacket outlet", line={"dash": "dash"}))
    temp_fig_local.add_hline(y=state.t_target, line_dash="dot", annotation_text=f"Target {state.t_target:.1f} C")
    temp_fig_local.add_hline(y=state.t_jacket, line_dash="dot", annotation_text=f"Jacket {state.t_jacket:.1f} C")
    temp_fig_local.update_layout(
        title="Batch Temperature Profile",
        xaxis_title=f"Time ({t_label})",
        yaxis_title="Temperature (C)",
        height=460,
    )
    state.temp_fig = temp_fig_local

    duty_fig_local = go.Figure()
    duty_fig_local.add_trace(go.Scatter(x=t_const, y=np_abs(result.q_const), mode="lines", name="|Q| const jacket"))
    duty_fig_local.add_trace(go.Scatter(x=t_var, y=np_abs(result.q_var), mode="lines", name="|Q| variable jacket"))
    duty_fig_local.update_layout(
        title="Jacket Heat Duty over Time",
        xaxis_title=f"Time ({t_label})",
        yaxis_title="|Q| (W)",
        height=380,
    )
    state.duty_fig = duty_fig_local

    _build_resistance_breakdown(state, result)
    _build_ua_sweeps(state)

    analytical_txt = "Infinity" if not pd.notna(result.time_analytical_s) or not np_is_finite(result.time_analytical_s) else f"{result.time_analytical_s/60.0:.2f} min"
    state.status_message = (
        f"Computed successfully. U = {result.u:.1f} W/(m2.K), "
        f"simulated time (const jacket) = {result.time_const_jacket_s/60.0:.2f} min, "
        f"analytical = {analytical_txt}."
    )
    state.result_ready = True
    notify(state, "S", "Heat-transfer results computed.")


def np_abs(arr):
    return np.abs(arr)


def np_is_finite(value: float) -> bool:
    return np.isfinite(value)


def _build_resistance_breakdown(state, result) -> None:
    """Resistance-contribution bar chart + agitator heat share (heat/cool mode)."""
    items: list[tuple[str, float]] = []
    if result.h_i > 0:
        items.append(("Inside film (process)", 1.0 / result.h_i))
    if state.wall_k > 0 and state.wall_thickness_mm > 0:
        items.append(("Wall", (state.wall_thickness_mm / 1000.0) / state.wall_k))
    if state.lining_k > 0 and state.lining_thickness_mm > 0:
        items.append(("Lining", (state.lining_thickness_mm / 1000.0) / state.lining_k))
    if state.fouling > 0:
        items.append(("Fouling", state.fouling))
    if result.h_o > 0:
        items.append(("Outside film (jacket)", 1.0 / result.h_o))

    r_total = sum(r for _, r in items) or 1.0
    labels = [n for n, _ in items]
    pct = [r / r_total * 100.0 for _, r in items]

    fig = go.Figure(go.Bar(
        x=pct, y=labels, orientation="h", marker_color="#E1251B",
        text=[f"{p:.1f}%" for p in pct], textposition="auto",
        hovertemplate="%{y}: %{x:.1f}%<extra></extra>",
    ))
    fig.update_layout(
        title="Heat Transfer Resistance Contributions",
        xaxis_title="Contribution to total resistance (%)",
        yaxis={"autorange": "reversed"},
        height=360,
    )
    state.res_fig = fig

    p_ag = result.p_agitator_w
    q_duty = abs(result.q_max_w)
    if p_ag > 0:
        ag_pct = (p_ag / q_duty * 100.0) if q_duty > 0 else float("inf")
        pct_txt = "∞" if not np.isfinite(ag_pct) else f"{ag_pct:.1f}%"
        state.agitator_text = (
            f"**Agitator heat:** {p_ag:.2f} W — about **{pct_txt}** of the initial "
            f"jacket duty (Q_max = {q_duty:.1f} W)."
        )
    else:
        state.agitator_text = "**Agitator heat:** not included (toggle *Include agitator heat* to add it)."


def _build_ua_sweeps(state) -> None:
    """UA vs stir speed (area fixed) and UA vs volume (U fixed) around the op-point."""
    row = _reactor_row(state.selected_reactor)
    h_max_val = safe_float(row.get("H_max_m"), safe_float(row.get("H_m"), 0.2))
    bottom = str(row.get("bottom_dish", ""))
    base = _shared_ht_data(state)

    # (1) UA vs stir speed at the current volume (A held constant).
    cur_rpm = max(state.n_rpm, 1.0)
    rmin = safe_float(row.get("N_rpm_min"), 0.0)
    rmax = safe_float(row.get("N_rpm_max"), 0.0)
    if not (rmax > rmin > 0):
        rmin, rmax = max(1.0, 0.1 * cur_rpm), 2.0 * cur_rpm
    rpm_range = np.linspace(rmin, rmax, 40)
    ua_rpm = [_heat_transfer_coeffs({**base, "n_rpm": rpm}, htm_db)["u"] * state.a_ht
              for rpm in rpm_range]
    fig1 = go.Figure(go.Scatter(x=rpm_range, y=ua_rpm, mode="lines",
                                line={"color": "#E1251B", "width": 2}, name="UA"))
    fig1.add_vline(x=state.n_rpm, line_dash="dot", line_color="#5C6670",
                   annotation_text=f"{state.n_rpm:.0f} rpm")
    fig1.update_layout(title=f"UA vs Stir Speed (at {state.v_l:.3g} L)",
                       xaxis_title="Stir speed (rpm)", yaxis_title="UA (W/K)", height=360)
    state.ua_rpm_fig = fig1

    # (2) UA vs volume at the current stir speed (U independent of volume).
    u_fixed = _heat_transfer_coeffs(base, htm_db)["u"]
    cur_vol = max(state.v_l, 1e-6)
    vmin = safe_float(row.get("V_L_min"), 0.0)
    vmax = safe_float(row.get("V_L_max"), 0.0)
    if not (vmax > vmin > 0):
        vmin, vmax = 0.1 * cur_vol, 2.0 * cur_vol
    vmin = max(vmin, 1e-6)
    vol_range = np.linspace(vmin, vmax, 40)
    ua_vol = [u_fixed * estimate_jacket_area(state.d_tank,
                                             liquid_height_from_volume(vol, state.d_tank, h_max_val),
                                             bottom)
              for vol in vol_range]
    fig2 = go.Figure(go.Scatter(x=vol_range, y=ua_vol, mode="lines",
                                line={"color": "#1f77b4", "width": 2}, name="UA"))
    fig2.add_vline(x=state.v_l, line_dash="dot", line_color="#5C6670",
                   annotation_text=f"{state.v_l:.3g} L")
    fig2.update_layout(title=f"UA vs Volume (at {state.n_rpm:.0f} rpm)",
                       xaxis_title="Liquid volume (L)", yaxis_title="UA (W/K)", height=360)
    state.ua_vol_fig = fig2


heat_transfer_md = """
# __ICON:Heat_Transfer__Heat Transfer Tool

<|{status_message}|text|>

<|part|class_name=va-card|
## Mode
Choose whether to drive the batch to a target temperature with the jacket, or to
model the temperature profile produced by a reaction.
<|{ht_mode}|toggle|lov={ht_mode_options}|label=What to model|on_change=on_ht_mode_change|>
|>

<|part|class_name=va-card|
## 1. Reactor and Fluid Selection
<|layout|columns=1 1 1 1|
<|{selected_reactor}|selector|lov={reactor_options}|dropdown|label=Reactor|on_change=on_reactor_change|>

<|{selected_fluid}|selector|lov={fluid_options}|dropdown|label=Process fluid|on_change=on_fluid_change|>

<|{selected_htm}|selector|lov={htm_options}|dropdown|label=Heat transfer medium|on_change=on_htm_change|>

<|{nusselt_correlation}|selector|lov={nusselt_options}|dropdown|label=Nusselt correlation|>
|>
|>

<|part|class_name=va-card|
## 2. Geometry, Materials, and Operating Inputs
<|layout|columns=1 1 1 1|
<|{d_tank}|number|label=D_tank (m)|>

<|{d_imp}|number|label=D_imp (m)|>

<|{n_rpm}|number|label=N (RPM)|>

<|{np_in}|number|label=Np|>
|>

<|layout|columns=1 1 1 1|
<|{v_l}|number|label=Liquid volume (L)|on_change=on_v_l_change|>

<|{a_ht}|number|label=Heat-transfer area A_ht (m2)|>

<|{fouling}|number|label=Fouling resistance (m2.K/W)|>

<|{mu_wall}|number|label=mu at wall (Pa.s)|>
|>

<|layout|columns=1 1 1 1|
<|{wall_material}|selector|lov={wall_options}|dropdown|label=Wall material|on_change=on_wall_material_change|>

<|{wall_k}|number|label=Wall k (W/m.K)|>

<|{wall_thickness_mm}|number|label=Wall thickness (mm)|>

<|{lining_material}|selector|lov={lining_options}|dropdown|label=Lining|on_change=on_lining_change|>
|>

<|layout|columns=1 1 1 1|
<|{lining_k}|number|label=Lining k (W/m.K)|>

<|{lining_thickness_mm}|number|label=Lining thickness (mm)|>

<|{rho}|number|label=rho (kg/m3)|on_change=on_rxn_input_change|>

<|{mu}|number|label=mu (Pa.s)|>
|>

<|layout|columns=1 1 1 1|
<|{cp}|number|label=Cp (J/kg.K)|on_change=on_rxn_input_change|>

<|{k_fluid}|number|label=k fluid (W/m.K)|>

<|{v_jacket}|number|label=Jacket velocity (m/s)|>

<|{d_hyd_jacket}|number|label=Jacket hydraulic diameter (m)|>
|>

<|layout|columns=1 1 1 1|
<|{m_dot_jacket}|number|label=Jacket mass flow (kg/s)|>

<|{cp_jacket}|number|label=Jacket Cp (J/kg.K)|>

<|{q_rxn}|number|label=Extra heat input (W)|>

<|{include_agitator}|toggle|label=Include agitator heat|>
|>

<|layout|columns=1 1 1 1|
<|{t_start}|number|label=T_start (C)|on_change=on_rxn_input_change|>

<|{t_jacket}|number|label=Jacket / coolant T (C)|>

<|{time_unit}|selector|lov=Seconds;Minutes;Hours|dropdown|label=Plot time unit|>

<|part|render={ht_mode == "Heat / cool vessel"}|
<|{t_target}|number|label=T_target (C)|>
|>
|>
|>

<|part|render={ht_mode == "Reaction temperature profile"}|class_name=va-card|
## Reaction Kinetics and Heat of Reaction
Pick a reaction to auto-fill its kinetics, or edit the fields directly. The rate
constant is held fixed (isothermal-kinetics approximation; activation energy is
not modelled) and the profile runs until 99% conversion.
<|layout|columns=1 1 1 1 1|
<|{selected_reaction}|selector|lov={reaction_options}|dropdown|label=Reaction|on_change=on_reaction_change|>

<|{rxn_order}|selector|lov={rxn_order_options}|dropdown|label=Order|>

<|{rxn_k}|number|label=Rate constant k|>

<|{rxn_c0}|number|label=C0 (mol/L)|on_change=on_rxn_input_change|>

<|{rxn_dH}|number|label=dH_rxn (kJ/mol)|on_change=on_rxn_input_change|>
|>

<|{rxn_adiabatic_text}|text|mode=markdown|>
|>

<|Compute|button|on_action=on_compute|class_name=compute-btn|>

<|part|render={ht_mode == "Heat / cool vessel"}|
<|part|class_name=va-card|
## 3. Core KPIs
<|{kpi_df}|table|width=100%|>
|>

<|part|class_name=va-card|
## 4. Heat Transfer Resistances & Agitator Heat
Relative contribution of each series thermal resistance to the overall U.
<|chart|figure={res_fig}|height=360px|>

<|{agitator_text}|text|mode=markdown|>
|>

<|part|class_name=va-card|
## 5. UA Sensitivity
UA versus stir speed at the selected volume, and versus volume at the selected stir speed.
<|layout|columns=1 1|
<|chart|figure={ua_rpm_fig}|height=360px|>

<|chart|figure={ua_vol_fig}|height=360px|>
|>
|>

<|part|class_name=va-card|
## 6. Temperature and Heat-Duty Profiles
<|chart|figure={temp_fig}|height=460px|>
<|chart|figure={duty_fig}|height=380px|>
|>

<|part|class_name=va-card|
## 7. Correlation and HTM Comparisons
### Nusselt correlation comparison
<|{corr_df}|table|width=100%|rebuild|>

### Heat transfer medium comparison
<|{htm_compare_df}|table|width=100%|rebuild|>
|>

<|part|class_name=va-card|
## 8. Summary
<|{summary_df}|table|width=100%|>
|>
|>

<|part|render={ht_mode == "Reaction temperature profile" and rxn_result_ready}|class_name=va-card|
## Reaction Temperature Profile
Batch temperature (red) and conversion (blue, right axis) versus time. Dotted
lines mark the coolant temperature and the adiabatic temperature (the peak the
batch would reach with no cooling).
<|chart|figure={rxn_fig}|height=460px|>

## Reaction and Heat-Transfer Summary
<|{rxn_summary_df}|table|width=100%|>
|>
"""

page = Markdown(inject_icons(heat_transfer_md))
