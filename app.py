from __future__ import annotations

from pathlib import Path
import sys

import pandas as pd
import plotly.graph_objects as go

if sys.version_info >= (3, 13):
    raise RuntimeError("Taipy GUI currently requires Python 3.12 or lower for this app. Please run with Python 3.12.")

from taipy.gui import Gui, Markdown, navigate, notify

from heat_transfer_core import (
    FOULING_DEFAULT,
    JACKET_HTC_DEFAULT,
    LINING_CONDUCTIVITY,
    LINING_THICKNESS_DEFAULT,
    NUSSELT_CORRELATIONS,
    WALL_CONDUCTIVITY,
    compute_batch,
    estimate_jacket_area,
    find_best_material_key,
    liquid_height_from_volume,
    load_csvs,
    safe_float,
)

from pages import (
    bourne_protocol,
    fluid_database,
    mixing_sensitivity,
    particle_database,
    reaction_database,
    unit_converter,
    vessel_assessment,
    vessel_comparison,
    vessel_database,
)

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"

reactors_df, fluids_df, htm_db = load_csvs(DATA_DIR)

reactor_options = sorted(reactors_df["reactor_name"].dropna().unique().tolist())
fluid_options = sorted(fluids_df["fluid_name"].dropna().unique().tolist())
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


selected_reactor = reactor_options[0]
selected_fluid = fluid_options[0]
selected_htm = htm_options[0]
nusselt_correlation = nusselt_options[0]

_r = _reactor_row(selected_reactor)
_f = _fluid_row(selected_fluid)

d_tank = safe_float(_r.get("D_tank_m"), 0.1)
d_imp = safe_float(_r.get("D_imp_m"), 0.05)
n_rpm = safe_float(_r.get("N_rpm_max"), 300.0)
np_in = safe_float(_r.get("Np"), 1.27)
v_l = safe_float(_r.get("V_L"), 1.0)
h_max = safe_float(_r.get("H_max_m"), safe_float(_r.get("H_m"), 0.2))
h_liquid = liquid_height_from_volume(v_l, d_tank, h_max)
a_ht = estimate_jacket_area(d_tank, h_liquid, str(_r.get("bottom_dish", "")))

rho = safe_float(_f.get("rho_kg_m3"), 1000.0)
mu = safe_float(_f.get("mu_Pa_s"), 0.001)
cp = safe_float(_f.get("Cp_J_per_kgK"), 4182.0)
k_fluid = safe_float(_f.get("k_W_per_mK"), 0.607)

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

status_message = "Set inputs and click Compute."
kpi_df = pd.DataFrame([{"Metric": "U (W/m2.K)", "Value": "-"}])
corr_df = pd.DataFrame(columns=["Correlation", "Nu", "h_i (W/m2.K)", "U (W/m2.K)", "Time (min)"])
htm_compare_df = pd.DataFrame(columns=["Medium", "h_o (W/m2.K)", "U (W/m2.K)", "Time (min)", "In range"])
summary_df = pd.DataFrame(columns=["Metric", "Value"])
result_ready = False

temp_fig = go.Figure()
temp_fig.update_layout(title="Batch Temperature Profile", xaxis_title="Time (min)", yaxis_title="Temperature (C)")
duty_fig = go.Figure()
duty_fig.update_layout(title="Heat Duty over Time", xaxis_title="Time (min)", yaxis_title="|Q| (W)")


# ---------------------------------------------------------------------------
# Navigation menu
# ---------------------------------------------------------------------------

# Taipy's `menu` is a flat list. Emoji icons are injected via CSS (see root_md)
# because the auto letter-badge mangles emoji, so labels stay plain text here.
menu_options = [
    ("Vessel_Database", "Vessels"),
    ("Fluid_Database", "Fluids"),
    ("Reaction_Database", "Reactions"),
    ("Particle_Database", "Particles"),
    ("Vessel_Assessment", "Vessel Assessment"),
    ("Vessel_Comparison", "Vessel Comparison"),
    ("Bourne_Protocol", "Bourne Protocol"),
    ("Mixing_Sensitivity", "Reaction Sensitivity Protocol"),
    ("Heat_Transfer", "Heat Transfer Tool"),
    ("Unit_Converter", "Unit Converter"),
]


def on_menu_action(state, action, info):
    page = info["args"][0]
    navigate(state, to=page)


def _logo_data_uri() -> str:
    """Return the sidebar logo as a base64 ``data:`` URI (empty string if missing)."""
    import base64

    path = BASE_DIR / "images" / "general" / "logo.png"
    if not path.exists():
        return ""
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


LOGO_DATA_URI = _logo_data_uri()

def _time_factor(unit: str) -> float:
    return {"Seconds": 1.0, "Minutes": 60.0, "Hours": 3600.0}.get(unit, 60.0)


def on_reactor_change(state):
    row = _reactor_row(state.selected_reactor)
    state.d_tank = safe_float(row.get("D_tank_m"), state.d_tank)
    state.d_imp = safe_float(row.get("D_imp_m"), state.d_imp)
    state.n_rpm = safe_float(row.get("N_rpm_max"), state.n_rpm)
    state.np_in = safe_float(row.get("Np"), state.np_in)
    state.v_l = safe_float(row.get("V_L"), state.v_l)
    h_max_val = safe_float(row.get("H_max_m"), safe_float(row.get("H_m"), 0.2))
    h = liquid_height_from_volume(state.v_l, state.d_tank, h_max_val)
    state.a_ht = estimate_jacket_area(state.d_tank, h, str(row.get("bottom_dish", "")))
    shell = find_best_material_key(str(row.get("shell_material", "stainless steel")), wall_options)
    state.wall_material = shell
    state.wall_k = WALL_CONDUCTIVITY.get(shell, 16.0)
    state.wall_thickness_mm = safe_float(row.get("wall_thickness_mm"), state.wall_thickness_mm)
    notify(state, "I", "Reactor defaults loaded.")


def on_fluid_change(state):
    row = _fluid_row(state.selected_fluid)
    state.rho = safe_float(row.get("rho_kg_m3"), state.rho)
    state.mu = safe_float(row.get("mu_Pa_s"), state.mu)
    state.cp = safe_float(row.get("Cp_J_per_kgK"), state.cp)
    state.k_fluid = safe_float(row.get("k_W_per_mK"), state.k_fluid)
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


def on_compute(state):
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

    analytical_txt = "Infinity" if not pd.notna(result.time_analytical_s) or not np_is_finite(result.time_analytical_s) else f"{result.time_analytical_s/60.0:.2f} min"
    state.status_message = (
        f"Computed successfully. U = {result.u:.1f} W/(m2.K), "
        f"simulated time (const jacket) = {result.time_const_jacket_s/60.0:.2f} min, "
        f"analytical = {analytical_txt}."
    )
    state.result_ready = True
    notify(state, "S", "Heat-transfer results computed.")


def np_abs(arr):
    import numpy as np

    return np.abs(arr)


def np_is_finite(value: float) -> bool:
    import numpy as np

    return np.isfinite(value)


heat_transfer_md = """
# Heat Transfer Tool

<|{status_message}|text|>

## 1) Reactor and Fluid Selection
<|layout|columns=1 1 1 1|
<|{selected_reactor}|selector|lov={reactor_options}|dropdown|label=Reactor|on_change=on_reactor_change|>

<|{selected_fluid}|selector|lov={fluid_options}|dropdown|label=Process fluid|on_change=on_fluid_change|>

<|{selected_htm}|selector|lov={htm_options}|dropdown|label=Heat transfer medium|on_change=on_htm_change|>

<|{nusselt_correlation}|selector|lov={nusselt_options}|dropdown|label=Nusselt correlation|>
|>

## 2) Geometry, Materials, and Operating Inputs
<|layout|columns=1 1 1 1|
<|{d_tank}|number|label=D_tank (m)|>

<|{d_imp}|number|label=D_imp (m)|>

<|{n_rpm}|number|label=N (RPM)|>

<|{np_in}|number|label=Np|>
|>

<|layout|columns=1 1 1 1|
<|{v_l}|number|label=Liquid volume (L)|>

<|{a_ht}|number|label=Heat-transfer area A_ht (m2)|>

<|{fouling}|number|label=Fouling resistance (m2.K/W)|>

<|{mu_wall}|number|label=mu at wall (Pa.s)|>
|>

<|layout|columns=1 1 1 1|
<|{wall_material}|selector|lov={wall_options}|dropdown|label=Wall material|>

<|{wall_k}|number|label=Wall k (W/m.K)|>

<|{wall_thickness_mm}|number|label=Wall thickness (mm)|>

<|{lining_material}|selector|lov={lining_options}|dropdown|label=Lining|on_change=on_lining_change|>
|>

<|layout|columns=1 1 1 1|
<|{lining_k}|number|label=Lining k (W/m.K)|>

<|{lining_thickness_mm}|number|label=Lining thickness (mm)|>

<|{rho}|number|label=rho (kg/m3)|>

<|{mu}|number|label=mu (Pa.s)|>
|>

<|layout|columns=1 1 1 1|
<|{cp}|number|label=Cp (J/kg.K)|>

<|{k_fluid}|number|label=k fluid (W/m.K)|>

<|{v_jacket}|number|label=Jacket velocity (m/s)|>

<|{d_hyd_jacket}|number|label=Jacket hydraulic diameter (m)|>
|>

<|layout|columns=1 1 1 1|
<|{m_dot_jacket}|number|label=Jacket mass flow (kg/s)|>

<|{cp_jacket}|number|label=Jacket Cp (J/kg.K)|>

<|{q_rxn}|number|label=Additional heat input Q_rxn (W)|>

<|{include_agitator}|toggle|label=Include agitator heat|>
|>

<|layout|columns=1 1 1 1|
<|{t_start}|number|label=T_start (C)|>

<|{t_target}|number|label=T_target (C)|>

<|{t_jacket}|number|label=T_jacket inlet (C)|>

<|{time_unit}|selector|lov=Seconds;Minutes;Hours|dropdown|label=Plot time unit|>
|>

<|Compute Heat Transfer|button|on_action=on_compute|class_name=compute-btn|>

## 3) Core KPIs
<|{kpi_df}|table|width=100%|>

## 4) Temperature and Heat-Duty Profiles
<|chart|figure={temp_fig}|height=460px|>
<|chart|figure={duty_fig}|height=380px|>

## 5) Correlation and HTM Comparisons
### Nusselt correlation comparison
<|{corr_df}|table|width=100%|>

### Heat transfer medium comparison
<|{htm_compare_df}|table|width=100%|>

## 6) Summary
<|{summary_df}|table|width=100%|>
"""


root_md = """
<style>
/* Replace the native hamburger (triple-bar) toggle icon of the Taipy menu
   with the app logo. The first list item in the menu Drawer is the open/close
   toggle; its avatar holds the MenuIcon SVG we hide and swap for the logo. */
.htt-menu .MuiList-root .MuiButtonBase-root:first-of-type .MuiAvatar-root {
    background-color: #ffffff !important;
    background-image: url("__LOGO_URI__");
    background-size: contain;
    background-repeat: no-repeat;
    background-position: center;
    width: 44px !important;
    height: 44px !important;
    border-radius: 6px;
}
.htt-menu .MuiList-root .MuiButtonBase-root:first-of-type .MuiAvatar-root svg {
    display: none !important;
}

/* The menu draws a round icon badge per item whose auto-generated letter mangles
   emoji into "?". Blank out that letter and inject a per-page emoji via ::after,
   so it shows in both the collapsed (icon-only) and expanded menu states. The
   first item's avatar is the logo (styled above) and is left untouched. */
.htt-menu .MuiList-root .MuiButtonBase-root:not(:first-of-type) .MuiAvatar-root {
    color: transparent !important;
    font-size: 0 !important;
    background-color: transparent !important;
}
.htt-menu .MuiList-root .MuiButtonBase-root:not(:first-of-type) .MuiAvatar-root::after {
    color: initial;
    font-size: 1.3rem;
    line-height: 1;
}
/* Icon order follows the `menu_options` list: nth-of-type(N) = menu position
   N-1 (position 1 is the logo/toggle). Update these if you reorder the menu.
   Order: 2=Vessels, 3=Fluids, 4=Reactions, 5=Particles, 6=Vessel Assessment,
   7=Vessel Comparison, 8=Bourne Protocol, 9=Reaction Sensitivity, 10=Heat Transfer,
   11=Unit Converter. */
.htt-menu .MuiList-root .MuiButtonBase-root:nth-of-type(2) .MuiAvatar-root::after {
    content: "⚗️";
}
.htt-menu .MuiList-root .MuiButtonBase-root:nth-of-type(3) .MuiAvatar-root::after {
    content: "💧";
}
.htt-menu .MuiList-root .MuiButtonBase-root:nth-of-type(4) .MuiAvatar-root::after {
    content: "🧪";
}
.htt-menu .MuiList-root .MuiButtonBase-root:nth-of-type(5) .MuiAvatar-root::after {
    content: "🟤";
}
.htt-menu .MuiList-root .MuiButtonBase-root:nth-of-type(6) .MuiAvatar-root::after {
    content: "🌀";
}
.htt-menu .MuiList-root .MuiButtonBase-root:nth-of-type(7) .MuiAvatar-root::after {
    content: "⚖️";
}
.htt-menu .MuiList-root .MuiButtonBase-root:nth-of-type(8) .MuiAvatar-root::after {
    content: "🅱️";
}
.htt-menu .MuiList-root .MuiButtonBase-root:nth-of-type(9) .MuiAvatar-root::after {
    content: "🧭";
}
.htt-menu .MuiList-root .MuiButtonBase-root:nth-of-type(10) .MuiAvatar-root::after {
    content: "🔥";
}
.htt-menu .MuiList-root .MuiButtonBase-root:nth-of-type(11) .MuiAvatar-root::after {
    content: "🔄";
}

/* Hide the "Mode" text label on the theme toggle; the sun/moon icons suffice. */
.theme-toggle .MuiTypography-root {
    display: none !important;
}

/* ---- Takeda corporate palette (red / gray / white) --------------------- */
/* Section headings in Takeda red; sub-headings in a neutral gray. */
h1, h2 {
    color: #E1251B;
}
h3, h4 {
    color: #4A4A4A;
}
/* Default (non-tagged) buttons use Takeda red so all actions read as on-brand. */
.taipy-button .MuiButton-root,
button.taipy-button {
    background-color: #E1251B !important;
    color: #ffffff !important;
}
.taipy-button .MuiButton-root:hover,
button.taipy-button:hover {
    background-color: #A81A12 !important;
}
/* Text/link accents and focused input outlines in Takeda red. */
a, .MuiLink-root {
    color: #E1251B;
}
.MuiOutlinedInput-root.Mui-focused .MuiOutlinedInput-notchedOutline {
    border-color: #E1251B !important;
}
.MuiInputLabel-root.Mui-focused {
    color: #E1251B !important;
}
/* Highlight the selected sidebar-menu item with a red accent. */
.htt-menu .MuiList-root .Mui-selected {
    background-color: rgba(225, 37, 27, 0.12) !important;
    border-left: 3px solid #E1251B;
}
/* Table header row: subtle Takeda-red tint for a corporate feel. */
.taipy-table .MuiTableCell-head {
    background-color: #FBEBEA !important;
    color: #4A4A4A !important;
    font-weight: 600;
}

/* ---- Dark-mode adjustments (Taipy adds `.taipy-dark` on the root) -------
   Keep the Takeda red accents but swap light surfaces/text for dark-legible
   equivalents so cards and headings don't jar against a dark background. */
.taipy-dark h1, .taipy-dark h2 {
    color: #FF5247;
}
.taipy-dark h3, .taipy-dark h4 {
    color: #C7CBD1;
}
.taipy-dark .va-card {
    background: rgba(255, 255, 255, 0.04);
    border-color: rgba(255, 255, 255, 0.14);
    border-left-color: #E1251B;
}
.taipy-dark .scheme-box {
    background: rgba(225, 37, 27, 0.16);
}
.taipy-dark .result-box {
    background: rgba(255, 255, 255, 0.06);
    border-color: rgba(255, 255, 255, 0.14);
    border-left-color: #9AA1A9;
}
.taipy-dark .taipy-table .MuiTableCell-head {
    background-color: rgba(225, 37, 27, 0.24) !important;
    color: #F0F0F0 !important;
}
.taipy-dark a,
.taipy-dark .MuiLink-root {
    color: #FF5247;
}
.taipy-dark .htt-menu .MuiList-root .Mui-selected {
    background-color: rgba(225, 37, 27, 0.28) !important;
}

/* Make the primary action button stand out in Takeda red. */
.compute-btn .MuiButton-root,
button.compute-btn {
    background-color: #E1251B !important;
    color: #ffffff !important;
}
.compute-btn .MuiButton-root:hover,
button.compute-btn:hover {
    background-color: #A81A12 !important;
}

/* Neutral gray variant shown after a result has been computed (results fresh). */
.compute-btn-ok .MuiButton-root,
button.compute-btn-ok {
    background-color: #5C6670 !important;
    color: #ffffff !important;
}
.compute-btn-ok .MuiButton-root:hover,
button.compute-btn-ok:hover {
    background-color: #3E464E !important;
}

/* Grouped "card" containers used to visually separate page sections
   (e.g. the Vessel Assessment page). White card with a Takeda-red left accent. */
.va-card {
    border: 1px solid #E6E6E6;
    border-left: 3px solid #E1251B;
    border-radius: 8px;
    padding: 2px 20px 16px;
    margin: 0 0 20px 0;
    background: #ffffff;
}

/* Reaction-scheme highlight box. */
.scheme-box {
    display: block;
    background: rgba(225, 37, 27, 0.08);
    border-left: 4px solid #E1251B;
    padding: 10px 14px;
    border-radius: 6px;
    font-family: monospace;
    margin: 8px 0 4px;
}

/* Result callout: wraps a step's computed assessment so the outcome stands
   apart from the input controls and the white card background. */
.result-box {
    display: block;
    background: #F4F5F6;
    border: 1px solid #E1E4E8;
    border-left: 4px solid #5C6670;
    border-radius: 6px;
    padding: 4px 16px 8px;
    margin: 12px 0 4px;
}

/* On/off toggles: neutral gray when OFF (first button) is selected, Takeda red
   when ON (last button) is selected. Applies to class_name=onoff-toggle. */
.onoff-toggle .MuiToggleButton-root:first-of-type.Mui-selected {
    background-color: #6E6E6E !important;
    color: #ffffff !important;
}
.onoff-toggle .MuiToggleButton-root:last-of-type.Mui-selected {
    background-color: #E1251B !important;
    color: #ffffff !important;
}

/* Operating-envelope chart height, keyed to the number of subplot rows.
   The Taipy chart `height` property is not reactive after first render, so the
   height is driven by a dynamic class_name instead (!important overrides the
   inline height). Heights ≈ rows*300 + title/legend allowance. */
.env-rows-1 { height: 520px !important; }
.env-rows-2 { height: 880px !important; }
.env-rows-3 { height: 1240px !important; }
.env-rows-4 { height: 1600px !important; }
.env-rows-5 { height: 1960px !important; }
.env-rows-6 { height: 2320px !important; }
.env-rows-7 { height: 2680px !important; }
.env-rows-8 { height: 3040px !important; }

/* Editable-table cell dropdowns (MUI Autocomplete) inherit the narrow column
   width, clipping long option text. Let the popup size to its content instead. */
.MuiAutocomplete-popper {
    width: max-content !important;
    min-width: 180px !important;
    max-width: 460px !important;
}
.MuiAutocomplete-popper .MuiAutocomplete-option {
    white-space: nowrap;
}

/* Global search box shown above each database table. */
.db-search {
    max-width: 380px;
    margin: 4px 0 12px 0;
}

/* Neat, level form controls: inside layout grids every input/selector fills its
   column and is top-aligned, and all number/text/selector fields share one
   height so boxes line up cleanly regardless of label length. Tight, uniform
   gaps keep related inputs grouped without excess white space. */
.taipy-layout {
    align-items: start;
    row-gap: 8px;
    column-gap: 12px;
    margin-top: 4px;
    margin-bottom: 4px;
}
.taipy-layout .taipy-number,
.taipy-layout .taipy-selector,
.taipy-layout .taipy-input,
.taipy-layout .taipy-date {
    width: 100%;
}
.taipy-number .MuiInputBase-root,
.taipy-input .MuiInputBase-root,
.taipy-selector .MuiInputBase-root {
    min-height: 48px;
}
/* Trim the default dense-form margins so stacked fields sit closer together. */
.taipy-number.MuiFormControl-marginDense,
.taipy-input.MuiFormControl-marginDense,
.taipy-selector.MuiFormControl-marginDense {
    margin-top: 4px;
    margin-bottom: 4px;
}
/* Add/entry forms: cap the grid width so inputs stay grouped and compact
   instead of stretching across the full page on wide screens. */
.form-grid {
    max-width: 780px;
}

/* Let table columns size to their content instead of wrapping text. Wide tables
   scroll horizontally within their container rather than cramming columns and
   wrapping cell/header text unnecessarily. */
.taipy-table .MuiTableContainer-root {
    overflow-x: auto;
}
.taipy-table .MuiTableCell-root {
    white-space: nowrap;
}
</style>

<|menu|lov={menu_options}|on_action=on_menu_action|label=Mixing Lab|width=260px|class_name=htt-menu|>

<|toggle|theme|class_name=theme-toggle|>

<|content|>
"""

root_md = root_md.replace("__LOGO_URI__", LOGO_DATA_URI)


pages = {
    "/": root_md,
    "Vessel_Database": vessel_database.page,
    "Fluid_Database": fluid_database.page,
    "Reaction_Database": reaction_database.page,
    "Particle_Database": particle_database.page,
    "Vessel_Assessment": vessel_assessment.page,
    "Vessel_Comparison": vessel_comparison.page,
    "Bourne_Protocol": bourne_protocol.page,
    "Mixing_Sensitivity": mixing_sensitivity.page,
    "Heat_Transfer": heat_transfer_md,
    "Unit_Converter": unit_converter.page,
}

# The `part` element's `content` property needs a content provider for the bound
# type. Register one for `str` so the vessel viewer HTML is served as-is.
Gui.register_content_provider(str, lambda html: html)

# Takeda corporate palette applied to the MUI theme so every primary-coloured
# component (buttons, toggles, checkboxes, focused inputs) reads as Takeda red.
TAKEDA_THEME = {
    "palette": {
        "primary": {"main": "#E1251B"},
        "secondary": {"main": "#5C6670"},
    },
}

if __name__ == "__main__":
    Gui(pages=pages).run(title="Mixing Lab V2", use_reloader=True, port="auto",
                         dark_mode=False, theme=TAKEDA_THEME)

