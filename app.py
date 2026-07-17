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
from vessel_media import build_vessel_viewer_html, media_caption

from pages import unit_converter

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"

reactors_df, fluids_df, htm_db = load_csvs(DATA_DIR)

reactions_df = pd.read_csv(DATA_DIR / "reactions.csv")
particles_df = pd.read_csv(DATA_DIR / "particles.csv")

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
# Friendly column labels for the library tables
# ---------------------------------------------------------------------------
# Maps raw CSV column names to display names in "Name [unit]" format. Any column
# not listed here falls back to its raw name. Adjust freely if a guess is wrong.
COLUMN_LABELS: dict[str, str] = {
    # --- Reactors / Vessels ---
    "reactor_id": "Reactor ID",
    "reactor_name": "Reactor Name",
    "owner": "Owner",
    "tag": "Tag",
    "location": "Location",
    "manufacturer": "Manufacturer",
    "manufacturer_model": "Manufacturer Model",
    "type": "Type",
    "scale": "Scale",
    "D_tank_m": "Tank Diameter [m]",
    "H_m": "Tank Height [m]",
    "H_max_m": "Max Liquid Height [m]",
    "D_imp_m": "Impeller Diameter [m]",
    "impeller_type": "Impeller Type",
    "Np": "Power Number",
    "Nq": "Flow Number",
    "N_rpm_min": "Min Speed [rpm]",
    "N_rpm_max": "Max Speed [rpm]",
    "N_rps": "Speed [rps]",
    "V_L_min": "Min Volume [L]",
    "V_L_max": "Max Volume [L]",
    "V_L": "Working Volume [L]",
    "shell_material": "Shell Material",
    "lining": "Lining",
    "lining_material": "Lining Material",
    "baffles": "Baffles",
    "bottom_dish": "Bottom Dish",
    "top_dish": "Top Dish",
    "impeller_count": "Impeller Count",
    "imp1_clearance_m": "Impeller 1 Clearance [m]",
    "imp1_height_m": "Impeller 1 Height [m]",
    "D_imp2_m": "Impeller 2 Diameter [m]",
    "Np2": "Power Number 2",
    "imp2_clearance_m": "Impeller 2 Clearance [m]",
    "imp2_height_m": "Impeller 2 Height [m]",
    "D_imp3_m": "Impeller 3 Diameter [m]",
    "Np3": "Power Number 3",
    "imp3_clearance_m": "Impeller 3 Clearance [m]",
    "imp3_height_m": "Impeller 3 Height [m]",
    "Zwietering_S": "Zwietering S Constant",
    "GMB_z": "GMB z",
    "wall_thickness_mm": "Wall Thickness [mm]",
    "OD_m": "Outer Diameter [m]",
    "knuckle_radius_m": "Knuckle Radius [m]",
    "instrumentation": "Instrumentation",
    "discharge_location": "Discharge Location",
    "insulated": "Insulated",
    "gas_addition": "Gas Addition",
    "gas_feed_control": "Gas Feed Control",
    "no_ports": "Number of Ports",
    "motor_power_kW": "Motor Power [kW]",
    "aux_units": "Auxiliary Units",
    "cip": "CIP",
    "heating_cooling": "Heating / Cooling",
    "heat_transfer_medium": "Heat Transfer Medium",
    "heat_exchanger": "Heat Exchanger",
    "T_max_C": "Max Temperature [°C]",
    "P_max_atm": "Max Pressure [atm]",
    "impeller_type2": "Impeller Type 2",
    "impeller_type3": "Impeller Type 3",
    "impeller_flow": "Impeller Flow",
    "impeller_model": "Impeller Model",
    "impeller_flow2": "Impeller Flow 2",
    "impeller_model2": "Impeller Model 2",
    "impeller_flow3": "Impeller Flow 3",
    "impeller_model3": "Impeller Model 3",
    "probes": "Probes",
    "search_name": "Search Name",
    # --- Fluids ---
    "fluid_name": "Fluid Name",
    "rho_kg_m3": "Density [kg/m³]",
    "mu_Pa_s": "Viscosity [Pa·s]",
    "D_mol_m2_s": "Molecular Diffusivity [m²/s]",
    "surface_tension_N_m": "Surface Tension [N/m]",
    "Cp_J_per_kgK": "Heat Capacity [J/kg·K]",
    "k_W_per_mK": "Thermal Conductivity [W/m·K]",
    "hsp_d": "Hansen δD [MPa^0.5]",
    "hsp_p": "Hansen δP [MPa^0.5]",
    "hsp_h": "Hansen δH [MPa^0.5]",
    # --- Reactions ---
    "reaction_name": "Reaction Name",
    "order": "Reaction Order",
    "k_value": "Rate Constant",
    "k_units": "Rate Constant Units",
    "C0_mol_L": "Initial Concentration [mol/L]",
    "t_rxn_s": "Reaction Time [s]",
    "T_C": "Temperature [°C]",
    "solvent": "Solvent",
    "delta_H_kJ_mol": "Heat of Reaction [kJ/mol]",
    "reaction_scheme": "Reaction Scheme",
    # --- Particles ---
    "particle_name": "Particle Name",
    "rho_p_kg_m3": "Particle Density [kg/m³]",
    "d10_um": "D10 [µm]",
    "d50_um": "D50 [µm]",
    "d90_um": "D90 [µm]",
    "shape_description": "Shape Description",
    "shape_factor": "Shape Factor",
    # --- Shared ---
    "notes": "Notes",
}


def _friendly_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Return a copy of ``df`` with columns renamed to friendly display labels."""
    return df.rename(columns={c: COLUMN_LABELS.get(c, c) for c in df.columns})


def _friendly(col: str) -> str:
    """Friendly label for a single column name (raw name if unmapped)."""
    return COLUMN_LABELS.get(col, col)


# ---------------------------------------------------------------------------
# Vessel (reactor) database view
# ---------------------------------------------------------------------------

VESSEL_DISPLAY_COLS = [
    "reactor_name", "owner", "manufacturer", "type", "scale",
    "D_tank_m", "H_m", "D_imp_m", "impeller_type", "Np",
    "N_rpm_min", "N_rpm_max", "V_L_min", "V_L_max", "V_L",
    "shell_material", "lining_material", "bottom_dish",
    "wall_thickness_mm", "T_max_C", "P_max_atm",
    "heat_transfer_medium", "notes",
]


def _vessel_table(df: pd.DataFrame) -> pd.DataFrame:
    cols = [c for c in VESSEL_DISPLAY_COLS if c in df.columns]
    return df[cols].copy()


vessel_full_df = _vessel_table(reactors_df)
vessel_df = _friendly_columns(vessel_full_df.copy())
vessel_search = ""
vessel_count_msg = f"{len(vessel_df)} vessels in database."

selected_vessel = reactor_options[0]
vessel_detail_df = pd.DataFrame(columns=["Property", "Value"])


def _reactor_id_for(reactor_name: str) -> str:
    row = _reactor_row(reactor_name)
    if row.empty:
        return ""
    return str(row.get("reactor_id", "") or "")


def _build_vessel_detail(reactor_name: str) -> pd.DataFrame:
    row = _reactor_row(reactor_name)
    if row.empty:
        return pd.DataFrame(columns=["Property", "Value"])
    records = []
    for col in reactors_df.columns:
        val = row.get(col)
        if pd.isna(val) or str(val).strip() == "":
            continue
        records.append({"Property": _friendly(col), "Value": str(val)})
    return pd.DataFrame(records)


vessel_detail_df = _build_vessel_detail(selected_vessel)
vessel_viewer_html = build_vessel_viewer_html(_reactor_id_for(selected_vessel))
vessel_media_caption = media_caption(_reactor_id_for(selected_vessel))


def on_vessel_search(state):
    query = (state.vessel_search or "").strip().lower()
    if not query:
        filtered = vessel_full_df.copy()
    else:
        mask = vessel_full_df.apply(
            lambda r: r.astype(str).str.lower().str.contains(query, na=False).any(), axis=1
        )
        filtered = vessel_full_df[mask].copy()
    state.vessel_df = _friendly_columns(filtered)
    state.vessel_count_msg = f"{len(filtered)} of {len(vessel_full_df)} vessels match '{state.vessel_search}'." if query else f"{len(vessel_full_df)} vessels in database."


def on_vessel_select(state):
    state.vessel_detail_df = _build_vessel_detail(state.selected_vessel)
    rid = _reactor_id_for(state.selected_vessel)
    state.vessel_viewer_html = build_vessel_viewer_html(rid)
    state.vessel_media_caption = media_caption(rid)


# ---------------------------------------------------------------------------
# Generic library pages (Fluids, Reactions, Particles)
# ---------------------------------------------------------------------------
# Taipy's `menu` renders a flat list, so these library pages reuse the same
# search + table + detail pattern as the Vessel Library. Each library registers
# its own module-level state variables and handlers via ``_make_library`` so the
# Taipy GUI can bind them by name.


def _build_generic_detail(df: pd.DataFrame, name_col: str, name: str) -> pd.DataFrame:
    """Return a two-column Property/Value table for the selected row."""
    if not name:
        return pd.DataFrame(columns=["Property", "Value"])
    match = df[df[name_col].astype(str) == str(name)]
    if match.empty:
        return pd.DataFrame(columns=["Property", "Value"])
    row = match.iloc[0]
    records = []
    for col in df.columns:
        val = row.get(col)
        if pd.isna(val) or str(val).strip() == "":
            continue
        records.append({"Property": _friendly(col), "Value": str(val)})
    return pd.DataFrame(records)


def _make_library(key: str, df: pd.DataFrame, name_col: str, noun: str) -> list:
    """Register state vars and handlers for a browsable library page.

    Creates module globals ``{key}_full_df``, ``{key}_df``, ``{key}_search``,
    ``{key}_count_msg``, ``{key}_options``, ``{key}_selected``,
    ``{key}_detail_df`` and handlers ``on_{key}_search`` / ``on_{key}_select``.
    """
    full = df.copy()
    options = sorted(full[name_col].dropna().astype(str).unique().tolist())
    first = options[0] if options else ""

    g = globals()
    g[f"{key}_full_df"] = full
    g[f"{key}_df"] = _friendly_columns(full.copy())
    g[f"{key}_search"] = ""
    g[f"{key}_count_msg"] = f"{len(full)} {noun} in database."
    g[f"{key}_options"] = options
    g[f"{key}_selected"] = first
    g[f"{key}_detail_df"] = _build_generic_detail(full, name_col, first)

    def on_search(state, _key=key, _full=full, _noun=noun):
        query = (getattr(state, f"{_key}_search") or "").strip().lower()
        if not query:
            filtered = _full.copy()
        else:
            mask = _full.apply(
                lambda r: r.astype(str).str.lower().str.contains(query, na=False).any(), axis=1
            )
            filtered = _full[mask].copy()
        setattr(state, f"{_key}_df", _friendly_columns(filtered))
        if query:
            msg = f"{len(filtered)} of {len(_full)} {_noun} match '{getattr(state, f'{_key}_search')}'."
        else:
            msg = f"{len(_full)} {_noun} in database."
        setattr(state, f"{_key}_count_msg", msg)

    def on_select(state, _key=key, _full=full, _name_col=name_col):
        setattr(
            state,
            f"{_key}_detail_df",
            _build_generic_detail(_full, _name_col, getattr(state, f"{_key}_selected")),
        )

    g[f"on_{key}_search"] = on_search
    g[f"on_{key}_select"] = on_select
    return options


_make_library("fluidlib", fluids_df, "fluid_name", "fluids")
_make_library("reactionlib", reactions_df, "reaction_name", "reactions")
_make_library("particlelib", particles_df, "particle_name", "particles")


def _library_md(key: str, title: str, search_hint: str, intro: str) -> str:
    """Build the Taipy markdown for a generic library page."""
    tmpl = """
# @TITLE@

@INTRO@

<|{@KEY@_count_msg}|text|>

<|{@KEY@_search}|input|label=@HINT@|on_change=on_@KEY@_search|change_delay=300|>

<|@TITLE@|expandable|expanded=False|
<|{@KEY@_df}|table|width=100%|filter|page_size=15|>
|>

## Explore
<|{@KEY@_selected}|selector|lov={@KEY@_options}|dropdown|label=Select entry|on_change=on_@KEY@_select|>

<|Properties|expandable|expanded=False|
<|{@KEY@_detail_df}|table|width=100%|show_all|>
|>
"""
    return (
        tmpl.replace("@TITLE@", title)
        .replace("@INTRO@", intro)
        .replace("@HINT@", search_hint)
        .replace("@KEY@", key)
    )


fluid_library_md = _library_md(
    "fluidlib", "Fluid Library",
    "Search fluids (name, notes, ...)",
    "Browse the same fluid/solvent properties used in the Mixing Lab app.",
)
reaction_library_md = _library_md(
    "reactionlib", "Reaction Library",
    "Search reactions (name, type, solvent, ...)",
    "Browse the reaction kinetics database from the Mixing Lab app.",
)
particle_library_md = _library_md(
    "particlelib", "Particle Library",
    "Search particles (name, shape, notes, ...)",
    "Browse the particle properties database from the Mixing Lab app.",
)


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


vessel_database_md = """
# Vessel Library

Browse the same vessel geometries used in the Mixing Lab app.

<|{vessel_count_msg}|text|>

<|{vessel_search}|input|label=Search vessels (name, owner, material, ...)|on_change=on_vessel_search|change_delay=300|>

<|Vessel Library|expandable|expanded=False|
<|{vessel_df}|table|width=100%|filter|page_size=15|>
|>

## Explore Vessels
<|{selected_vessel}|selector|lov={reactor_options}|dropdown|label=Select vessel|on_change=on_vessel_select|>

<|Vessel properties|expandable|expanded=False|
<|{vessel_detail_df}|table|width=100%|show_all|>
|>

<|{vessel_media_caption}|text|>

<|part|content={vessel_viewer_html}|height=380px|>
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
   Order: 2=Vessels, 3=Fluids, 4=Reactions, 5=Particles, 6=Heat Transfer,
   7=Unit Converter. */
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
    content: "🔥";
}
.htt-menu .MuiList-root .MuiButtonBase-root:nth-of-type(7) .MuiAvatar-root::after {
    content: "🔄";
}

/* Hide the "Mode" text label on the theme toggle; the sun/moon icons suffice. */
.theme-toggle .MuiTypography-root {
    display: none !important;
}

/* Make the Compute Heat Transfer button stand out. */
.compute-btn .MuiButton-root,
button.compute-btn {
    background-color: #d32f2f !important;
    color: #ffffff !important;
}
.compute-btn .MuiButton-root:hover,
button.compute-btn:hover {
    background-color: #b71c1c !important;
}
</style>

<|menu|lov={menu_options}|on_action=on_menu_action|label=Mixing Lab|width=260px|class_name=htt-menu|>

<|toggle|theme|class_name=theme-toggle|>

<|content|>
"""

root_md = root_md.replace("__LOGO_URI__", LOGO_DATA_URI)


pages = {
    "/": root_md,
    "Vessel_Database": vessel_database_md,
    "Fluid_Database": fluid_library_md,
    "Reaction_Database": reaction_library_md,
    "Particle_Database": particle_library_md,
    "Heat_Transfer": heat_transfer_md,
    "Unit_Converter": unit_converter.page,
}

# The `part` element's `content` property needs a content provider for the bound
# type. Register one for `str` so the vessel viewer HTML is served as-is.
Gui.register_content_provider(str, lambda html: html)

if __name__ == "__main__":
    Gui(pages=pages).run(title="Mixing Lab V2", use_reloader=True, port="auto", dark_mode=False)

