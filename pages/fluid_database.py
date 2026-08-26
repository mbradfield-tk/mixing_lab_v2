"""Fluid Database page (Taipy).

Ported from the Streamlit ``3_Fluid_Database.py`` page. Combines the built-in
**solvent library** (temperature-dependent literature correlations, 27 solvents)
with user-managed **custom fluids** (fixed properties, persisted to
``data/fluids.csv``). Sub-views are switched with a toggle acting as tabs:

* Solvent Library     — reference table at 25 °C + custom fluids table
* Solvent Properties  — properties at any T / P, with 6-panel property curves
* Custom Fluids       — full CRUD editable table + add form
* Blend               — mix solvents/custom fluids with literature mixing rules
* Import / Export     — CSV round-trip of the custom fluids

The Streamlit blend "SM ratio" and "dissolved starting material" sub-modes are
not yet ported (see project notes); the core Volume/Mass blend with miscibility
screening is implemented.
"""
from __future__ import annotations

from itertools import combinations
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from taipy.gui import Markdown, notify

from utils.menu_icons import inject_icons
from pages import _db_common as db
from utils.solvent_properties import (
    SOLVENT_DB,
    boiling_point_at_pressure,
    density,
    diffusivity,
    get_properties,
    is_known_solvent,
    list_solvents,
    solvent_info_table,
    solvent_miscibility,
    specific_heat,
    surface_tension,
    thermal_conductivity,
    viscosity,
)
from utils.validation import TEMP_MIN_C, TEMP_MAX_C

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
FLUID_CSV = DATA_DIR / "fluids.csv"

COLUMNS = [
    "fluid_name", "rho_kg_m3", "mu_Pa_s", "D_mol_m2_s", "surface_tension_N_m",
    "notes", "Cp_J_per_kgK", "k_W_per_mK", "hsp_d", "hsp_p", "hsp_h",
]

# ---------------------------------------------------------------------------
# Sub-view tabs
# ---------------------------------------------------------------------------
fluid_tab_options = [
    "Solvent Library", "Solvent Properties", "Custom Fluids", "Blend", "Import / Export",
]
fluid_tab = "Solvent Library"

# ---------------------------------------------------------------------------
# Solvent library (built-in, read-only)
# ---------------------------------------------------------------------------
solvent_library_df = pd.DataFrame(solvent_info_table())
solvent_options = list_solvents()
solvent_search = ""
solvent_library_view_df = solvent_library_df

# ---------------------------------------------------------------------------
# Custom fluids (editable, persisted)
# ---------------------------------------------------------------------------
fluid_df = db.load_csv(FLUID_CSV, COLUMNS)
fluid_search = ""
fluid_view_df = fluid_df
fluid_export = db.csv_bytes(fluid_df)
fluid_msg = f"{len(fluid_df)} custom fluids (plus {len(solvent_options)} built-in solvents)."

# Add-form fields
flu_new_name = ""
flu_new_rho = 997.0
flu_new_mu = 0.00089
flu_new_D = 2.3e-9
flu_new_sigma = 0.072
flu_new_Cp = 4182.0
flu_new_k = 0.607
flu_new_hd = 0.0
flu_new_hp = 0.0
flu_new_hh = 0.0
flu_new_notes = ""

fluid_upload = ""

# ---------------------------------------------------------------------------
# Solvent Properties (T) view
# ---------------------------------------------------------------------------
solvent_selected = "Water" if "Water" in solvent_options else solvent_options[0]
solvent_P = 1.0
solvent_T = 25.0
solvent_props_df = pd.DataFrame(columns=["Property", "Value", "Units"])
solvent_range_msg = ""
solvent_prop_fig = go.Figure()

# ---------------------------------------------------------------------------
# Blend view
# ---------------------------------------------------------------------------
blend_available = sorted(SOLVENT_DB.keys())
blend_selected: list[str] = []
blend_basis = "Volume"
blend_basis_options = ["Volume", "Mass"]
blend_T = 25.0
blend_input_df = pd.DataFrame(columns=["Component", "Amount"])
blend_result_df = pd.DataFrame(columns=["Component", "Vol %", "Mass %", "ρ (kg/m³)", "μ (Pa·s)"])
blend_misc_df = pd.DataFrame(columns=["Pair", "Assessment", "R_a (MPa½)", "Source"])
blend_status = "Select two or more components and enter amounts, then compute."


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _refresh_available() -> list[str]:
    custom = fluid_df["fluid_name"].dropna().astype(str).tolist() if not fluid_df.empty else []
    return sorted(SOLVENT_DB.keys()) + custom


blend_available = _refresh_available()


def _persist(state) -> None:
    db.save_csv(state.fluid_df, FLUID_CSV)
    state.fluid_export = db.csv_bytes(state.fluid_df)
    state.fluid_msg = f"{len(state.fluid_df)} custom fluids (plus {len(solvent_options)} built-in solvents)."
    custom = state.fluid_df["fluid_name"].dropna().astype(str).tolist() if not state.fluid_df.empty else []
    state.blend_available = sorted(SOLVENT_DB.keys()) + custom
    state.fluid_view_df = _apply_fluid_search(state)


def _apply_fluid_search(state) -> pd.DataFrame:
    """Full custom-fluids frame, or a filtered (read-only) view while searching."""
    query = (state.fluid_search or "").strip()
    return db.filter_rows(state.fluid_df, query) if query else state.fluid_df


def on_fluid_search(state):
    state.fluid_view_df = _apply_fluid_search(state)


def _fluid_searching(state) -> bool:
    if (state.fluid_search or "").strip():
        notify(state, "W", "Clear the search box to edit the database.")
        return True
    return False


def on_solvent_library_search(state):
    query = (state.solvent_search or "").strip()
    state.solvent_library_view_df = (
        db.filter_rows(state.solvent_library_df, query) if query else state.solvent_library_df)


def _fluid_props(fname: str, df: pd.DataFrame, T: float = 25.0) -> dict | None:
    """Return property dict for a solvent (at T) or custom fluid (fixed)."""
    if is_known_solvent(fname):
        p = get_properties(fname, T)
        return {k: p[k] for k in (
            "rho_kg_m3", "mu_Pa_s", "D_mol_m2_s", "surface_tension_N_m",
            "Cp_J_per_kgK", "k_W_per_mK")}
    if not df.empty and fname in df["fluid_name"].astype(str).values:
        row = df[df["fluid_name"].astype(str) == fname].iloc[0]
        try:
            return {
                "rho_kg_m3": float(row["rho_kg_m3"]),
                "mu_Pa_s": float(row["mu_Pa_s"]),
                "D_mol_m2_s": float(row["D_mol_m2_s"]),
                "surface_tension_N_m": float(row["surface_tension_N_m"]),
                "Cp_J_per_kgK": float(row.get("Cp_J_per_kgK", 4182.0) or 4182.0),
                "k_W_per_mK": float(row.get("k_W_per_mK", 0.607) or 0.607),
            }
        except (TypeError, ValueError):  # non-numeric cell -> treat as missing
            return None
    return None


def _compute_solvent_props(name: str, P_atm: float, T_C: float):
    sd = SOLVENT_DB[name]
    bp_at_P = boiling_point_at_pressure(P_atm, sd)
    props = get_properties(name, T_C, P_atm)
    props_df = pd.DataFrame([
        {"Property": "Density ρ", "Value": f"{props['rho_kg_m3']:.2f}", "Units": "kg/m³"},
        {"Property": "Viscosity μ", "Value": f"{props['mu_Pa_s']:.6f}", "Units": "Pa·s"},
        {"Property": "Surface tension σ", "Value": f"{props['surface_tension_N_m']:.4f}", "Units": "N/m"},
        {"Property": "Diffusivity D", "Value": f"{props['D_mol_m2_s']:.3e}", "Units": "m²/s"},
        {"Property": "Specific heat Cp", "Value": f"{props['Cp_J_per_kgK']:.1f}", "Units": "J/kg·K"},
        {"Property": "Thermal conductivity k", "Value": f"{props['k_W_per_mK']:.4f}", "Units": "W/m·K"},
        {"Property": "Vapour pressure", "Value": f"{props['vapor_pressure_atm']:.4f}", "Units": "atm"},
        {"Property": "b.p. at P", "Value": f"{bp_at_P:.1f}", "Units": "°C"},
        {"Property": "Normal b.p.", "Value": f"{sd.bp_C:.1f}", "Units": "°C"},
        {"Property": "m.p.", "Value": f"{props['mp_C']:.1f}", "Units": "°C"},
        {"Property": "MW", "Value": f"{props['mw']:.2f}", "Units": "g/mol"},
        {"Property": "CAS", "Value": str(props["cas"]), "Units": "–"},
    ])
    if props["in_range"]:
        range_msg = f"Liquid range at {P_atm:.3f} atm: {sd.mp_C:.0f} – {bp_at_P:.0f} °C."
    else:
        range_msg = (f"⚠️ {T_C:.1f} °C is outside the liquid range "
                     f"({sd.mp_C:.0f} – {bp_at_P:.0f} °C) — values are extrapolated.")

    # 6-panel property-vs-temperature curves across the liquid range
    T_arr = np.linspace(sd.mp_C, bp_at_P, 200)
    fig = make_subplots(rows=3, cols=2, subplot_titles=[
        "Density ρ (kg/m³)", "Viscosity μ (Pa·s)",
        "Surface tension σ (N/m)", "Diffusivity D (m²/s)",
        "Specific heat Cp (J/kg·K)", "Thermal conductivity k (W/m·K)",
    ], vertical_spacing=0.12, horizontal_spacing=0.10)
    series = [
        (1, 1, [density(T, sd) for T in T_arr]),
        (1, 2, [viscosity(T, sd) for T in T_arr]),
        (2, 1, [surface_tension(T, sd) for T in T_arr]),
        (2, 2, [diffusivity(T, sd) for T in T_arr]),
        (3, 1, [specific_heat(T, sd) for T in T_arr]),
        (3, 2, [thermal_conductivity(T, sd) for T in T_arr]),
    ]
    idx = int(np.argmin(np.abs(T_arr - T_C)))
    for r, c, y_arr in series:
        fig.add_trace(go.Scatter(x=T_arr, y=y_arr, mode="lines",
                                 line={"width": 2}, showlegend=False), row=r, col=c)
        fig.add_trace(go.Scatter(x=[T_C], y=[y_arr[idx]], mode="markers",
                                 marker={"size": 10, "color": "red"}, showlegend=False),
                      row=r, col=c)
        fig.update_xaxes(title_text="T (°C)", row=r, col=c)
    fig.update_layout(height=760, margin={"t": 40, "b": 40},
                      title=f"{name} — properties vs temperature")
    return props_df, range_msg, fig


# Populate the Solvent Properties view for the initial render.
solvent_props_df, solvent_range_msg, solvent_prop_fig = _compute_solvent_props(
    solvent_selected, solvent_P, solvent_T)


# ---------------------------------------------------------------------------
# Handlers — Custom fluid CRUD
# ---------------------------------------------------------------------------
def on_fluid_edit(state, var_name, payload):
    if _fluid_searching(state):
        return
    state.fluid_df = db.apply_edit(state.fluid_df.copy(), payload)
    _persist(state)
    notify(state, "S", "Saved.")


def on_fluid_delete(state, var_name, payload):
    if _fluid_searching(state):
        return
    state.fluid_df = db.delete_row(state.fluid_df.copy(), payload)
    _persist(state)
    notify(state, "I", "Row deleted.")


def on_fluid_add(state, var_name, payload):
    if _fluid_searching(state):
        return
    state.fluid_df = db.add_blank(state.fluid_df.copy(), COLUMNS)
    _persist(state)


def on_fluid_add_row(state):
    name = (state.flu_new_name or "").strip()
    if not name:
        notify(state, "W", "Enter a fluid name.")
        return
    if is_known_solvent(name):
        notify(state, "W", f"'{name}' is already in the solvent library — no need to add it.")
        return
    if db.name_taken(state.fluid_df, "fluid_name", name):
        notify(state, "E", f"A custom fluid named '{name}' already exists.")
        return
    try:
        props = {
            "rho_kg_m3": float(state.flu_new_rho), "mu_Pa_s": float(state.flu_new_mu),
            "D_mol_m2_s": float(state.flu_new_D),
            "surface_tension_N_m": float(state.flu_new_sigma),
            "Cp_J_per_kgK": float(state.flu_new_Cp), "k_W_per_mK": float(state.flu_new_k),
            "hsp_d": float(state.flu_new_hd), "hsp_p": float(state.flu_new_hp),
            "hsp_h": float(state.flu_new_hh),
        }
    except (TypeError, ValueError):
        notify(state, "E", "All property fields must be numeric.")
        return
    new = pd.DataFrame([{"fluid_name": name, "notes": state.flu_new_notes, **props}])
    state.fluid_df = db.reset(pd.concat([state.fluid_df, new], ignore_index=True))
    _persist(state)
    state.flu_new_name = ""
    notify(state, "S", f"Added '{name}'.")


def on_fluid_import(state):
    path = state.fluid_upload
    if not path:
        return
    try:
        new_df = pd.read_csv(path)
    except Exception as exc:  # noqa: BLE001 - surface parse errors to the user
        notify(state, "E", f"Import failed: {exc}")
        return
    state.fluid_df = db.reset(new_df)
    _persist(state)
    notify(state, "S", f"Imported {len(new_df)} custom fluids (replaced database).")


# ---------------------------------------------------------------------------
# Handlers — Solvent properties (T)
# ---------------------------------------------------------------------------
def on_solvent_change(state):
    props_df, range_msg, fig = _compute_solvent_props(
        state.solvent_selected, float(state.solvent_P), float(state.solvent_T))
    state.solvent_props_df = props_df
    state.solvent_range_msg = range_msg
    state.solvent_prop_fig = fig


# ---------------------------------------------------------------------------
# Handlers — Blend
# ---------------------------------------------------------------------------
def on_blend_select(state):
    comps = list(state.blend_selected or [])
    state.blend_input_df = pd.DataFrame(
        [{"Component": c, "Amount": 1.0} for c in comps])


def on_blend_amount_edit(state, var_name, payload):
    state.blend_input_df = db.apply_edit(state.blend_input_df.copy(), payload)


def _join_pairs(pairs: list[str], limit: int = 3) -> str:
    """Render offending pair labels for a status line, truncating long lists."""
    if len(pairs) <= limit:
        return "; ".join(pairs)
    return "; ".join(pairs[:limit]) + f"; +{len(pairs) - limit} more"


def on_blend_compute(state):
    inp = state.blend_input_df
    if inp.empty:
        notify(state, "W", "Select components and enter amounts first.")
        return
    comps = inp["Component"].astype(str).tolist()
    try:
        amounts = {str(r["Component"]): float(r["Amount"]) for _, r in inp.iterrows()}
    except (TypeError, ValueError):
        notify(state, "E", "Component amounts must be numeric.")
        return
    total = sum(amounts.values())
    if total <= 0:
        notify(state, "E", "Total amount must be > 0.")
        return
    T = float(state.blend_T)
    is_vol = state.blend_basis == "Volume"

    comp_props, missing = [], []
    for comp in comps:
        p = _fluid_props(comp, state.fluid_df, T)
        if p is None:
            missing.append(comp)
        else:
            comp_props.append({"name": comp, "input": amounts[comp] / total, **p})
    if missing:
        notify(state, "E", f"No properties for: {', '.join(missing)}")
        return
    bad = [cp["name"] for cp in comp_props
           if not (cp["rho_kg_m3"] > 0 and cp["mu_Pa_s"] > 0 and cp["D_mol_m2_s"] > 0)]
    if bad:
        notify(state, "E",
               f"Invalid properties (ρ, μ and D must be > 0) for: {', '.join(bad)}")
        return

    if is_vol:
        for cp in comp_props:
            cp["vol_frac"] = cp["input"]
        masses = [cp["vol_frac"] * cp["rho_kg_m3"] for cp in comp_props]
        tm = sum(masses)
        for cp, m in zip(comp_props, masses):
            cp["mass_frac"] = m / tm
    else:
        for cp in comp_props:
            cp["mass_frac"] = cp["input"]
        vols = [cp["mass_frac"] / cp["rho_kg_m3"] for cp in comp_props]
        tv = sum(vols)
        for cp, v in zip(comp_props, vols):
            cp["vol_frac"] = v / tv

    # Literature mixing rules
    blend_rho = 1.0 / sum(cp["mass_frac"] / cp["rho_kg_m3"] for cp in comp_props)
    blend_mu = float(np.exp(sum(cp["mass_frac"] * np.log(cp["mu_Pa_s"]) for cp in comp_props)))
    blend_D = float(np.exp(sum(cp["mass_frac"] * np.log(cp["D_mol_m2_s"]) for cp in comp_props)))
    blend_sig = sum(cp["vol_frac"] * cp["surface_tension_N_m"] for cp in comp_props)
    blend_Cp = sum(cp["mass_frac"] * cp["Cp_J_per_kgK"] for cp in comp_props)
    blend_k = sum(cp["vol_frac"] * cp["k_W_per_mK"] for cp in comp_props)

    rows = [{
        "Component": cp["name"],
        "Vol %": f"{cp['vol_frac'] * 100:.1f}",
        "Mass %": f"{cp['mass_frac'] * 100:.1f}",
        "ρ (kg/m³)": f"{cp['rho_kg_m3']:.1f}",
        "μ (Pa·s)": f"{cp['mu_Pa_s']:.6f}",
        "σ (N/m)": f"{cp['surface_tension_N_m']:.4f}",
        "D (m²/s)": f"{cp['D_mol_m2_s']:.3e}",
        "Cp (J/kg·K)": f"{cp['Cp_J_per_kgK']:.1f}",
        "k (W/m·K)": f"{cp['k_W_per_mK']:.4f}",
    } for cp in comp_props]
    rows.append({
        "Component": "Blend",
        "Vol %": "100.0", "Mass %": "100.0",
        "ρ (kg/m³)": f"{blend_rho:.1f}", "μ (Pa·s)": f"{blend_mu:.6f}",
        "σ (N/m)": f"{blend_sig:.4f}", "D (m²/s)": f"{blend_D:.3e}",
        "Cp (J/kg·K)": f"{blend_Cp:.1f}", "k (W/m·K)": f"{blend_k:.4f}",
    })
    state.blend_result_df = pd.DataFrame(rows)

    # Pairwise miscibility screening
    misc_rows = []
    reactive_pairs, immiscible_pairs, unknown_pairs = [], [], []
    for n1, n2 in combinations(comps, 2):
        m = solvent_miscibility(n1, n2, custom_fluids=state.fluid_df)
        label = f"{n1} / {n2}"
        misc_rows.append({
            "Pair": label,
            "Assessment": m["assessment"],
            "R_a (MPa½)": f"{m['Ra']:.1f}" if m.get("Ra") is not None else "—",
            "Source": m["source"],
        })
        if m.get("reactive"):
            reactive_pairs.append(label)
        elif m["miscible"] is False:
            immiscible_pairs.append(label)
        elif m["miscible"] is None:
            unknown_pairs.append(label)
    state.blend_misc_df = pd.DataFrame(misc_rows) if misc_rows else pd.DataFrame(
        columns=["Pair", "Assessment", "R_a (MPa½)", "Source"])

    if reactive_pairs:
        state.blend_status = (f"⚠️ Reacts chemically on mixing ({_join_pairs(reactive_pairs)}) — "
                              "this is not a physical blend; averaged properties do not apply.")
        notify(state, "E", "Reactive pair detected.")
    elif immiscible_pairs:
        state.blend_status = (f"⚠️ Immiscible / partially miscible ({_join_pairs(immiscible_pairs)}) — "
                              "the blend may split into phases; averaged properties may not apply.")
        notify(state, "W", "Immiscible pair detected.")
    elif unknown_pairs:
        state.blend_status = (f"❔ Miscibility unknown — no HSP data for {_join_pairs(unknown_pairs)}. "
                              f"If single-phase: ρ = {blend_rho:.1f} kg/m³, μ = {blend_mu:.6f} Pa·s.")
        notify(state, "I", "Some pairs have unknown miscibility.")
    else:
        state.blend_status = f"🟢 Single-phase blend: ρ = {blend_rho:.1f} kg/m³, μ = {blend_mu:.6f} Pa·s."
        notify(state, "S", "Blend computed.")


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------
page = Markdown(
    inject_icons("""
# __ICON:Fluid_Database__Fluid Database

<|{fluid_msg}|text|>

<|{fluid_tab}|toggle|lov={fluid_tab_options}|>

<|part|render={fluid_tab == "Solvent Library"}|
<|part|class_name=va-card|
## Solvent Library

Reference table of all built-in solvents with **properties at 25 °C and 1 atm**.
These are always available in the assessment tools — pick one and set any
temperature to get properties from literature correlations.

<|Solvent database|expandable|expanded=False|
<|{solvent_search}|input|label=Search solvents|on_change=on_solvent_library_search|class_name=db-search|>

<|{solvent_library_view_df}|table|width=100%|filter|page_size=15|>
|>
|>

<|part|class_name=va-card|
### Custom Fluids
Manually added fluids with fixed (temperature-independent) properties.

<|Custom fluids|expandable|expanded=False|
<|{fluid_df}|table|width=100%|filter|page_size=10|>
|>
|>
|>

<|part|render={fluid_tab == "Solvent Properties"}|
<|part|class_name=va-card|
## Solvent Properties at Temperature

Compute physical properties for a built-in solvent at any liquid-phase
temperature and pressure. The Antoine equation adjusts the boiling point for
non-atmospheric pressure.

<|layout|columns=1 1 1|class_name=form-grid|
<|{solvent_selected}|selector|lov={solvent_options}|dropdown|label=Solvent|on_change=on_solvent_change|>

<|{solvent_P}|number|label=Pressure (atm)|on_change=on_solvent_change|>

<|{solvent_T}|number|label=Temperature (°C)|on_change=on_solvent_change|>
|>

<|{solvent_range_msg}|text|>

<|{solvent_props_df}|table|width=100%|show_all|>

<|chart|figure={solvent_prop_fig}|height=780px|>
|>
|>

<|part|render={fluid_tab == "Custom Fluids"}|
<|part|class_name=va-card|
## Custom Fluids

Add or edit **custom fluids** not in the built-in solvent library (mixtures,
slurries, concentrated acids). Custom fluids have fixed properties.
**Every table edit is saved automatically.**

<|Custom fluids database|expandable|expanded=True|
<|{fluid_search}|input|label=Search custom fluids|on_change=on_fluid_search|class_name=db-search|>

<|{fluid_view_df}|table|editable={fluid_search == ""}|filter|rebuild|on_edit=on_fluid_edit|on_delete=on_fluid_delete|on_add=on_fluid_add|width=100%|page_size=12|>
|>
|>

<|part|class_name=va-card|
### Add Custom Fluid
<|layout|columns=1 1 1|class_name=form-grid|
<|{flu_new_name}|input|label=Fluid name *|>

<|{flu_new_rho}|number|label=Density ρ (kg/m³)|>

<|{flu_new_mu}|number|label=Viscosity μ (Pa·s)|>
|>

<|layout|columns=1 1 1|class_name=form-grid|
<|{flu_new_D}|number|label=Diffusivity D (m²/s)|>

<|{flu_new_sigma}|number|label=Surface tension σ (N/m)|>

<|{flu_new_Cp}|number|label=Specific heat Cp (J/kg·K)|>
|>

<|layout|columns=1 1 1|class_name=form-grid|
<|{flu_new_k}|number|label=Thermal conductivity k (W/m·K)|>

<|{flu_new_notes}|input|label=Notes|>

<|Add fluid|button|on_action=on_fluid_add_row|>
|>

**Hansen solubility parameters** _(optional — for miscibility screening; 0 = unknown)_
<|layout|columns=1 1 1|class_name=form-grid|
<|{flu_new_hd}|number|label=δd dispersion (MPa½)|>

<|{flu_new_hp}|number|label=δp polar (MPa½)|>

<|{flu_new_hh}|number|label=δh H-bonding (MPa½)|>
|>
|>
|>

<|part|render={fluid_tab == "Blend"}|
<|part|class_name=va-card|
## Blend Fluids

Create a blend from solvents and/or custom fluids. Enter proportions on a
**volume** or **mass** basis; properties are combined with literature mixing
rules (log-mixing viscosity, volume-additive density, etc.).

<|layout|columns=2 1 1|class_name=form-grid|
<|{blend_selected}|selector|lov={blend_available}|multiple|dropdown|label=Component fluids|on_change=on_blend_select|>

<|{blend_basis}|toggle|lov={blend_basis_options}|label=Input basis|>

<|{blend_T}|number|label=Temperature (°C)|>
|>

### Component amounts
<|{blend_input_df}|table|editable|rebuild|on_edit=on_blend_amount_edit|width=60%|show_all|>

<|Compute blend|button|on_action=on_blend_compute|class_name=compute-btn|>
|>

<|part|class_name=va-card|
### Results
<|{blend_status}|text|>

<|{blend_result_df}|table|width=100%|show_all|>

### Miscibility screening
_Screening reflects ~25 °C behaviour; temperature effects (e.g. hexane/methanol UCST ≈ 34 °C) are not modeled._

<|{blend_misc_df}|table|width=100%|show_all|>
|>
|>

<|part|render={fluid_tab == "Import / Export"}|
<|part|class_name=va-card|
## Import / Export (custom fluids)
<|layout|columns=1 1|
<|Download CSV|file_download|content={fluid_export}|name=fluids_export.csv|label=Download custom fluids|>

<|{fluid_upload}|file_selector|label=Import CSV (replaces custom fluids)|on_action=on_fluid_import|extensions=.csv|>
|>
|>
|>
""")
)
