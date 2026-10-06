"""Heat Transfer Tool page (Taipy).

Two modes: (1) heat/cool a vessel to a target temperature via the jacket, and
(2) model the batch temperature profile produced by an exo/endothermic reaction.
The numerical engine lives in :mod:`core.heat_transfer`;
this module owns the page state, handlers, and markdown layout.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from taipy.gui import Markdown, download, notify

from core.heat_transfer import (
    FOULING_DEFAULT,
    LINING_CONDUCTIVITY,
    LINING_THICKNESS_DEFAULT,
    NUSSELT_CORRELATIONS,
    SWEEP_PARAMETERS,
    WALL_CONDUCTIVITY,
    adiabatic_rise,
    compute_batch,
    compute_reaction_profile,
    find_best_material_key,
    heat_cool_setup_error,
    liquid_height_from_volume,
    load_csvs,
    reactor_jacket_area,
    resistance_breakdown,
    resistance_items,
    round_sig,
    safe_float,
    surface_color_limits as _surface_color_limits,
    sweep_range_defaults,
    time_factor,
    u_ua_surface,
    ua_sweep_series,
)
from viz import heat_transfer as viz_ht
from reports import snapshots
from utils.menu_icons import inject_icons
from utils.report_builder import (
    build_heat_transfer_pdf,
    report_filename,
    report_header_label,
)
from core import catalog
from core.options import Toggle, is_on
from core.records import (
    range_midpoint as _avg_range,
    reaction_row as _reaction_row,
    reactor_row as _reactor_row,
    thermal_props,
)
from pages import _db_common as db

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

# Temperature at which built-in solvent properties are evaluated for the initial
# dropdown selection (handlers re-evaluate at the user's start temperature).
FLUID_REF_T_C = 25.0

reactors_df, fluids_df, htm_db = load_csvs(DATA_DIR)

reactor_options = sorted(reactors_df["reactor_name"].dropna().unique().tolist())
fluid_options = catalog.fluid_names()
reaction_class_options = catalog.reaction_names("yes")
reaction_measured_options = catalog.reaction_names("no")
reaction_source_options = ["Measured kinetics", "Reaction classes"]
reaction_options = reaction_measured_options or reaction_class_options
htm_options = list(htm_db.keys())
nusselt_options = list(NUSSELT_CORRELATIONS.keys())
wall_options = list(WALL_CONDUCTIVITY.keys())
lining_options = ["None"] + list(LINING_CONDUCTIVITY.keys())
UNIT_OPERATION_OPTIONS = ["- select -", "Reaction", "Quench", "Crystallization",
                          "Liquid-Liquid Extraction", "Distillation", "Filtration",
                          "Drying", "Other"]


_fluid_properties = thermal_props
_round_sig = round_sig


SWEEP_PARAMETER_KEYS = SWEEP_PARAMETERS
SWEEP_PARAMETER_OPTIONS = list(SWEEP_PARAMETER_KEYS)
SWEEP_COLOR_THEME_OPTIONS = ["Turbo", "Viridis", "Cool/Warm", "X-ray"]
SWEEP_COLOR_RANGE_OPTIONS = ["Automatic", "Custom"]


def _sweep_range_defaults(reactor_name: str, parameter: str, current_value: float) -> tuple[float, float]:
    """Use reactor operating bounds where available, otherwise bracket the current value."""
    return sweep_range_defaults(_reactor_row(reactor_name), SWEEP_PARAMETER_KEYS[parameter],
                                current_value)


_sweep_colorscale = viz_ht.sweep_colorscale


selected_reactor = ("TMA EasyMax-102" if "TMA EasyMax-102" in reactor_options
                    else (reactor_options[0] if reactor_options else ""))
selected_fluid = "Water" if "Water" in fluid_options else fluid_options[0]
selected_htm = htm_options[0]
nusselt_correlation = nusselt_options[0]

_r = _reactor_row(selected_reactor)

d_tank = safe_float(_r.get("D_tank_m"), 0.1)
d_imp = safe_float(_r.get("D_imp_m"), 0.05)
n_rpm = _avg_range(_r, "N_rpm_min", "N_rpm_max", 300.0)
np_in = safe_float(_r.get("Np"), 1.27)
v_l = _avg_range(_r, "V_L_min", "V_L_max", safe_float(_r.get("V_L"), 1.0))
h_max = safe_float(_r.get("H_max_m"), safe_float(_r.get("H_m"), 0.2))
h_liquid = liquid_height_from_volume(
    v_l, d_tank, h_max, str(_r.get("bottom_dish", "")), db.bottom_dish_height(_r))
a_ht = reactor_jacket_area(_r, d_tank, v_l)

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
sweep_x_parameter = "Stir speed (rpm)"
sweep_y_parameter = "Liquid volume (L)"
sweep_x_min, sweep_x_max = _sweep_range_defaults(selected_reactor, sweep_x_parameter, n_rpm)
sweep_y_min, sweep_y_max = _sweep_range_defaults(selected_reactor, sweep_y_parameter, v_l)
sweep_color_theme = "Turbo"
sweep_color_range_mode = "Automatic"
sweep_u_color_min = 0.0
sweep_u_color_max = 0.0
sweep_ua_color_min = 0.0
sweep_ua_color_max = 0.0
sweep_result_ready = False
sweep_u_fig = go.Figure()
sweep_u_fig.update_layout(title="Overall U Surface", height=500)
sweep_ua_fig = go.Figure()
sweep_ua_fig.update_layout(title="UA Surface", height=500)

_htm = htm_db[selected_htm]
cp_jacket = safe_float(_htm.get("Cp_J_kgK"), 3500.0)
v_jacket = 1.0
d_hyd_jacket = 0.05
m_dot_jacket = 1.0

fouling = FOULING_DEFAULT
mu_wall = 0.0
# String toggle: a lov-less boolean toggle in a page module never updates state.
include_agitator = Toggle.ON.label
include_agitator_options = Toggle.labels()
q_rxn = 0.0
t_start = 25.0
t_target = 5.0
t_jacket = -10.0
time_unit = "Minutes"

# Tool mode: heat/cool a vessel, or model a reaction's temperature profile.
HT_MODE_HEAT = "Heat / cool vessel"
HT_MODE_RXN = "Reaction temperature profile"
HT_MODE_SWEEP = "Parameter Sweep"
ht_mode = HT_MODE_HEAT
ht_mode_options = [HT_MODE_HEAT, HT_MODE_RXN, HT_MODE_SWEEP]

# Reaction kinetics + heat of reaction (mode 2)
selected_reaction_source = reaction_source_options[0]
selected_reaction_options = reaction_options
selected_reaction = selected_reaction_options[0] if selected_reaction_options else ""
_x = _reaction_row(selected_reaction)
rxn_order_options = ["1", "2", "pseudo-1", "pseudo-2"]
rxn_order = str(_x.get("order", "2")) if not _x.empty else "2"
rxn_k = safe_float(_x.get("k_value"), 0.5)
rxn_c0 = safe_float(_x.get("C0_mol_L"), 1.0)
rxn_dH = safe_float(_x.get("delta_H_kJ_mol"), -50.0)


def _adiabatic_readout(rho: float, cp: float, c0: float, dH_kJ: float,
                       t_start: float) -> tuple[float, float]:
    """Adiabatic rise (signed K) and temperature; volume cancels out."""
    rise = adiabatic_rise(rho, cp, c0, dH_kJ)
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
rxn_summary_csv = b""
kpi_csv = b""
corr_csv = b""
htm_compare_csv = b""
summary_csv = b""

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

# Project Information (captured in the exported PDF's header/filename and body)
ht_project_name = ""
ht_step_text = ""
ht_unit_operation = UNIT_OPERATION_OPTIONS[0]
ht_process_version = ""
ht_pdf_bytes = b""
ht_pdf_name = "Heat_Transfer.pdf"
ht_pdf_ready = False


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------
_time_factor = time_factor


def _build_csv_exports(state):
    """Refresh CSV download content from the current heat-transfer tables."""
    empty = pd.DataFrame()
    state.rxn_summary_csv = db.csv_bytes(getattr(state, "rxn_summary_df", empty))
    state.kpi_csv = db.csv_bytes(getattr(state, "kpi_df", empty))
    state.corr_csv = db.csv_bytes(getattr(state, "corr_df", empty))
    state.htm_compare_csv = db.csv_bytes(getattr(state, "htm_compare_df", empty))
    state.summary_csv = db.csv_bytes(getattr(state, "summary_df", empty))


def on_reactor_change(state):
    row = _reactor_row(state.selected_reactor)
    state.d_tank = safe_float(row.get("D_tank_m"), state.d_tank)
    state.d_imp = safe_float(row.get("D_imp_m"), state.d_imp)
    state.n_rpm = _avg_range(row, "N_rpm_min", "N_rpm_max", state.n_rpm)
    state.np_in = safe_float(row.get("Np"), state.np_in)
    state.v_l = _avg_range(row, "V_L_min", "V_L_max", safe_float(row.get("V_L"), state.v_l))
    _refresh_area(state)
    shell = find_best_material_key(str(row.get("shell_material", "stainless steel")), wall_options)
    state.wall_material = shell
    state.wall_k = WALL_CONDUCTIVITY.get(shell, 16.0)
    state.wall_thickness_mm = safe_float(row.get("wall_thickness_mm"), state.wall_thickness_mm)
    raw_lining = row.get("lining_material", "")
    lining_name = str(raw_lining).strip() if pd.notna(raw_lining) else ""
    state.lining_material = find_best_material_key(lining_name, lining_options)
    on_lining_change(state)
    _refresh_sweep_ranges(state)
    notify(state, "I", "Reactor defaults loaded.")


def _refresh_sweep_ranges(state) -> None:
    for axis in ("x", "y"):
        parameter = getattr(state, f"sweep_{axis}_parameter")
        key = SWEEP_PARAMETER_KEYS[parameter]
        current = getattr(state, key)
        lower, upper = _sweep_range_defaults(state.selected_reactor, parameter, current)
        setattr(state, f"sweep_{axis}_min", lower)
        setattr(state, f"sweep_{axis}_max", upper)


def _on_sweep_parameter_change(state, changed_axis: str) -> None:
    other_axis = "y" if changed_axis == "x" else "x"
    changed_parameter = getattr(state, f"sweep_{changed_axis}_parameter")
    if changed_parameter == getattr(state, f"sweep_{other_axis}_parameter"):
        replacement = next(option for option in SWEEP_PARAMETER_OPTIONS
                           if option != changed_parameter)
        setattr(state, f"sweep_{other_axis}_parameter", replacement)
    _refresh_sweep_ranges(state)
    state.sweep_result_ready = False


def on_sweep_x_change(state):
    _on_sweep_parameter_change(state, "x")


def on_sweep_y_change(state):
    _on_sweep_parameter_change(state, "y")


def on_sweep_color_range_mode_change(state):
    if state.sweep_color_range_mode != "Custom":
        return
    for metric, figure_name in (("u", "sweep_u_fig"), ("ua", "sweep_ua_fig")):
        figure = getattr(state, figure_name)
        if not figure.data:
            continue
        lower, upper = _surface_color_limits(np.asarray(figure.data[0].z, dtype=float))
        setattr(state, f"sweep_{metric}_color_min", lower)
        setattr(state, f"sweep_{metric}_color_max", upper)


def _refresh_area(state):
    """Recompute the jacket heat-transfer area from the current liquid volume."""
    state.a_ht = reactor_jacket_area(_reactor_row(state.selected_reactor), state.d_tank, state.v_l)


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


def on_reaction_source_change(state):
    state.selected_reaction_options = (reaction_class_options
                                       if state.selected_reaction_source == "Reaction classes"
                                       else reaction_measured_options) or ["(none available)"]
    if state.selected_reaction not in state.selected_reaction_options:
        state.selected_reaction = state.selected_reaction_options[0]
    on_reaction_change(state)


def _refresh_adiabatic(state):
    state.rxn_adiabatic_text = _adiabatic_text(
        state.rho, state.cp, state.rxn_c0, state.rxn_dH, state.t_start)


def on_rxn_input_change(state):
    _refresh_adiabatic(state)


def on_ht_mode_change(state):
    if state.ht_mode == HT_MODE_RXN:
        state.status_message = "Select a reaction and coolant temperature, then Compute."
    elif state.ht_mode == HT_MODE_SWEEP:
        state.status_message = "Choose two parameters and their ranges, then Compute."
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
        "include_agitator": is_on(state.include_agitator),
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
    state.rxn_fig = viz_ht.reaction_profile(result.t / t_factor, result.T,
                                            result.conversion * 100.0, t_label,
                                            state.t_jacket, result.T_adiabatic_c)
    state.rxn_summary_df = result.summary
    state.rxn_result_ready = True
    _build_csv_exports(state)

    _complete = ("not reached" if not np_is_finite(result.t_complete_s)
                 else f"{result.t_complete_s / 60.0:.2f} min")
    thermal = "exothermic" if state.rxn_dH < 0 else ("endothermic" if state.rxn_dH > 0 else "athermal")
    state.status_message = (
        f"Reaction simulated ({thermal}). Peak T = {result.T_peak_c:.1f} C, "
        f"adiabatic T = {result.T_adiabatic_c:.1f} C, time to 99% conversion = {_complete}."
    )
    notify(state, "S", "Reaction temperature profile computed.")


def on_compute(state):
    if state.ht_mode == HT_MODE_SWEEP:
        _compute_parameter_sweep(state)
        return
    if state.ht_mode == HT_MODE_RXN:
        _compute_reaction(state)
        return
    error = heat_cool_setup_error(state.t_start, state.t_target, state.t_jacket)
    if error:
        state.status_message = error
        notify(state, "E", state.status_message)
        return

    data = {**_shared_ht_data(state), "t_start": state.t_start, "t_target": state.t_target,
            "t_jacket": state.t_jacket, "q_rxn": state.q_rxn}
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
    state.temp_fig = viz_ht.batch_temperature(t_const, result.T_const, t_var, result.T_var,
                                              result.Tj_out, t_label, state.t_target,
                                              state.t_jacket)
    state.duty_fig = viz_ht.jacket_duty(t_const, result.q_const, t_var, result.q_var, t_label)

    _build_resistance_breakdown(state, result)
    _build_ua_sweeps(state)
    _build_csv_exports(state)

    analytical_txt = "Infinity" if not pd.notna(result.time_analytical_s) or not np_is_finite(result.time_analytical_s) else f"{result.time_analytical_s/60.0:.2f} min"
    state.status_message = (
        f"Computed successfully. U = {result.u:.1f} W/(m2.K), "
        f"simulated time (const jacket) = {result.time_const_jacket_s/60.0:.2f} min, "
        f"analytical = {analytical_txt}."
    )
    state.result_ready = True
    notify(state, "S", "Heat-transfer results computed.")


def np_is_finite(value: float) -> bool:
    return np.isfinite(value)


def _resistance_items(state, result) -> list[tuple[str, float]]:
    """Series thermal resistances (name, R value) feeding both the chart and the PDF."""
    return resistance_items(result.h_i, result.h_o, state.wall_k, state.wall_thickness_mm,
                            state.lining_k, state.lining_thickness_mm, state.fouling)


def _build_resistance_breakdown(state, result) -> None:
    """Resistance-contribution bar chart + agitator heat share (heat/cool mode)."""
    state.res_fig = viz_ht.resistance_bars(resistance_breakdown(_resistance_items(state, result)))

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
    s = ua_sweep_series(_shared_ht_data(state), htm_db, _reactor_row(state.selected_reactor),
                        state.a_ht)
    state.ua_rpm_fig = viz_ht.ua_vs_speed(s["rpm"], s["ua_rpm"], state.n_rpm, state.v_l)
    state.ua_vol_fig = viz_ht.ua_vs_volume(s["volume"], s["ua_volume"], state.v_l, state.n_rpm)


def _compute_parameter_sweep(state) -> None:
    x_parameter = state.sweep_x_parameter
    y_parameter = state.sweep_y_parameter
    if x_parameter == y_parameter:
        state.sweep_result_ready = False
        state.status_message = "Choose two different parameters for the sweep."
        notify(state, "E", state.status_message)
        return

    x_min = safe_float(state.sweep_x_min, float("nan"))
    x_max = safe_float(state.sweep_x_max, float("nan"))
    y_min = safe_float(state.sweep_y_min, float("nan"))
    y_max = safe_float(state.sweep_y_max, float("nan"))
    if not all(np.isfinite(value) for value in (x_min, x_max, y_min, y_max)) or x_max <= x_min or y_max <= y_min:
        state.sweep_result_ready = False
        state.status_message = "Each sweep maximum must be greater than its minimum."
        notify(state, "E", state.status_message)
        return

    x_key = SWEEP_PARAMETER_KEYS[x_parameter]
    y_key = SWEEP_PARAMETER_KEYS[y_parameter]
    x_values = np.linspace(x_min, x_max, 30)
    y_values = np.linspace(y_min, y_max, 30)
    reactor = _reactor_row(state.selected_reactor)
    u_values, ua_values = u_ua_surface(
        _shared_ht_data(state), htm_db, x_key, x_values, y_key, y_values, state.a_ht,
        h_max=safe_float(reactor.get("H_max_m"), safe_float(reactor.get("H_m"), 0.2)),
        bottom_dish=str(reactor.get("bottom_dish", "")),
        dish_height=db.bottom_dish_height(reactor))

    u_auto_limits = _surface_color_limits(u_values)
    ua_auto_limits = _surface_color_limits(ua_values)
    if state.sweep_color_range_mode == "Automatic":
        state.sweep_u_color_min, state.sweep_u_color_max = u_auto_limits
        state.sweep_ua_color_min, state.sweep_ua_color_max = ua_auto_limits
        u_color_limits = u_auto_limits
        ua_color_limits = ua_auto_limits
    else:
        u_color_limits = (safe_float(state.sweep_u_color_min, float("nan")),
                          safe_float(state.sweep_u_color_max, float("nan")))
        ua_color_limits = (safe_float(state.sweep_ua_color_min, float("nan")),
                           safe_float(state.sweep_ua_color_max, float("nan")))
        if u_color_limits == (0.0, 0.0):
            u_color_limits = u_auto_limits
            state.sweep_u_color_min, state.sweep_u_color_max = u_color_limits
        if ua_color_limits == (0.0, 0.0):
            ua_color_limits = ua_auto_limits
            state.sweep_ua_color_min, state.sweep_ua_color_max = ua_color_limits
        if not all(np.isfinite(value) for value in (*u_color_limits, *ua_color_limits)) \
                or u_color_limits[1] <= u_color_limits[0] or ua_color_limits[1] <= ua_color_limits[0]:
            state.sweep_result_ready = False
            state.status_message = "Each custom color maximum must be greater than its minimum."
            notify(state, "E", state.status_message)
            return

    colorscale = _sweep_colorscale(state.sweep_color_theme)
    state.sweep_u_fig = viz_ht.sweep_surface(
        x_values, y_values, u_values, x_parameter, y_parameter, u_color_limits, colorscale,
        "Overall Heat-Transfer Coefficient U", "U (W/m2.K)")
    state.sweep_ua_fig = viz_ht.sweep_surface(
        x_values, y_values, ua_values, x_parameter, y_parameter, ua_color_limits, colorscale,
        "Overall Heat-Transfer Capacity UA", "UA (W/K)")
    state.sweep_result_ready = True
    state.status_message = f"Parameter sweep computed for {x_parameter} and {y_parameter}."
    notify(state, "S", "U and UA parameter surfaces computed.")


def on_ht_export_pdf(state):
    if state.ht_mode == HT_MODE_RXN:
        _export_reaction_pdf(state)
    else:
        _export_batch_pdf(state)


def _project(state) -> dict:
    unit_op = state.ht_unit_operation if state.ht_unit_operation != UNIT_OPERATION_OPTIONS[0] else ""
    return snapshots.project_meta(state.ht_project_name, state.ht_step_text, unit_op,
                                  state.ht_process_version)


def _finish_pdf(state, snap: dict) -> None:
    state.ht_pdf_bytes = build_heat_transfer_pdf(snap)
    state.ht_pdf_name = report_filename(
        "HeatTransfer", report_header_label(snap) or state.selected_reactor)
    state.ht_pdf_ready = True
    notify(state, "S", "PDF report generated \u2014 click Download.")


def _export_batch_pdf(state):
    if not state.result_ready:
        notify(state, "W", "Compute the heat/cool vessel results before exporting a PDF.")
        return
    try:
        data = {**_shared_ht_data(state), "t_start": state.t_start,
                "t_target": state.t_target, "t_jacket": state.t_jacket, "q_rxn": state.q_rxn}
        _finish_pdf(state, snapshots.heat_cool_snapshot(
            data, htm_db, _reactor_row(state.selected_reactor), reactor=state.selected_reactor,
            fluid=state.selected_fluid, wall_material=state.wall_material,
            lining_material=state.lining_material, time_unit=state.time_unit,
            project=_project(state)))
    except Exception as exc:  # noqa: BLE001 - surface builder errors to the user
        notify(state, "E", f"PDF generation failed: {exc}")


def _export_reaction_pdf(state):
    if not state.rxn_result_ready:
        notify(state, "W", "Compute the reaction temperature profile before exporting a PDF.")
        return
    try:
        data = {**_shared_ht_data(state), "t_start": state.t_start, "t_jacket": state.t_jacket,
                "rxn_order": state.rxn_order, "rxn_k": state.rxn_k, "rxn_c0": state.rxn_c0,
                "rxn_dH": state.rxn_dH}
        _finish_pdf(state, snapshots.reaction_snapshot(
            data, htm_db, reactor=state.selected_reactor, fluid=state.selected_fluid,
            time_unit=state.time_unit, project=_project(state)))
    except Exception as exc:  # noqa: BLE001 - surface builder errors to the user
        notify(state, "E", f"PDF generation failed: {exc}")


def on_ht_pdf_download(state):
    # file_download's `name` property is static, so the filename must be set
    # via the imperative download() call rather than the control's binding.
    if not state.ht_pdf_ready:
        return
    download(state, content=state.ht_pdf_bytes, name=state.ht_pdf_name)




heat_transfer_md = """
# __ICON:Heat_Transfer__Heat Transfer Tool

<|{status_message}|text|>

<|part|class_name=va-card|
## Mode
Choose heat/cool operation, a reaction temperature profile, or a two-parameter U/UA sweep.
<|{ht_mode}|toggle|lov={ht_mode_options}|label=What to model|on_change=on_ht_mode_change|>
|>

<|part|class_name=va-card|
## Project Information
<|layout|columns=1 1 1 1|
<|{ht_project_name}|input|label=Project name|>

<|{ht_step_text}|input|label=Step|>

<|{ht_unit_operation}|selector|lov={UNIT_OPERATION_OPTIONS}|dropdown|label=Unit operation|>

<|{ht_process_version}|input|label=Process version|>
|>
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
### Reactor & Operating Point
<|layout|columns=1 1 1 1|
<|{d_tank}|number|label=D_tank (m)|>

<|{d_imp}|number|label=D_imp (m)|>

<|{np_in}|number|label=Np|>

<|{n_rpm}|number|label=N (RPM)|>
|>

<|layout|columns=1 1 1 1|
<|{v_l}|number|label=Liquid volume (L)|on_change=on_v_l_change|>

<|{a_ht}|number|label=Heat-transfer area A_ht (m²)|>

<|{fouling}|number|label=Fouling resistance (m²·K/W)|>

<|{q_rxn}|number|label=Extra heat input (W)|>
|>

<|{include_agitator}|toggle|lov={include_agitator_options}|label=Include agitator heat|class_name=onoff-toggle|>

### Wall
<|layout|columns=1 1 1 1|
<|{wall_material}|selector|lov={wall_options}|dropdown|label=Wall material|on_change=on_wall_material_change|>

<|{wall_k}|number|label=Wall k (W/m.K)|>

<|{wall_thickness_mm}|number|label=Wall thickness (mm)|>

<|{mu_wall}|number|label=mu at wall (Pa.s)|>
|>

### Lining
<|layout|columns=1 1 1 1|
<|{lining_material}|selector|lov={lining_options}|dropdown|label=Lining|on_change=on_lining_change|>

<|{lining_k}|number|label=Lining k (W/m.K)|>

<|{lining_thickness_mm}|number|label=Lining thickness (mm)|>
|>

### Fluid Properties
<|layout|columns=1 1 1 1|
<|{rho}|number|label=rho (kg/m3)|on_change=on_rxn_input_change|>

<|{mu}|number|label=mu (Pa.s)|>

<|{cp}|number|label=Cp (J/kg.K)|on_change=on_rxn_input_change|>

<|{k_fluid}|number|label=k fluid (W/m.K)|>
|>

### Jacket
<|layout|columns=1 1 1 1|
<|{v_jacket}|number|label=Jacket velocity (m/s)|>

<|{d_hyd_jacket}|number|label=Jacket hydraulic diameter (m)|>

<|{m_dot_jacket}|number|label=Jacket mass flow (kg/s)|>

<|{cp_jacket}|number|label=Jacket Cp (J/kg.K)|>
|>

### Temperatures
<|layout|columns=1 1 1 1|
<|{t_start}|number|label=T_start (C)|on_change=on_rxn_input_change|>

<|{t_jacket}|number|label=Jacket / coolant T (C)|>

<|part|render={ht_mode == "Heat / cool vessel"}|
<|{t_target}|number|label=T_target (C)|>
|>

<|{time_unit}|selector|lov=Seconds;Minutes;Hours|dropdown|label=Plot time unit|>
|>
|>

<|part|render={ht_mode == "Parameter Sweep"}|class_name=va-card|
## Parameter Sweep Inputs
### X axis
<|layout|columns=1 1 1|
<|{sweep_x_parameter}|selector|lov={SWEEP_PARAMETER_OPTIONS}|dropdown|label=X-axis parameter|on_change=on_sweep_x_change|>

<|{sweep_x_min}|number|label=X minimum|>

<|{sweep_x_max}|number|label=X maximum|>
|>

### Y axis
<|layout|columns=1 1 1|
<|{sweep_y_parameter}|selector|lov={SWEEP_PARAMETER_OPTIONS}|dropdown|label=Y-axis parameter|on_change=on_sweep_y_change|>

<|{sweep_y_min}|number|label=Y minimum|>

<|{sweep_y_max}|number|label=Y maximum|>
|>

### Surface Appearance
<|layout|columns=1 1|
<|{sweep_color_theme}|selector|lov={SWEEP_COLOR_THEME_OPTIONS}|dropdown|label=Color theme|>

<|{sweep_color_range_mode}|selector|lov={SWEEP_COLOR_RANGE_OPTIONS}|dropdown|label=Color range|on_change=on_sweep_color_range_mode_change|>
|>
<|part|render={sweep_color_range_mode == "Custom"}|
### U color range
<|layout|columns=1 1|
<|{sweep_u_color_min}|number|label=U color minimum|>

<|{sweep_u_color_max}|number|label=U color maximum|>
|>

### UA color range
<|layout|columns=1 1|
<|{sweep_ua_color_min}|number|label=UA color minimum|>

<|{sweep_ua_color_max}|number|label=UA color maximum|>
|>
|>
|>

<|part|render={ht_mode == "Reaction temperature profile"}|class_name=va-card|
## Reaction Kinetics and Heat of Reaction
Pick a reaction to auto-fill its kinetics, or edit the fields directly. The rate
constant is held fixed (isothermal-kinetics approximation; activation energy is
not modelled) and the profile runs until 99% conversion.
<|layout|columns=1 1 1 1 1|
<|{selected_reaction_source}|selector|lov={reaction_source_options}|dropdown|label=Reaction source|on_change=on_reaction_source_change|>

<|{selected_reaction}|selector|lov={selected_reaction_options}|dropdown|label=Reaction|on_change=on_reaction_change|>

<|{rxn_order}|selector|lov={rxn_order_options}|dropdown|label=Order|>

<|{rxn_k}|number|label=Rate constant k|>

<|{rxn_c0}|number|label=C0 (mol/L)|on_change=on_rxn_input_change|>

<|{rxn_dH}|number|label=dH_rxn (kJ/mol)|on_change=on_rxn_input_change|>
|>

<|{rxn_adiabatic_text}|text|mode=markdown|>
|>

<|Compute|button|on_action=on_compute|class_name=compute-btn|>

<|part|render={ht_mode == "Parameter Sweep" and sweep_result_ready}|class_name=va-card|
## U and UA Surfaces
<|layout|columns=1 1|
<|chart|figure={sweep_u_fig}|height=520px|>
<|chart|figure={sweep_ua_fig}|height=520px|>
|>
|>

<|part|render={ht_mode == "Heat / cool vessel" and result_ready}|
<|part|class_name=va-card|
## 3. Core KPIs
<|{kpi_df}|table|width=100%|>

<|Download core KPIs CSV|file_download|content={kpi_csv}|name=heat_transfer_core_kpis.csv|label=Download core KPIs CSV|>
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

<|Download correlation comparison CSV|file_download|content={corr_csv}|name=heat_transfer_correlations.csv|label=Download correlation comparison CSV|>

### Heat transfer medium comparison
<|{htm_compare_df}|table|width=100%|rebuild|>

<|Download medium comparison CSV|file_download|content={htm_compare_csv}|name=heat_transfer_media.csv|label=Download medium comparison CSV|>
|>

<|part|class_name=va-card|
## 8. Summary
<|{summary_df}|table|width=100%|>

<|Download summary CSV|file_download|content={summary_csv}|name=heat_transfer_summary.csv|label=Download summary CSV|>
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

<|Download reaction summary CSV|file_download|content={rxn_summary_csv}|name=heat_transfer_reaction_summary.csv|label=Download reaction summary CSV|>
|>

<|part|render={ht_mode != "Parameter Sweep"}|class_name=va-card|
## Export Report
Generate a PDF capturing the system, resistances, KPIs, and profiles (heat/cool
mode) or the reaction kinetics and temperature/conversion profile (reaction mode).

<|Generate PDF report|button|on_action=on_ht_export_pdf|class_name=compute-btn|>

<|part|render={ht_pdf_ready}|
<|{None}|file_download|on_action=on_ht_pdf_download|label=Download PDF|>
|>
|>
"""

page = Markdown(inject_icons(heat_transfer_md))
