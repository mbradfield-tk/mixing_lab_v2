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

import pandas as pd
import plotly.graph_objects as go
from taipy.gui import Markdown, notify

from utils.menu_icons import inject_icons
from pages import _db_common as db
from core import catalog
from core import fluids
from core import repositories as repos
from core import solvents as solvent_curves
from viz import fluids as viz_fluids

REPO = repos.fluids
FLUID_CSV = REPO.path
COLUMNS = REPO.columns

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
solvent_library_df = pd.DataFrame(fluids.library_table())
solvent_options = catalog.solvent_names()
solvent_search = ""
solvent_library_view_df = solvent_library_df

# ---------------------------------------------------------------------------
# Custom fluids (editable, persisted)
# ---------------------------------------------------------------------------
fluid_df = REPO.load()
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
blend_available = list(solvent_options)
blend_selected: list[str] = []
blend_basis = "Volume"
blend_basis_options = ["Volume", "Mass"]
blend_T = 25.0
blend_input_df = pd.DataFrame(columns=["Component", "Amount"])
blend_result_df = pd.DataFrame(columns=["Component", "Vol %", "Mass %", "ρ (kg/m³)", "μ (Pa·s)",
                                        "σ (N/m)", "D (m²/s)", "Cp (J/kg·K)", "k (W/m·K)"])
blend_misc_df = pd.DataFrame(columns=["Pair", "Assessment", "R_a (MPa½)", "Source"])
blend_dispersion_speed = 5.0
blend_dispersion_d = 0.05
blend_dispersion_h = 1.0
blend_sigma_ll = 0.01
blend_dispersion_df = pd.DataFrame(columns=[
    "Pair", "Weber number", "d₃₂ (µm)", "N_min (1/s)", "N/N_min", "Rest separation"
])
blend_status = "Select two or more components and enter amounts, then compute."


_phase_placeholder_fig = viz_fluids.message


blend_phase_fig = _phase_placeholder_fig("Compute a blend to see the predicted phase stratification.")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _refresh_available() -> list[str]:
    custom = fluid_df["fluid_name"].dropna().astype(str).tolist() if not fluid_df.empty else []
    return solvent_options + custom


blend_available = _refresh_available()


def _persist(state, df) -> None:
    state.fluid_df = df
    state.fluid_export = db.csv_bytes(df)
    state.fluid_msg = f"{len(df)} custom fluids (plus {len(solvent_options)} built-in solvents)."
    custom = df["fluid_name"].dropna().astype(str).tolist() if not df.empty else []
    state.blend_available = solvent_options + custom
    state.fluid_view_df = _apply_fluid_search(state)


def _apply_fluid_search(state) -> pd.DataFrame:
    """Full custom-fluids frame, or a filtered (read-only) view while searching."""
    return REPO.search(state.fluid_df, state.fluid_search)[0]


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
    return fluids.component_props(fname, df, T)


def _compute_solvent_props(name: str, P_atm: float, T_C: float):
    props = fluids.solvent_state(name, P_atm, T_C)
    bp_at_P = props["bp_at_P_C"]
    mp_C = props["liquid_range_C"][0]
    props_df = pd.DataFrame([
        {"Property": "Density ρ", "Value": f"{props['rho_kg_m3']:.2f}", "Units": "kg/m³"},
        {"Property": "Viscosity μ", "Value": f"{props['mu_Pa_s']:.6f}", "Units": "Pa·s"},
        {"Property": "Surface tension σ", "Value": f"{props['surface_tension_N_m']:.4f}", "Units": "N/m"},
        {"Property": "Diffusivity D", "Value": f"{props['D_mol_m2_s']:.3e}", "Units": "m²/s"},
        {"Property": "Specific heat Cp", "Value": f"{props['Cp_J_per_kgK']:.1f}", "Units": "J/kg·K"},
        {"Property": "Thermal conductivity k", "Value": f"{props['k_W_per_mK']:.4f}", "Units": "W/m·K"},
        {"Property": "Vapour pressure", "Value": f"{props['vapor_pressure_atm']:.4f}", "Units": "atm"},
        {"Property": "b.p. at P", "Value": f"{bp_at_P:.1f}", "Units": "°C"},
        {"Property": "Normal b.p.", "Value": f"{props['bp_C']:.1f}", "Units": "°C"},
        {"Property": "m.p.", "Value": f"{props['mp_C']:.1f}", "Units": "°C"},
        {"Property": "MW", "Value": f"{props['mw']:.2f}", "Units": "g/mol"},
        {"Property": "CAS", "Value": str(props["cas"]), "Units": "–"},
    ])
    if props["in_range"]:
        range_msg = f"Liquid range at {P_atm:.3f} atm: {mp_C:.0f} – {bp_at_P:.0f} °C."
    else:
        range_msg = (f"⚠️ {T_C:.1f} °C is outside the liquid range "
                     f"({mp_C:.0f} – {bp_at_P:.0f} °C) — values are extrapolated.")

    fig = viz_fluids.property_curves(name, solvent_curves.property_curves(name, P_atm), T_C)
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
    _persist(state, REPO.edit(state.fluid_df, payload, db.ANONYMOUS))
    notify(state, "S", "Saved.")


def on_fluid_delete(state, var_name, payload):
    if _fluid_searching(state):
        return
    _persist(state, REPO.delete(state.fluid_df, payload, db.ANONYMOUS))
    notify(state, "I", "Row deleted.")


def on_fluid_add(state, var_name, payload):
    if _fluid_searching(state):
        return
    _persist(state, REPO.add_blank(state.fluid_df, db.ANONYMOUS))


def on_fluid_add_row(state):
    data = {
        "fluid_name": state.flu_new_name, "notes": state.flu_new_notes,
        "rho_kg_m3": state.flu_new_rho, "mu_Pa_s": state.flu_new_mu,
        "D_mol_m2_s": state.flu_new_D, "surface_tension_N_m": state.flu_new_sigma,
        "Cp_J_per_kgK": state.flu_new_Cp, "k_W_per_mK": state.flu_new_k,
        "hsp_d": state.flu_new_hd, "hsp_p": state.flu_new_hp, "hsp_h": state.flu_new_hh,
    }
    try:
        df = REPO.create(state.fluid_df, data, db.ANONYMOUS)
    except ValueError as exc:
        notify(state, "E", str(exc))
        return
    _persist(state, df)
    name = (state.flu_new_name or "").strip()
    state.flu_new_name = ""
    notify(state, "S", f"Added '{name}'.")


def on_fluid_import(state):
    path = state.fluid_upload
    if not path:
        return
    try:
        new_df = db.read_upload_csv(path)
    except Exception as exc:  # noqa: BLE001 - surface parse errors to the user
        notify(state, "E", f"Import failed: {exc}")
        return
    _persist(state, REPO.replace(new_df, db.ANONYMOUS))
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
    try:
        amounts = {str(r["Component"]): float(r["Amount"]) for _, r in inp.iterrows()}
    except (TypeError, ValueError):
        notify(state, "E", "Component amounts must be numeric.")
        return
    try:
        res = fluids.blend(amounts, state.blend_basis == "Volume", float(state.blend_T),
                           state.fluid_df, float(state.blend_dispersion_speed),
                           float(state.blend_dispersion_d), float(state.blend_dispersion_h),
                           float(state.blend_sigma_ll))
    except ValueError as exc:
        notify(state, "E", str(exc))
        return
    comp_props, mixed = res["components"], res["blend"]
    blend_rho, blend_mu = mixed["rho_kg_m3"], mixed["mu_Pa_s"]

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
        "σ (N/m)": f"{mixed['surface_tension_N_m']:.4f}", "D (m²/s)": f"{mixed['D_mol_m2_s']:.3e}",
        "Cp (J/kg·K)": f"{mixed['Cp_J_per_kgK']:.1f}", "k (W/m·K)": f"{mixed['k_W_per_mK']:.4f}",
    })
    state.blend_result_df = pd.DataFrame(rows)

    misc_rows = [{
        "Pair": p["label"],
        "Assessment": p["misc"]["assessment"],
        "R_a (MPa½)": f"{p['misc']['Ra']:.1f}" if p["misc"].get("Ra") is not None else "—",
        "Source": p["misc"]["source"],
    } for p in res["pairs"]]
    state.blend_misc_df = pd.DataFrame(misc_rows) if misc_rows else pd.DataFrame(
        columns=["Pair", "Assessment", "R_a (MPa½)", "Source"])

    if res["phases"] is None:
        state.blend_phase_fig = _phase_placeholder_fig(
            "⚠️ Reactive pair — chemical reaction on mixing;<br>"
            "physical phase stratification does not apply.")
    else:
        state.blend_phase_fig = viz_fluids.phase_stack(*res["phases"])

    # Preliminary liquid-liquid dispersion screen for immiscible pairs. The
    # user-entered interfacial tension and vessel inputs make the assumptions
    # explicit; this is not a substitute for an emulsion stability model.
    state.blend_dispersion_df = pd.DataFrame([{
        "Pair": d["pair"],
        "Weber number": f"{d['We']:.3g}",
        "d₃₂ (µm)": f"{d['d32_um']:.3g}",
        "N_min (1/s)": f"{d['N_min_1_s']:.3g}",
        "N/N_min": f"{d['N_over_N_min']:.3g}",
        "Rest separation": d["assessment"],
    } for d in res["dispersion"]], columns=blend_dispersion_df.columns)

    pairs_of = {cls: [p["label"] for p in res["pairs"] if p["class"] == cls]
                for cls in ("reactive", "immiscible", "unknown")}
    if res["status"] == "reactive":
        state.blend_status = (f"⚠️ Reacts chemically on mixing ({_join_pairs(pairs_of['reactive'])}) — "
                              "this is not a physical blend; averaged properties do not apply.")
        notify(state, "E", "Reactive pair detected.")
    elif res["status"] == "immiscible":
        state.blend_status = (f"⚠️ Immiscible / partially miscible ({_join_pairs(pairs_of['immiscible'])}) — "
                              "the blend may split into phases; averaged properties may not apply.")
        notify(state, "W", "Immiscible pair detected.")
    elif res["status"] == "unknown":
        state.blend_status = (f"❔ Miscibility unknown — no HSP data for {_join_pairs(pairs_of['unknown'])}. "
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

### Liquid-liquid dispersion screen
For immiscible pairs, estimate dispersion stability using the entered operating
assumptions. Interfacial tension and impeller inputs are screening values.
<|layout|columns=1 1 1 1|class_name=form-grid|
<|{blend_dispersion_speed}|number|label=Impeller speed (1/s)|>
<|{blend_dispersion_d}|number|label=Impeller diameter (m)|>
<|{blend_dispersion_h}|number|label=Separation height (m)|>
<|{blend_sigma_ll}|number|label=Interfacial tension σ<sub>LL</sub> (N/m)|>
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

<|part|render={len(blend_dispersion_df) > 0}|
### Dispersion estimate
<|{blend_dispersion_df}|table|width=100%|show_all|>
|>

### Phase stratification
_Settled (unagitated) liquid levels predicted from pairwise miscibility and phase density —
densest phase at the bottom. Layer heights are proportional to volume; mutual solubility
between phases is neglected._

<|chart|figure={blend_phase_fig}|height=450px|>
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
