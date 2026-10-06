"""Vessel Assessment page (Taipy).

Ported and restructured from the Streamlit ``5_Mixing_Sensitivity.py`` page into
visually-grouped cards: (1) Vessel & System, (2) Phases (liquid always, optional
solid and gas), (3) Reaction (with kinetic-model display), and (4) Correlations
(empirical / experimental / reduced-order CFD, limited to what is registered for
the selected vessel). Results report the mixing hydrodynamics, Damkohler
mixing-sensitivity numbers, optional solid-suspension and heat-balance checks,
and an operating-envelope sweep across the RPM range and fill-volume band.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from taipy.gui import Markdown, notify

from utils.menu_icons import inject_icons
from utils.calculations import heat_balance_assessment, particle_suspension_criterion
from utils.solvent_properties import (
    is_known_solvent,
    list_solvents,
    resolve_solvent_name,
)
from utils.rom_registry import available_modes
from utils.report_builder import build_vessel_assessment_pdf, report_filename
from core import operating_point as op
from core import sensitivity_rules as rules
from core.kinetics import effective_t_rxn as _auto_t_rxn
from core.envelope import operating_window, solve_operating_point, surface_grid, sweep
from core.options import Coalescence, CorrSource, FeedLocation, GasTransfer, Toggle, is_on
from core.records import (
    VesselGeometry,
    fluid_props as _fluid_props,
    particle_row as _particle_row,
    range_midpoint as _avg_range,
    reaction_row as _reaction_row,
    reactor_id as _reactor_id,
    reactor_row as _reactor_row,
    sf as _sf,
)
from pages import _db_common as db
from vessel_media import build_vessel_viewer_html, media_caption

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
reactors_df = pd.read_csv(DATA_DIR / "reactors.csv")
reactions_df = pd.read_csv(DATA_DIR / "reactions.csv")
particles_df = pd.read_csv(DATA_DIR / "particles.csv")
fluids_df = pd.read_csv(DATA_DIR / "fluids.csv")

RECORDED_CSV = DATA_DIR / "recorded_results.csv"

# 3D vessel viewer render height (px). The Taipy `part` pane is sized a little
# taller so the image is fully visible without scrolling.
VIEWER_H = 380


# ---------------------------------------------------------------------------
# Data helpers
# ---------------------------------------------------------------------------
def _geometry(state) -> VesselGeometry:
    """Selected vessel's geometry with the page's advanced overrides applied."""
    return VesselGeometry.from_row(
        _reactor_row(state.va_reactor), H_max_fallback=state.va_d_tank,
    ).with_overrides(D_tank=state.va_d_tank, D_imp=state.va_d_imp,
                     Np=state.va_np, Nq=state.va_nq)


def _law_html(order: str) -> str:
    """Return a small self-contained HTML doc rendering the rate-law equation
    (real subscripts/italics — Taipy GUI has no native LaTeX/KaTeX support)."""
    if order in ("1", "pseudo-1"):
        expr = "<i>r</i>&nbsp;=&nbsp;<i>k</i>&thinsp;<i>C</i><sub>A</sub>"
    elif order in ("2", "pseudo-2"):
        expr = "<i>r</i>&nbsp;=&nbsp;<i>k</i>&thinsp;<i>C</i><sub>A</sub>&thinsp;<i>C</i><sub>B</sub>"
    else:
        expr = "<i>r</i>&nbsp;=&nbsp;<i>k</i>&thinsp;<i>f</i>(<i>C</i>)"
    return (
        "<!DOCTYPE html><html><head><meta charset='utf-8'></head>"
        "<body style='margin:0;padding:8px 14px;display:flex;align-items:center;"
        "font-size:20px;font-family:Georgia,\"Times New Roman\",serif;"
        "background:#eef3ff;color:#16305c;border-radius:6px;'>"
        f"{expr}</body></html>"
    )


def _kinetic_model(row: pd.Series) -> tuple[str, str, str]:
    """Return (kinetic-model markdown, rate-law HTML, reaction-scheme text)."""
    if row.empty:
        return "_No reaction selected._", _law_html(""), ""
    order = str(row.get("order", "1"))
    k = _sf(row.get("k_value"), 0.0)
    k_units = str(row.get("k_units", "") or "")
    dH = _sf(row.get("delta_H_kJ_mol"), 0.0)
    thermo = ("athermal" if dH == 0 else
              (f"exothermic (ΔH = {dH:g} kJ/mol)" if dH < 0
               else f"endothermic (ΔH = {dH:g} kJ/mol)"))
    model = f"**Order {order}** · k = {k:g} {k_units} · {thermo}"
    scheme = str(row.get("reaction_scheme", "") or "")
    return model, _law_html(order), scheme


def _gas_params(state) -> tuple[float, bool]:
    """Return (superficial gas velocity v_s, coalescing?) from the gas settings."""
    if (is_on(state.va_gas_mode)
            and GasTransfer.from_label(state.va_gas_transfer) is GasTransfer.SPARGING):
        return (_sf(state.va_vs, 0.0),
                Coalescence.from_label(state.va_coalescing) is Coalescence.COALESCING)
    return 0.0, True


def _refresh_corr(state):
    """Refresh the correlation-source options/status for the selected vessel."""
    modes = available_modes(state.va_reactor)
    labels = [CorrSource(m).label for m in modes]
    state.va_corr_options = labels
    if state.va_corr_mode not in labels:
        state.va_corr_mode = labels[0]
    if len(modes) > 1:
        state.va_corr_status = "Available sources for this vessel: " + ", ".join(labels) + "."
    else:
        state.va_corr_status = ("Only empirical (literature) correlations are registered for "
                                "this vessel. Experimental and reduced-order (CFD) sources become "
                                "available once fitted via ROM Fitting.")


# ---------------------------------------------------------------------------
# Option lists
# ---------------------------------------------------------------------------
reactor_options = sorted(reactors_df["reactor_name"].dropna().astype(str).unique().tolist())
reaction_class_options = db.reaction_names(reactions_df, "yes")
reaction_measured_options = db.reaction_names(reactions_df, "no")
reaction_source_options = ["Measured kinetics", "Reaction classes"]
reaction_options = reaction_measured_options or reaction_class_options
fluid_options = sorted(list_solvents() + fluids_df["fluid_name"].dropna().astype(str).tolist())
particle_options = sorted(particles_df["particle_name"].dropna().astype(str).unique().tolist())

# ---------------------------------------------------------------------------
# State — Section 1: Vessel & System
# ---------------------------------------------------------------------------
va_reactor = ("TMA EasyMax-102" if "TMA EasyMax-102" in reactor_options
              else (reactor_options[0] if reactor_options else ""))
va_T = 25.0
va_P = 1.0
va_T_cool = 15.0

# 3D vessel viewer (same media as the Vessel Database page)
va_viewer_html = build_vessel_viewer_html(_reactor_id(va_reactor), VIEWER_H)
va_media_caption = media_caption(_reactor_id(va_reactor))

# Geometry / agitation
_r0 = _reactor_row(va_reactor)
va_d_tank = _sf(_r0.get("D_tank_m"), 0.1)
va_d_imp = _sf(_r0.get("D_imp_m"), 0.05)
va_n_rpm = _avg_range(_r0, "N_rpm_min", "N_rpm_max", 300.0)
va_np = _sf(_r0.get("Np"), 1.27)
va_nq = _sf(_r0.get("Nq"), 0.79)
va_v_l = _avg_range(_r0, "V_L_min", "V_L_max", _sf(_r0.get("V_L"), 1.0))

# Operation mode — fed-batch (unlocks feed inputs feeding the mesomixing check)
va_fed_mode = Toggle.OFF.label
va_fed_mode_options = Toggle.labels()
va_feed_rate = 5.0
va_feed_diam = 3.0
va_feed_location = FeedLocation.BULK.label
va_feed_location_options = FeedLocation.labels()

# ---------------------------------------------------------------------------
# State — Section 2: Phases
# ---------------------------------------------------------------------------
# Liquid / solvent (always present)
va_fluid = "Water" if "Water" in fluid_options else fluid_options[0]
_fp0 = _fluid_props(va_fluid, va_T, va_P)
va_rho = _fp0["rho"]
va_mu = _fp0["mu"]
va_dmol = _fp0["D_mol"]
va_sigma = _fp0["sigma"]

# Solid (optional)
va_sl_mode = Toggle.OFF.label
va_sl_mode_options = Toggle.labels()
va_particle = particle_options[0] if particle_options else ""
_p0 = _particle_row(va_particle) if particle_options else pd.Series(dtype=object)
va_rho_p = _sf(_p0.get("rho_p_kg_m3"), 1500.0)
va_d50 = _sf(_p0.get("d50_um"), 50.0)
va_phi = _sf(_p0.get("shape_factor"), 1.0)
va_x_wt = 5.0
va_szw = 5.5
va_gmb_z = 3.0
va_cd = 0.33

# Gas (optional)
va_gas_mode = Toggle.OFF.label
va_gas_mode_options = Toggle.labels()
va_gas_transfer = GasTransfer.HEADSPACE.label
va_gas_transfer_options = GasTransfer.labels()
va_vs = 0.005
va_coalescing = Coalescence.COALESCING.label
va_coalescing_options = Coalescence.labels()

# ---------------------------------------------------------------------------
# State — Section 3: Reaction
# ---------------------------------------------------------------------------
va_reaction_source = reaction_source_options[0]
va_reaction_options = reaction_measured_options or reaction_class_options
va_reaction = va_reaction_options[0] if va_reaction_options else ""
_x0 = _reaction_row(va_reaction)
va_order = str(_x0.get("order", "1")) if not _x0.empty else "1"
va_k = _sf(_x0.get("k_value"), 0.01) if not _x0.empty else 0.01
va_c0 = _sf(_x0.get("C0_mol_L"), 0.1) if not _x0.empty else 0.1
va_trxn = _auto_t_rxn(va_order, va_k, va_c0, _sf(_x0.get("t_rxn_s"), 0.0) if not _x0.empty else 0.0)
va_dH = _sf(_x0.get("delta_H_kJ_mol"), 0.0) if not _x0.empty else 0.0
va_rxn_model, va_rxn_law, va_rxn_scheme = _kinetic_model(_x0)

# ---------------------------------------------------------------------------
# State — Section 4: Correlations
# ---------------------------------------------------------------------------
_modes0 = available_modes(va_reactor)
va_corr_options = [CorrSource(m).label for m in _modes0]
va_corr_mode = va_corr_options[0]
_extra0 = [m for m in _modes0 if m != CorrSource.LITERATURE]
va_corr_status = (
    "Available sources for this vessel: " + ", ".join(va_corr_options) + "."
    if _extra0 else
    "Only empirical (literature) correlations are registered for this vessel. "
    "Experimental and reduced-order (CFD) sources become available once fitted via ROM Fitting.")

# ---------------------------------------------------------------------------
# Operating-envelope parameter selection
# ---------------------------------------------------------------------------
# Every hydrodynamic / mass- / heat-transfer parameter that can be plotted as an
# operating envelope. Da numbers are derived; the rest come straight from the
# hydro dictionary.
_HYDRO_ENV_KEYS = [
    "Re", "Power (W)", "P/V (W/L)", "P/V (W/kg)", "Tip speed (m/s)",
    "Pumping rate (m³/s)", "Blend time 95% (s)", "Circulation time (s)",
    "Micromix time t_E (s)", "Kolmogorov η (µm)", "ε_max (W/kg)",
    "EDCF (W/kg/s)", "Torque (N·m)", "Froude number", "Avg shear rate (1/s)",
    "Max shear rate (1/s)", "Avg shear stress (Pa)", "kLa (1/s)",
    "kLa_surface (1/s)",
]
va_env_params_options = ["Da_macro", "Da_micro", "Da_GL"] + _HYDRO_ENV_KEYS
va_env_params = ["Da_macro", "Da_micro", "P/V (W/L)", "Blend time 95% (s)",
                 "Tip speed (m/s)", "Re"]
_ENV_LOG = {"Da_macro", "Da_micro", "Da_GL"}
# Chart height is driven by a dynamic CSS class (env-rows-N in app.py) keyed to
# the subplot row count, because the Taipy chart `height` property is not
# reactive after first render.
va_env_class = "env-rows-2"
va_env_caption = ""

# 3D response surfaces z = f(N, V) — generated on demand (button) because the
# N×V grid costs ~375 hydro evaluations per parameter set.
_SURF_N_PTS, _SURF_V_PTS = 25, 15
va_surf_fig = go.Figure()
va_surf_class = "env-rows-2"
va_surf_caption = ""
va_surf_ready = False
va_surf_stale = False   # True when results/params changed after the surfaces were built
va_surf_btn_class = "compute-btn"

# Solve-for: find N (or V) giving a target parameter value, other variable held
# at the Section 1 input.
_SOLVE_N = "Agitation speed N (RPM)"
_SOLVE_V = "Working volume V (L)"
va_solve_var_options = [_SOLVE_N, _SOLVE_V]
va_solve_var = _SOLVE_N
va_solve_param_options = va_env_params_options
va_solve_param = "P/V (W/L)"
va_solve_target = 0.5
va_solve_status = ""
va_solve_df = pd.DataFrame(columns=["#", "Solved variable", "Value", "Achieved",
                                    "Within vessel range"])
va_solve_value = 0.0
va_solve_found = False

# Hydrodynamics results-table rows: (hydro-dict key, display name, unit).
_HYDRO_ROWS = [
    ("Re", "Reynolds number", "–"),
    ("Power (W)", "Power", "W"),
    ("P/V (W/L)", "Power per volume", "W/L"),
    ("Tip speed (m/s)", "Tip speed", "m/s"),
    ("Blend time 95% (s)", "Blend time (95%)", "s"),
    ("Micromix time t_E (s)", "Micromixing time t_E", "s"),
    ("Kolmogorov η (µm)", "Kolmogorov length η", "µm"),
    ("Circulation time (s)", "Circulation time", "s"),
    ("Avg shear rate (1/s)", "Average shear rate", "1/s"),
    ("Max shear rate (1/s)", "Maximum shear rate", "1/s"),
    ("Torque (N·m)", "Torque", "N·m"),
    ("Froude number", "Froude number", "–"),
    ("kLa_surface (1/s)", "Surface kLa", "1/s"),
]

# Results
va_status = "Set inputs and click Compute Assessment."
va_hydro_df = pd.DataFrame(columns=["Parameter", "Value", "Units"])
va_dam_df = pd.DataFrame(columns=["Type", "Damköhler", "Value", "Regime"])
va_mt_df = pd.DataFrame(columns=["Transfer path", "kLa (1/s)", "Demand 1/t_rxn (1/s)",
                                 "Capacity / demand", "Screening"])
va_assess = ""
va_corr_applicability = ""
va_sl_df = pd.DataFrame(columns=["Parameter", "Value", "Units"])
va_heat_df = pd.DataFrame(columns=["Parameter", "Value", "Units"])
va_result_ready = False
va_env_fig = go.Figure()
va_compute_class = "compute-btn"   # red until an assessment is run; blue after
va_stale = False                   # True when inputs change after a run
va_hydro_csv = b""
va_dam_csv = b""
va_mt_csv = b""
va_sl_csv = b""
va_heat_csv = b""

va_pdf_bytes = b""
va_pdf_name = "Vessel_Assessment.pdf"
va_pdf_ready = False

# per-state raw snapshot of the last compute (for save-to-Recorded-Results)
_va_cache: dict = {}


# ---------------------------------------------------------------------------
# Change handlers — load defaults
# ---------------------------------------------------------------------------
def on_va_reactor_change(state):
    row = _reactor_row(state.va_reactor)
    state.va_d_tank = _sf(row.get("D_tank_m"), state.va_d_tank)
    state.va_d_imp = _sf(row.get("D_imp_m"), state.va_d_imp)
    state.va_n_rpm = _avg_range(row, "N_rpm_min", "N_rpm_max", state.va_n_rpm)
    state.va_np = _sf(row.get("Np"), 1.27)
    state.va_nq = _sf(row.get("Nq"), 0.79)
    state.va_v_l = _avg_range(row, "V_L_min", "V_L_max", _sf(row.get("V_L"), state.va_v_l))
    rid = _reactor_id(state.va_reactor)
    state.va_viewer_html = build_vessel_viewer_html(rid, VIEWER_H)
    state.va_media_caption = media_caption(rid)
    _refresh_corr(state)
    _mark_stale(state)
    notify(state, "I", "Vessel geometry loaded.")


def on_va_reaction_change(state):
    row = _reaction_row(state.va_reaction)
    if row.empty:
        return
    state.va_order = str(row.get("order", "1"))
    state.va_k = _sf(row.get("k_value"), state.va_k)
    state.va_c0 = _sf(row.get("C0_mol_L"), state.va_c0)
    state.va_trxn = _auto_t_rxn(state.va_order, state.va_k, state.va_c0, _sf(row.get("t_rxn_s"), 0.0))
    state.va_dH = _sf(row.get("delta_H_kJ_mol"), 0.0)
    state.va_rxn_model, state.va_rxn_law, state.va_rxn_scheme = _kinetic_model(row)
    solvent = str(row.get("solvent", "") or "")
    if solvent and (is_known_solvent(solvent) or solvent in fluid_options):
        state.va_fluid = resolve_solvent_name(solvent) or solvent
        _load_fluid(state)
    _mark_stale(state)
    notify(state, "I", "Reaction kinetics loaded.")


def on_va_reaction_source_change(state):
    state.va_reaction_options = (reaction_class_options if state.va_reaction_source == "Reaction classes"
                                 else reaction_measured_options) or ["(none available)"]
    if state.va_reaction not in state.va_reaction_options:
        state.va_reaction = state.va_reaction_options[0]
    on_va_reaction_change(state)


def _load_fluid(state):
    fp = _fluid_props(state.va_fluid, state.va_T, state.va_P)
    state.va_rho = fp["rho"]
    state.va_mu = fp["mu"]
    state.va_dmol = fp["D_mol"]
    state.va_sigma = fp["sigma"]


def on_va_fluid_change(state):
    _load_fluid(state)
    _mark_stale(state)
    notify(state, "I", "Fluid properties loaded.")


def on_va_sys_change(state):
    """Temperature or pressure changed — refresh solvent properties."""
    if is_known_solvent(state.va_fluid):
        _load_fluid(state)
    _mark_stale(state)


def on_va_particle_change(state):
    row = _particle_row(state.va_particle)
    state.va_rho_p = _sf(row.get("rho_p_kg_m3"), state.va_rho_p)
    state.va_d50 = _sf(row.get("d50_um"), state.va_d50)
    state.va_phi = _sf(row.get("shape_factor"), state.va_phi)
    _mark_stale(state)


def _mark_stale(state):
    """Flag the results as out-of-date and turn the Compute button red again."""
    if state.va_result_ready and not state.va_stale:
        state.va_stale = True
        state.va_compute_class = "compute-btn"
        state.va_pdf_ready = False


def on_va_input_change(state):
    """Generic input-change hook — marks the assessment results stale."""
    _mark_stale(state)


def on_va_env_change(state):
    """Rebuild the operating-envelope plot when the parameter selection changes."""
    if not state.va_result_ready:
        return
    t_rxn = _auto_t_rxn(state.va_order, state.va_k, state.va_c0, state.va_trxn)
    if t_rxn > 0:
        _build_envelope(state, t_rxn)
        _mark_surface_stale(state)
        state.va_pdf_ready = False


def _mark_surface_stale(state):
    """Flag the 3D surfaces as out-of-date relative to the current results."""
    if state.va_surf_ready and not state.va_surf_stale:
        state.va_surf_stale = True
        state.va_surf_btn_class = "compute-btn"


def on_va_surface(state):
    """Build the 3D response surfaces for the current assessment (on demand)."""
    if not state.va_result_ready or state.va_stale:
        notify(state, "W", "Compute the assessment before generating 3D surfaces.")
        return
    t_rxn = _auto_t_rxn(state.va_order, state.va_k, state.va_c0, state.va_trxn)
    if t_rxn <= 0:
        notify(state, "E", "Provide a reaction time or rate constant (> 0) first.")
        return
    _build_surface(state, t_rxn)
    state.va_surf_ready = True
    state.va_surf_stale = False
    state.va_surf_btn_class = "compute-btn-ok"
    notify(state, "S", "3D response surfaces generated.")


def _build_csv_exports(state):
    """Refresh CSV download content from the current assessment tables."""
    empty = pd.DataFrame()
    state.va_hydro_csv = db.csv_bytes(getattr(state, "va_hydro_df", empty))
    state.va_dam_csv = db.csv_bytes(getattr(state, "va_dam_df", empty))
    state.va_mt_csv = db.csv_bytes(getattr(state, "va_mt_df", empty))
    state.va_sl_csv = db.csv_bytes(getattr(state, "va_sl_df", empty))
    state.va_heat_csv = db.csv_bytes(getattr(state, "va_heat_df", empty))


def on_va_export_pdf(state):
    """Generate a PDF report of the current assessment (incl. the envelope chart)."""
    if not state.va_result_ready:
        notify(state, "W", "Compute the assessment before exporting.")
        return
    try:
        t_rxn = _auto_t_rxn(state.va_order, state.va_k, state.va_c0, state.va_trxn)
        snap = {
            "reactor": state.va_reactor, "fluid": state.va_fluid,
            "T": state.va_T, "P": state.va_P, "N_rpm": state.va_n_rpm,
            "V_L": state.va_v_l, "corr_mode": state.va_corr_mode,
            "reaction": state.va_reaction, "t_rxn": t_rxn, "dH": state.va_dH,
            "hydro_df": state.va_hydro_df, "assessment": state.va_assess,
            "dam_df": state.va_dam_df, "sl_df": state.va_sl_df,
            "heat_df": state.va_heat_df, "env_fig": state.va_env_fig,
            "env_caption": state.va_env_caption, "env_params": state.va_env_params,
        }
        state.va_pdf_bytes = build_vessel_assessment_pdf(snap)
        state.va_pdf_name = report_filename("Vessel_Assessment", state.va_reactor)
        state.va_pdf_ready = True
        notify(state, "S", "PDF report generated — click Download.")
    except Exception as exc:  # noqa: BLE001
        notify(state, "E", f"PDF generation failed: {exc}")


def on_va_save_results(state):
    """Append the last computed case to data/recorded_results.csv."""
    if not state.va_result_ready or not state._va_cache:
        notify(state, "W", "Compute the assessment before saving.")
        return
    cache = state._va_cache
    h, dam = cache["hydro"], cache["dam"]
    row = {
        "reactor": cache["reactor"], "reaction": cache["reaction"],
        "fluid": cache["fluid"], "fluid_T_C": cache["fluid_T_C"],
        "RPM": cache["rpm"], "Volume (L)": cache["v_l"],
        "Re": h.get("Re", ""), "P/V (W/L)": h.get("P/V (W/L)", ""),
        "Tip speed (m/s)": h.get("Tip speed (m/s)", ""),
        "Blend time (s)": h.get("Blend time 95% (s)", ""),
        "Circulation time (s)": h.get("Circulation time (s)", ""),
        "Micromix t_E (s)": h.get("Micromix time t_E (s)", ""),
        "Micromix t_E_local (s)": h.get("Micromix time t_E_local (s)", ""),
        "Kolmogorov η (µm)": h.get("Kolmogorov η (µm)", ""),
        "EDCF (W/kg/s)": h.get("EDCF (W/kg/s)", ""),
        "Torque (N·m)": h.get("Torque (N·m)", ""),
        "Froude number": h.get("Froude number", ""),
        "Avg shear rate (1/s)": h.get("Avg shear rate (1/s)", ""),
        "Max shear rate (1/s)": h.get("Max shear rate (1/s)", ""),
        "Avg shear stress (Pa)": h.get("Avg shear stress (Pa)", ""),
        "kLa (1/s)": h.get("kLa (1/s)", ""),
        "kLa_surface (1/s)": h.get("kLa_surface (1/s)", ""),
        "t_rxn (s)": cache["t_rxn"], "Da_macro": dam.get("Da_macro", ""),
        "Da_micro": dam.get("Da_micro", ""), "Da_GL": dam.get("Da_GL", ""),
        "Da_SL": dam.get("Da_SL", ""), "Assessment": dam.get("Assessment", ""),
    }
    try:
        db.append_csv(pd.DataFrame([row]), RECORDED_CSV)
        notify(state, "S", "Saved 1 result — view it on the Recorded Results page.")
    except Exception as exc:  # noqa: BLE001
        notify(state, "E", f"Save failed: {exc}")


# ---------------------------------------------------------------------------
# Core compute
# ---------------------------------------------------------------------------
def _correlation_applicability(state, hydro: dict) -> str:
    """Summarize applicability checks for the selected hydro correlations."""
    return rules.correlation_applicability(
        hydro, _geometry(state), _reactor_row(state.va_reactor), _sf(state.va_v_l),
        gas_on=is_on(state.va_gas_mode), solids_on=is_on(state.va_sl_mode))


def _inputs(state, t_rxn: float, *, heat: bool = True) -> op.PointInputs:
    """Operating-point inputs from the page state (heat=False skips the heat balance)."""
    v_s, coal = _gas_params(state)
    solids = (op.Solids(rho_p=_sf(state.va_rho_p), d50_um=_sf(state.va_d50),
                        phi=_sf(state.va_phi, 1.0), x_wt=_sf(state.va_x_wt),
                        S_zw=_sf(state.va_szw, 5.5), gmb_z=_sf(state.va_gmb_z, 3.0),
                        cd=_sf(state.va_cd, 0.33))
              if is_on(state.va_sl_mode) else None)
    feed = (op.Feed(FeedLocation.from_label(state.va_feed_location, FeedLocation.BULK),
                    _sf(state.va_feed_diam) / 1000.0)
            if is_on(state.va_fed_mode) else None)
    return op.PointInputs(
        reactor=state.va_reactor, geometry=_geometry(state),
        fluid=op.Fluid(state.va_fluid, _sf(state.va_rho), _sf(state.va_mu), _sf(state.va_dmol)),
        reaction=op.Reaction(str(state.va_order), _sf(state.va_k), _sf(state.va_c0),
                             t_rxn, _sf(state.va_dH)),
        corr_mode=CorrSource.from_label(state.va_corr_mode, CorrSource.LITERATURE),
        gas=op.Gas(v_s, coal), solids=solids, feed=feed,
        heat=op.Heat(_sf(state.va_T), _sf(state.va_T_cool)) if heat else None)


def on_va_compute(state):
    t_rxn = _auto_t_rxn(state.va_order, state.va_k, state.va_c0, state.va_trxn)
    if t_rxn <= 0:
        state.va_status = "Provide a reaction time or rate constant (> 0) to compute Damköhler numbers."
        notify(state, "E", state.va_status)
        return

    hydro = op.evaluate_point(_inputs(state, t_rxn), state.va_n_rpm / 60.0, state.va_v_l)
    state.va_corr_applicability = _correlation_applicability(state, hydro)
    sl_on, gas_on, fed_on = (is_on(state.va_sl_mode), is_on(state.va_gas_mode),
                             is_on(state.va_fed_mode))

    kla_sl = hydro.get("kLa_SL (1/s)", 0.0)
    if sl_on:
        n_js_rpm = hydro.get("N_js (RPM)", 0.0)
        assess = particle_suspension_criterion(state.va_n_rpm / 60.0, n_js_rpm / 60.0)
        state.va_sl_df = pd.DataFrame([
            {"Parameter": "Just-suspended speed N_js", "Value": f"{n_js_rpm:.1f}", "Units": "RPM"},
            {"Parameter": "Operating speed N", "Value": f"{state.va_n_rpm:.1f}", "Units": "RPM"},
            {"Parameter": "N / N_js", "Value": f"{(state.va_n_rpm / n_js_rpm) if n_js_rpm > 0 else 0:.2f}", "Units": "–"},
            {"Parameter": "Suspension state", "Value": assess, "Units": "–"},
            {"Parameter": "Settling velocity v_t", "Value": f"{hydro.get('v_t (m/s)', 0.0):.3g}", "Units": "m/s"},
            {"Parameter": "Solid-liquid k_SL", "Value": f"{hydro.get('k_SL (m/s)', 0.0):.3g}", "Units": "m/s"},
            {"Parameter": "Solid-liquid kLa_SL", "Value": f"{kla_sl:.3g}", "Units": "1/s"},
        ])
    else:
        state.va_sl_df = pd.DataFrame(columns=["Parameter", "Value", "Units"])

    dam = {k: hydro[k] for k in ("Da_macro", "Da_micro", "Da_GL", "Da_SL", "Assessment")}

    transfer_paths = []
    if gas_on:
        transfer_paths.append(("Gas-liquid", hydro["kLa (1/s)"]))
    if sl_on:
        transfer_paths.append(("Solid-liquid", kla_sl))
    state.va_mt_df = pd.DataFrame(rules.mass_transfer_screen(transfer_paths, t_rxn),
                                  columns=va_mt_df.columns)

    # Hydrodynamics KPI table
    state.va_hydro_df = pd.DataFrame(
        [{"Parameter": name, "Value": f"{hydro[key]:,.4g}", "Units": unit}
         for key, name, unit in _HYDRO_ROWS])

    _regime = rules.regime_label

    da_meso = hydro.get("Da_meso", 0.0)
    gl_type = ("Gas–liquid mass transfer" if gas_on
               else "Gas–liquid mass transfer (surface aeration)")

    dam_rows = [
        {"Type": "Macromixing (bulk blending)", "Damköhler": "Da_macro", "Value": f"{dam['Da_macro']:.3g}", "Regime": _regime(dam["Da_macro"])},
    ]
    if fed_on:
        dam_rows.append({"Type": "Mesomixing (feed dispersion)", "Damköhler": "Da_meso", "Value": f"{da_meso:.3g}", "Regime": _regime(da_meso)})
    dam_rows.append({"Type": "Micromixing (engulfment)", "Damköhler": "Da_micro", "Value": f"{dam['Da_micro']:.3g}", "Regime": _regime(dam["Da_micro"])})
    dam_rows.append({"Type": gl_type, "Damköhler": "Da_GL", "Value": f"{dam['Da_GL']:.3g}", "Regime": _regime(dam["Da_GL"])})
    if sl_on:
        dam_rows.append({"Type": "Solid–liquid mass transfer", "Damköhler": "Da_SL", "Value": f"{dam['Da_SL']:.3g}", "Regime": _regime(dam["Da_SL"])})
    state.va_dam_df = pd.DataFrame(dam_rows)
    state.va_assess = f"**Assessment:** {dam['Assessment']}"

    # Heat balance (optional — only when a heat of reaction is set)
    if "Q_gen (W)" in hydro:
        q_gen, q_cool = hydro["Q_gen (W)"], hydro["Q_cool (W)"]
        state.va_heat_df = pd.DataFrame([
            {"Parameter": "Heat generation Q_gen", "Value": f"{q_gen:,.1f}", "Units": "W"},
            {"Parameter": "Overall U", "Value": f"{hydro['U (W/m²·K)']:,.1f}", "Units": "W/m²·K"},
            {"Parameter": "Jacket area A", "Value": f"{hydro['A_ht (m²)']:,.4g}", "Units": "m²"},
            {"Parameter": "Cooling capacity Q_cool", "Value": f"{q_cool:,.1f}", "Units": "W"},
            {"Parameter": "Balance", "Value": heat_balance_assessment(q_gen, q_cool), "Units": "–"},
        ])
    else:
        state.va_heat_df = pd.DataFrame(columns=["Parameter", "Value", "Units"])

    _build_envelope(state, t_rxn)
    _mark_surface_stale(state)
    _build_csv_exports(state)

    state._va_cache = {
        "hydro": hydro, "dam": dam, "t_rxn": t_rxn,
        "reactor": state.va_reactor, "reaction": state.va_reaction,
        "fluid": state.va_fluid, "fluid_T_C": state.va_T,
        "rpm": state.va_n_rpm, "v_l": state.va_v_l,
    }

    state.va_result_ready = True
    state.va_compute_class = "compute-btn-ok"
    state.va_stale = False
    state.va_pdf_ready = False
    state.va_status = (f"Computed at {state.va_n_rpm:.0f} RPM, {state.va_v_l:.3g} L "
                       f"({state.va_corr_mode}) — Re = {hydro['Re']:,.0f}, "
                       f"P/V = {hydro['P/V (W/L)']:.3g} W/L.")
    notify(state, "S", "Assessment computed.")


def _evaluator(inp: op.PointInputs):
    """(N_rpm, V_L) -> full point dict for the core.envelope sweep/solve helpers."""
    return lambda n_rpm, v_l: op.evaluate_point(inp, n_rpm / 60.0, v_l)


def on_va_solve(state):
    """Solve for the N (or V) that gives the target value of the chosen parameter."""
    param = state.va_solve_param
    target = _sf(state.va_solve_target, float("nan"))
    if param not in va_solve_param_options or not np.isfinite(target):
        notify(state, "E", "Choose a parameter and a numeric target value.")
        return
    t_rxn = _auto_t_rxn(state.va_order, state.va_k, state.va_c0, state.va_trxn)
    if param.startswith("Da_") and t_rxn <= 0:
        notify(state, "E", "Damköhler targets need a reaction time or rate constant (> 0).")
        return

    solve_n = state.va_solve_var == _SOLVE_N
    if solve_n:
        name, unit, fixed = "N", "RPM", f"V = {state.va_v_l:.3g} L"
    else:
        name, unit, fixed = "V", "L", f"N = {state.va_n_rpm:.0f} RPM"

    try:
        res = solve_operating_point(
            _evaluator(_inputs(state, t_rxn, heat=False)), _reactor_row(state.va_reactor),
            param, target, "N_rpm" if solve_n else "V_L", state.va_n_rpm, state.va_v_l)
    except Exception as exc:  # noqa: BLE001
        notify(state, "E", f"Solve failed: {exc}")
        return
    (lo, hi), (rng_lo, rng_hi) = res["search"], res["window"]

    roots = res["roots"]
    rows = [{"#": i, "Solved variable": f"{name} ({unit})",
             "Value": f"{x:,.4g}", "Achieved": f"{param} = {achieved:.4g}",
             "Within vessel range": "Yes" if ok else "No"}
            for i, (x, achieved, ok) in enumerate(
                zip(roots, res["achieved"], res["in_window"]), start=1)]
    state.va_solve_df = pd.DataFrame(rows, columns=va_solve_df.columns)

    best = res["first_in_window"]
    state.va_solve_found = best is not None
    state.va_solve_value = float(best) if best is not None else 0.0
    window = f"{name} = {rng_lo:.4g}–{rng_hi:.4g} {unit}"
    if not roots:
        span = f"{res['span'][0]:.4g}–{res['span'][1]:.4g}" if res["span"] else "n/a"
        state.va_solve_status = (
            f"**No solution:** {param} = {target:g} is not reachable for {name} = "
            f"{lo:.4g}–{hi:.4g} {unit} at {fixed} (achievable range {span}).")
        notify(state, "W", "Target not reachable.")
    elif best is None:
        state.va_solve_status = (
            f"**Solution outside vessel range:** {param} = {target:g} needs {name} = "
            f"{roots[0]:.4g} {unit} at {fixed}; vessel window is {window}.")
        notify(state, "W", "Solution lies outside the vessel operating range.")
    else:
        extra = " (multiple solutions — see table)" if len(roots) > 1 else ""
        state.va_solve_status = (
            f"**Solution:** {name} = {best:.4g} {unit} gives {param} = "
            f"{target:g} at {fixed} ({state.va_corr_mode}){extra}.")
        notify(state, "S", f"Solved: {name} = {best:.4g} {unit}.")


def on_va_solve_apply(state):
    """Copy the in-range solution into the Section 1 operating inputs."""
    if not state.va_solve_found:
        return
    if state.va_solve_var == _SOLVE_N:
        state.va_n_rpm = round(state.va_solve_value, 1)
    else:
        state.va_v_l = round(state.va_solve_value, 4)
    state.va_solve_found = False
    _mark_stale(state)
    notify(state, "I", "Solution applied to the operating inputs.")


def _env_params(state) -> list[str]:
    params = [p for p in (state.va_env_params or []) if p in va_env_params_options]
    return params or ["Da_macro"]


def _env_ranges(state) -> tuple[np.ndarray, float, float]:
    """(RPM sweep array, V_min, V_max) for the selected vessel."""
    return operating_window(_reactor_row(state.va_reactor), state.va_n_rpm, state.va_v_l)


def _build_envelope(state, t_rxn: float):
    """Plot each SELECTED parameter as an operating *region*: an RPM sweep
    bounded by the vessel's minimum and maximum fill volume, with the current
    operating point marked. The subplot grid adapts to the number of chosen
    parameters."""
    params = _env_params(state)
    n_arr, v_min, v_max = _env_ranges(state)
    evaluate = _evaluator(_inputs(state, t_rxn, heat=False))
    curves = sweep(evaluate, n_arr, (v_max, v_min), params)
    hi_v, lo_v = curves[v_max], curves[v_min]
    current = evaluate(state.va_n_rpm, state.va_v_l)

    n = len(params)
    cols = min(3, n)
    rows = int(np.ceil(n / cols))
    positions = [(i // cols + 1, i % cols + 1) for i in range(n)]
    # Give each inter-row gap enough room for the lower row's x-axis title and
    # the next row's subplot title (Plotly spacing is a fraction of the total
    # height, so scale it down only as the row count grows).
    vspace = min(0.22, 0.6 / max(rows - 1, 1))
    fig = make_subplots(rows=rows, cols=cols, subplot_titles=params,
                        vertical_spacing=vspace, horizontal_spacing=0.08)
    for p, (r, c) in zip(params, positions):
        first = (p == params[0])
        y_hi, y_lo = hi_v[p], lo_v[p]
        # Shaded operating region between min- and max-volume boundaries.
        fig.add_trace(go.Scatter(
            x=np.concatenate([n_arr, n_arr[::-1]]),
            y=np.concatenate([y_hi, y_lo[::-1]]),
            fill="toself", fillcolor="rgba(92,102,112,0.22)",
            line={"width": 0}, hoverinfo="skip", showlegend=False), row=r, col=c)
        # Max-volume boundary (solid) and min-volume boundary (dotted) — mid
        # gray stays visible on both the light and dark chart backgrounds.
        fig.add_trace(go.Scatter(
            x=n_arr, y=y_hi, mode="lines", line={"width": 2, "color": "#808080"},
            name=f"V_max = {v_max:.0f} L", legendgroup="vmax",
            showlegend=first), row=r, col=c)
        fig.add_trace(go.Scatter(
            x=n_arr, y=y_lo, mode="lines",
            line={"width": 2, "color": "#808080", "dash": "dot"},
            name=f"V_min = {v_min:.0f} L", legendgroup="vmin",
            showlegend=first), row=r, col=c)
        # Current operating point (red star).
        fig.add_trace(go.Scatter(
            x=[state.va_n_rpm], y=[current[p]], mode="markers",
            marker={"symbol": "star", "size": 15, "color": "red",
                    "line": {"width": 1, "color": "black"}},
            name="Operating point", legendgroup="op",
            showlegend=first), row=r, col=c)
        fig.update_xaxes(title_text="N (RPM)", row=r, col=c)
        if p in _ENV_LOG:
            fig.update_yaxes(type="log", row=r, col=c)
            for thr, col_ in ((0.1, "orange"), (1.0, "red")):
                fig.add_hline(y=thr, line_dash="dash", line_color=col_, row=r, col=c)
    fig_height = max(360, rows * 360)
    # Place the horizontal legend a consistent ~45 px above the plot area (legend
    # y is a fraction of plot-area height, so it must scale with the figure).
    _t_margin = 90
    _plot_area = max(fig_height - _t_margin - 40, 120)
    _legend_y = 1 + 45 / _plot_area
    fig.update_layout(
        height=fig_height, margin={"t": _t_margin, "b": 40},
        # No explicit paper/font colors: Taipy swaps the plotly template per
        # theme, so legends/titles/axes stay legible in both light and dark mode.
        plot_bgcolor="rgba(225,37,27,0.06)",
        legend={"orientation": "h", "y": _legend_y, "yanchor": "bottom",
                "x": 0.5, "xanchor": "center"})
    state.va_env_fig = fig
    state.va_env_class = f"env-rows-{min(rows, 8)}"
    state.va_env_caption = (f"**Operating envelope** — RPM sweep across "
                            f"V = {v_min:.3g}–{v_max:.3g} L")


def _build_surface(state, t_rxn: float):
    """3D response surfaces z = f(N, V) for each selected parameter over the
    vessel's full RPM × fill-volume window, with the operating point marked."""
    params = _env_params(state)
    n_full, v_min, v_max = _env_ranges(state)
    n_arr = np.linspace(n_full[0], n_full[-1], _SURF_N_PTS)
    v_arr = np.linspace(v_min, v_max, _SURF_V_PTS)
    evaluate = _evaluator(_inputs(state, t_rxn, heat=False))
    z = surface_grid(evaluate, n_arr, v_arr, params)
    current = evaluate(state.va_n_rpm, state.va_v_l)

    n = len(params)
    cols = min(3, n)
    rows = int(np.ceil(n / cols))
    fig = make_subplots(
        rows=rows, cols=cols, subplot_titles=params,
        specs=[[{"type": "surface"}] * cols for _ in range(rows)],
        vertical_spacing=0.06, horizontal_spacing=0.03)

    for idx, p in enumerate(params):
        r, c = idx // cols + 1, idx % cols + 1
        zp = z[p]
        log_z = p in _ENV_LOG and bool(np.all(zp > 0))
        fig.add_trace(go.Surface(
            x=n_arr, y=v_arr, z=zp, colorscale="Viridis", showscale=False,
            opacity=0.9, name=p, showlegend=False,
            hovertemplate=("N = %{x:.0f} RPM<br>V = %{y:.3g} L<br>"
                           + p + " = %{z:.3g}<extra></extra>"),
            contours={"z": {"show": True, "usecolormap": True,
                            "project": {"z": True}}},
        ), row=r, col=c)
        if log_z:
            # Translucent planes at the 0.1 / 1.0 mixing-sensitivity thresholds.
            for thr, col_ in ((0.1, "orange"), (1.0, "red")):
                fig.add_trace(go.Surface(
                    x=n_arr, y=v_arr, z=np.full_like(zp, thr),
                    colorscale=[[0, col_], [1, col_]], showscale=False,
                    opacity=0.25, hoverinfo="skip", showlegend=False), row=r, col=c)
        fig.add_trace(go.Scatter3d(
            x=[state.va_n_rpm], y=[state.va_v_l], z=[current[p]], mode="markers",
            marker={"symbol": "diamond", "size": 7, "color": "red",
                    "line": {"width": 1, "color": "black"}},
            name="Operating point", legendgroup="op", showlegend=(idx == 0),
        ), row=r, col=c)
        fig.update_scenes(
            xaxis={"title": "N (RPM)"}, yaxis={"title": "V (L)"},
            zaxis={"title": p, "type": "log" if log_z else "linear"},
            camera={"eye": {"x": 1.6, "y": -1.6, "z": 0.9}},
            row=r, col=c)

    fig_height = max(360, rows * 360)
    fig.update_layout(
        height=fig_height, margin={"t": 60, "b": 10, "l": 0, "r": 0},
        legend={"orientation": "h", "y": 1.02, "yanchor": "bottom",
                "x": 0.5, "xanchor": "center"})
    state.va_surf_fig = fig
    state.va_surf_class = f"env-rows-{min(rows, 8)}"
    state.va_surf_caption = (
        f"**Response surfaces** — N = {n_arr[0]:.0f}–{n_arr[-1]:.0f} RPM × "
        f"V = {v_min:.3g}–{v_max:.3g} L ({_SURF_N_PTS}×{_SURF_V_PTS} grid)")


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------
page = Markdown(
    inject_icons("""
# __ICON:Vessel_Assessment__Vessel Assessment

<|{va_status}|text|>

<|part|height=18px|>

<|part|class_name=va-card|
## 1. Vessel & System
<|layout|columns=3 2|
<|part|
<|{va_reactor}|selector|lov={reactor_options}|dropdown|label=Vessel|on_change=on_va_reactor_change|>

<|layout|columns=1 1 1|
<|{va_T}|number|label=Temperature (°C)|on_change=on_va_sys_change|>

<|{va_P}|number|label=Pressure (atm)|on_change=on_va_sys_change|>

<|{va_T_cool}|number|label=Coolant temp (°C)|on_change=on_va_input_change|>
|>

<|layout|columns=1 1|
<|{va_n_rpm}|number|label=Agitation speed N (RPM)|on_change=on_va_input_change|>

<|{va_v_l}|number|label=Working volume (L)|on_change=on_va_input_change|>
|>

<|{va_fed_mode}|toggle|lov={va_fed_mode_options}|label=Fed-batch|class_name=onoff-toggle|on_change=on_va_input_change|>

<|part|render={va_fed_mode == "On"}|
Feed inputs unlock the **mesomixing** assessment (feed-plume dispersion).
<|layout|columns=1 1 1|
<|{va_feed_rate}|number|label=Feed rate (mL/min)|on_change=on_va_input_change|>

<|{va_feed_diam}|number|label=Feed pipe ID (mm)|on_change=on_va_input_change|>

<|{va_feed_location}|selector|lov={va_feed_location_options}|dropdown|label=Feed location|on_change=on_va_input_change|>
|>
|>

<|Advanced: vessel geometry overrides|expandable|expanded=False|
<|layout|columns=1 1 1 1|
<|{va_d_tank}|number|label=D_tank (m)|on_change=on_va_input_change|>

<|{va_d_imp}|number|label=D_imp (m)|on_change=on_va_input_change|>

<|{va_np}|number|label=Np|on_change=on_va_input_change|>

<|{va_nq}|number|label=Nq|on_change=on_va_input_change|>
|>
|>
|>

<|part|
<|part|content={va_viewer_html}|height=400px|>
|>
|>
|>

<|part|class_name=va-card|
## 2. Phases
<|layout|columns=1 1 1|gap=16px|class_name=phase-grid|
<|part|class_name=phase-panel|
### __ICON:Fluid_Database__Liquid / Solvent
<|{va_fluid}|selector|lov={fluid_options}|dropdown|label=Solvent / fluid|on_change=on_va_fluid_change|>

<|layout|columns=1 1|
<|{va_rho}|number|label=ρ (kg/m³)|on_change=on_va_input_change|>

<|{va_mu}|number|label=μ (Pa·s)|on_change=on_va_input_change|>

<|{va_dmol}|number|label=D_mol (m²/s)|on_change=on_va_input_change|>

<|{va_sigma}|number|label=σ (N/m)|on_change=on_va_input_change|>
|>
|>

<|part|class_name=phase-panel|
### __ICON:Particle_Database__Solid
<|{va_sl_mode}|toggle|lov={va_sl_mode_options}|label=Include solid particles|class_name=onoff-toggle|on_change=on_va_input_change|>

<|part|render={va_sl_mode == "On"}|
<|{va_particle}|selector|lov={particle_options}|dropdown|label=Particle|on_change=on_va_particle_change|>

<|layout|columns=1 1|
<|{va_rho_p}|number|label=ρ_p (kg/m³)|on_change=on_va_input_change|>

<|{va_d50}|number|label=d50 (µm)|on_change=on_va_input_change|>

<|{va_phi}|number|label=Shape factor φ|on_change=on_va_input_change|>

<|{va_x_wt}|number|label=Solids loading (wt-%)|on_change=on_va_input_change|>
|>

<|layout|columns=1 1 1|
<|{va_szw}|number|label=Zwietering S|on_change=on_va_input_change|>

<|{va_gmb_z}|number|label=GMB z|on_change=on_va_input_change|>

<|{va_cd}|number|label=C/D|on_change=on_va_input_change|>
|>
|>

<|part|render={va_sl_mode == "Off"}|class_name=phase-hint|
Enable to check off-bottom suspension (just-suspended speed) and solid–liquid mass transfer.
|>
|>

<|part|class_name=phase-panel|
### 🫧 Gas
<|{va_gas_mode}|toggle|lov={va_gas_mode_options}|label=Include gas phase|class_name=onoff-toggle|on_change=on_va_input_change|>

<|part|render={va_gas_mode == "On"}|
<|{va_gas_transfer}|toggle|lov={va_gas_transfer_options}|label=Mass-transfer mode|on_change=on_va_input_change|>

<|part|render={va_gas_transfer == "Sparging"}|
<|{va_vs}|number|label=Superficial gas velocity v_s (m/s)|on_change=on_va_input_change|>

<|{va_coalescing}|toggle|lov={va_coalescing_options}|label=Coalescence|on_change=on_va_input_change|>
|>

<|part|render={va_gas_transfer == "Headspace"}|class_name=phase-hint|
Gas–liquid transfer through the free surface (surface kLa).
|>
|>

<|part|render={va_gas_mode == "Off"}|class_name=phase-hint|
Enable to include gas–liquid mass transfer (headspace or sparged) in the Damköhler screen.
|>
|>
|>
|>

<|part|class_name=va-card|
## 3. Reaction
<|layout|columns=1 2|
<|{va_reaction_source}|selector|lov={reaction_source_options}|dropdown|label=Reaction source|on_change=on_va_reaction_source_change|>

<|{va_reaction}|selector|lov={va_reaction_options}|dropdown|label=Reaction|on_change=on_va_reaction_change|>
|>

<|{va_rxn_model}|text|mode=markdown|>

**Rate law:**
<|part|content={va_rxn_law}|height=54px|>

<|{va_rxn_scheme}|text|class_name=scheme-box|>

#### Kinetics (editable)
<|layout|columns=1 1 1 1|
<|{va_k}|number|label=Rate constant k|on_change=on_va_input_change|>

<|{va_c0}|number|label=C0 (mol/L)|on_change=on_va_input_change|>

<|{va_trxn}|number|label=t_rxn (s, 0 = auto)|on_change=on_va_input_change|>

<|{va_dH}|number|label=ΔH_rxn (kJ/mol)|on_change=on_va_input_change|>
|>
|>

<|part|class_name=va-card|
## 4. Correlations
Choose the correlation source used for the assessment. Only sources registered
for the selected vessel are offered.

<|layout|columns=1 2|
<|{va_corr_mode}|selector|lov={va_corr_options}|dropdown|label=Correlation source|on_change=on_va_input_change|>

<|{va_corr_status}|text|class_name=phase-hint|>
|>
|>

<|Compute Assessment|button|on_action=on_va_compute|class_name={va_compute_class}|>

<|part|render={va_stale}|
**⚠️ Inputs changed since the last run — click _Compute Assessment_ to refresh the results.**
|>

<|part|render={va_result_ready}|
<|part|class_name=va-card|
## Results
### Hydrodynamics
<|{va_hydro_df}|table|width=100%|show_all|>

<|part|render={not va_stale}|
<|Download hydrodynamics CSV|file_download|content={va_hydro_csv}|name=vessel_assessment_hydrodynamics.csv|label=Download hydrodynamics CSV|>
|>

<|{va_corr_applicability}|text|mode=markdown|>

### Mixing sensitivity (Damköhler)
<|{va_assess}|text|mode=markdown|>

<|{va_dam_df}|table|width=100%|show_all|>

<|part|render={not va_stale}|
<|Download Damköhler CSV|file_download|content={va_dam_csv}|name=vessel_assessment_damkohler.csv|label=Download Damköhler CSV|>
|>

<|part|render={len(va_mt_df) > 0}|
### Mass-transfer capacity versus kinetic demand
The capacity ratio is a preliminary screen using **kLa / (1/t<sub>rxn</sub>)**.
Confirm the result with solubility, phase composition, and concentration driving-force data.
<|{va_mt_df}|table|width=100%|show_all|>

<|part|render={not va_stale}|
<|Download mass-transfer CSV|file_download|content={va_mt_csv}|name=vessel_assessment_mass_transfer.csv|label=Download mass-transfer CSV|>
|>
|>

<|part|render={va_sl_mode == "On"}|
### Solid suspension and dissolution
<|{va_sl_df}|table|width=100%|show_all|>

<|part|render={not va_stale}|
<|Download solids CSV|file_download|content={va_sl_csv}|name=vessel_assessment_solids.csv|label=Download solids CSV|>
|>
|>

### Heat balance
<|part|render={len(va_heat_df) > 0}|
<|{va_heat_df}|table|width=100%|show_all|rebuild|>

<|part|render={not va_stale}|
<|Download heat-balance CSV|file_download|content={va_heat_csv}|name=vessel_assessment_heat_balance.csv|label=Download heat-balance CSV|>
|>
|>

<|part|render={len(va_heat_df) == 0}|class_name=phase-hint|
No heat of reaction set (ΔH = 0) — enter ΔH<sub>rxn</sub> in Section 3 to run the heat-balance check.
|>
|>

<|part|class_name=va-card|
## Operating Envelope
Each parameter is swept across the vessel's RPM range to form an **operating
region**: the solid line is the boundary at maximum fill volume, the dotted line
at minimum fill volume, and the shaded band is the reachable envelope between
them. The red ★ marks the current operating point. Dashed lines on the Damköhler
panels mark the 0.1 and 1.0 mixing-sensitivity thresholds.

<|{va_env_params}|selector|lov={va_env_params_options}|multiple|dropdown|label=Parameters to plot|on_change=on_va_env_change|>

<|{va_env_caption}|text|mode=markdown|>

<|chart|figure={va_env_fig}|class_name={va_env_class}|rebuild=True|>
|>

<|part|class_name=va-card|
## Response Surfaces (3D)
Each parameter selected above is evaluated over the full **agitation speed ×
fill volume** window of the vessel as an interactive 3D surface (drag to rotate,
scroll to zoom, hover for values). The red ◆ marks the current operating point;
translucent planes on the Damköhler panels mark the 0.1 and 1.0
mixing-sensitivity thresholds. Surfaces are generated on demand because the
N × V grid is computationally heavier than the envelope sweep.

<|Generate 3D surfaces|button|on_action=on_va_surface|class_name={va_surf_btn_class}|>

<|part|render={va_surf_stale}|
**⚠️ Results or parameter selection changed since the surfaces were built — click _Generate 3D surfaces_ to refresh.**
|>

<|part|render={va_surf_ready}|
<|{va_surf_caption}|text|mode=markdown|>

<|chart|figure={va_surf_fig}|class_name={va_surf_class}|rebuild=True|>
|>
|>

<|part|class_name=va-card|
## Export & Save
Generate a PDF capturing the system configuration, hydrodynamics, Damköhler
mixing-sensitivity, optional solid-suspension / heat balance, and the operating
envelope chart — or save the computed case to the **Recorded Results** page for
bulk export and comparison.

<|layout|columns=1 1|
<|Generate PDF report|button|on_action=on_va_export_pdf|class_name=compute-btn|>

<|Save results to Recorded Results|button|on_action=on_va_save_results|>
|>

<|part|render={va_pdf_ready}|
<|Download PDF|file_download|content={va_pdf_bytes}|name={va_pdf_name}|label=Download PDF|>
|>
|>
|>

<|part|class_name=va-card|
## Solve for
Find the agitation speed (or working volume) that gives a target value of a
hydrodynamic or mass-transfer parameter in the selected vessel. The other
variable is held at its Section 1 input; fluid, phase, reaction and
correlation settings above are used. Speed is scanned from 0.25× the minimum to
2× the maximum rated speed; volume is scanned across the vessel fill range.

<|layout|columns=1 1 1|
<|{va_solve_var}|selector|lov={va_solve_var_options}|dropdown|label=Solve for|>

<|{va_solve_param}|selector|lov={va_solve_param_options}|dropdown|label=Target parameter|>

<|{va_solve_target}|number|label=Target value|>
|>

<|Solve|button|on_action=on_va_solve|class_name=compute-btn|>

<|{va_solve_status}|text|mode=markdown|>

<|part|render={len(va_solve_df) > 0}|
<|{va_solve_df}|table|width=100%|show_all|rebuild|>
|>

<|part|render={va_solve_found}|
<|Apply solution to operating inputs|button|on_action=on_va_solve_apply|>
|>
|>
""")
)
