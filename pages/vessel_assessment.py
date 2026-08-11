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

from utils.calculations import (
    compute_damkohler_numbers,
    estimate_U_detailed,
    estimate_jacket_area,
    heat_balance_assessment,
    heat_generation_rate,
    heat_removal_capacity,
    liquid_height_from_volume,
    mesomixing_time,
    particle_suspension_criterion,
    reaction_rate_mol_per_s,
    zwietering_njs,
)
from utils.solvent_properties import (
    get_properties,
    is_known_solvent,
    list_solvents,
    resolve_solvent_name,
)
from utils.rom_registry import available_modes, compute_reactor_hydro_with_mode
from utils.report_builder import build_vessel_assessment_pdf, report_filename
from vessel_media import build_vessel_viewer_html, media_caption

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
reactors_df = pd.read_csv(DATA_DIR / "reactors.csv")
reactions_df = pd.read_csv(DATA_DIR / "reactions.csv")
particles_df = pd.read_csv(DATA_DIR / "particles.csv")
fluids_df = pd.read_csv(DATA_DIR / "fluids.csv")

# Correlation-source display labels <-> registry keys.
_CORR_LABEL_TO_KEY = {
    "Empirical (literature)": "Literature",
    "Experimental": "Experimental",
    "Reduced-order (CFD)": "ROM",
}
_CORR_KEY_TO_LABEL = {v: k for k, v in _CORR_LABEL_TO_KEY.items()}

# 3D vessel viewer render height (px). The Taipy `part` pane is sized a little
# taller so the image is fully visible without scrolling.
VIEWER_H = 380


# ---------------------------------------------------------------------------
# Data helpers
# ---------------------------------------------------------------------------
def _sf(val, default=0.0) -> float:
    """Safe float conversion (NaN / blank -> default)."""
    try:
        f = float(val)
        return default if np.isnan(f) else f
    except (TypeError, ValueError):
        return default


def _avg_range(row: pd.Series, min_key: str, max_key: str, fallback: float) -> float:
    """Midpoint of a reactor's min/max range (e.g. fill volume, agitation speed).

    Falls back to whichever bound is available, then to ``fallback`` when neither
    is defined."""
    lo = _sf(row.get(min_key), 0.0)
    hi = _sf(row.get(max_key), 0.0)
    if lo > 0 and hi > 0:
        return (lo + hi) / 2.0
    if hi > 0:
        return hi
    if lo > 0:
        return lo
    return fallback


def _reactor_row(name: str) -> pd.Series:
    row = reactors_df[reactors_df["reactor_name"].astype(str) == str(name)]
    return row.iloc[0] if not row.empty else pd.Series(dtype=object)


def _reaction_row(name: str) -> pd.Series:
    row = reactions_df[reactions_df["reaction_name"].astype(str) == str(name)]
    return row.iloc[0] if not row.empty else pd.Series(dtype=object)


def _particle_row(name: str) -> pd.Series:
    row = particles_df[particles_df["particle_name"].astype(str) == str(name)]
    return row.iloc[0] if not row.empty else pd.Series(dtype=object)


def _reactor_id(name: str) -> str:
    """Return the ``reactor_id`` for a reactor name (for image/3D lookup)."""
    row = _reactor_row(name)
    if row.empty or "reactor_id" not in reactors_df.columns:
        return ""
    return str(row.get("reactor_id", "") or "")


def _fluid_props(name: str, T_C: float, P_atm: float = 1.0) -> dict:
    """Return {rho, mu, D_mol, sigma} for a solvent (at T, P) or custom fluid."""
    if is_known_solvent(name):
        canonical = resolve_solvent_name(name) or name
        p = get_properties(canonical, T_C, P_atm)
        return {"rho": p["rho_kg_m3"], "mu": p["mu_Pa_s"],
                "D_mol": p["D_mol_m2_s"], "sigma": p["surface_tension_N_m"]}
    row = fluids_df[fluids_df["fluid_name"].astype(str) == str(name)]
    if not row.empty:
        r = row.iloc[0]
        return {"rho": _sf(r.get("rho_kg_m3"), 1000.0),
                "mu": _sf(r.get("mu_Pa_s"), 0.001),
                "D_mol": _sf(r.get("D_mol_m2_s"), 2.3e-9),
                "sigma": _sf(r.get("surface_tension_N_m"), 0.072)}
    return {"rho": 1000.0, "mu": 0.001, "D_mol": 2.3e-9, "sigma": 0.072}


def _auto_t_rxn(order: str, k: float, C0: float, t_rxn: float) -> float:
    """Return characteristic reaction time, auto-computing from k if needed."""
    if t_rxn and t_rxn > 0:
        return t_rxn
    if k and k > 0:
        if str(order) in ("1", "pseudo-1"):
            return 1.0 / k
        if str(order) in ("2", "pseudo-2") and C0 > 0:
            return 1.0 / (k * C0)
    return 0.0


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
    if state.va_gas_mode == "On" and state.va_gas_transfer == "Sparging":
        return _sf(state.va_vs, 0.0), (state.va_coalescing == "Coalescing")
    return 0.0, True


def _refresh_corr(state):
    """Refresh the correlation-source options/status for the selected vessel."""
    modes = available_modes(state.va_reactor)
    labels = [_CORR_KEY_TO_LABEL[m] for m in modes]
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
reaction_options = sorted(reactions_df["reaction_name"].dropna().astype(str).unique().tolist())
fluid_options = sorted(list_solvents() + fluids_df["fluid_name"].dropna().astype(str).tolist())
particle_options = sorted(particles_df["particle_name"].dropna().astype(str).unique().tolist())

# ---------------------------------------------------------------------------
# State — Section 1: Vessel & System
# ---------------------------------------------------------------------------
va_reactor = "RX-027" if "RX-027" in reactor_options else reactor_options[0]
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
va_np = _sf(_r0.get("Np"), 5.0)
va_nq = _sf(_r0.get("Nq"), 0.79)
va_v_l = _avg_range(_r0, "V_L_min", "V_L_max", _sf(_r0.get("V_L"), 1.0))

# Operation mode — fed-batch (unlocks feed inputs feeding the mesomixing check)
va_fed_mode = "Off"
va_fed_mode_options = ["Off", "On"]
va_feed_rate = 5.0
va_feed_diam = 3.0
va_feed_location = "Bulk (mid-liquid)"
va_feed_location_options = ["Near impeller", "Bulk (mid-liquid)", "Surface"]

# ---------------------------------------------------------------------------
# State — Section 2: Phases
# ---------------------------------------------------------------------------
# Liquid / solvent (always present)
va_fluid = fluid_options[0]
_fp0 = _fluid_props(va_fluid, va_T, va_P)
va_rho = _fp0["rho"]
va_mu = _fp0["mu"]
va_dmol = _fp0["D_mol"]
va_sigma = _fp0["sigma"]

# Solid (optional)
va_sl_mode = "Off"
va_sl_mode_options = ["Off", "On"]
va_particle = particle_options[0] if particle_options else ""
_p0 = _particle_row(va_particle) if particle_options else pd.Series(dtype=object)
va_rho_p = _sf(_p0.get("rho_p_kg_m3"), 1500.0)
va_d50 = _sf(_p0.get("d50_um"), 50.0)
va_phi = _sf(_p0.get("shape_factor"), 1.0)
va_x_wt = 5.0
va_szw = 5.5

# Gas (optional)
va_gas_mode = "Off"
va_gas_mode_options = ["Off", "On"]
va_gas_transfer = "Headspace"
va_gas_transfer_options = ["Headspace", "Sparging"]
va_vs = 0.005
va_coalescing = "Coalescing"
va_coalescing_options = ["Coalescing", "Non-coalescing"]

# ---------------------------------------------------------------------------
# State — Section 3: Reaction
# ---------------------------------------------------------------------------
va_reaction = reaction_options[0] if reaction_options else ""
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
va_corr_options = [_CORR_KEY_TO_LABEL[m] for m in _modes0]
va_corr_mode = va_corr_options[0]
_extra0 = [m for m in _modes0 if m != "Literature"]
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
va_assess = ""
va_sl_df = pd.DataFrame(columns=["Parameter", "Value", "Units"])
va_heat_df = pd.DataFrame(columns=["Parameter", "Value", "Units"])
va_result_ready = False
va_env_fig = go.Figure()
va_compute_class = "compute-btn"   # red until an assessment is run; blue after
va_stale = False                   # True when inputs change after a run

va_pdf_bytes = b""
va_pdf_name = "Vessel_Assessment.pdf"
va_pdf_ready = False


# ---------------------------------------------------------------------------
# Change handlers — load defaults
# ---------------------------------------------------------------------------
def on_va_reactor_change(state):
    row = _reactor_row(state.va_reactor)
    state.va_d_tank = _sf(row.get("D_tank_m"), state.va_d_tank)
    state.va_d_imp = _sf(row.get("D_imp_m"), state.va_d_imp)
    state.va_n_rpm = _avg_range(row, "N_rpm_min", "N_rpm_max", state.va_n_rpm)
    state.va_np = _sf(row.get("Np"), state.va_np)
    state.va_nq = _sf(row.get("Nq"), state.va_nq)
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
        state.va_pdf_ready = False


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


# ---------------------------------------------------------------------------
# Core compute
# ---------------------------------------------------------------------------
def _hydro_at(state, n_rpm: float, v_l: float) -> dict:
    """Run the hydro engine at a given RPM and fill volume using the selected
    correlation source and gas settings."""
    row = _reactor_row(state.va_reactor)
    h_max = _sf(row.get("H_max_m"), _sf(row.get("H_m"), state.va_d_tank))
    dish = str(row.get("bottom_dish", "") or "")
    h_liq = liquid_height_from_volume(v_l, state.va_d_tank, h_max, dish)
    v_s, coal = _gas_params(state)
    mode_key = _CORR_LABEL_TO_KEY.get(state.va_corr_mode, "Literature")
    hydro, _sources = compute_reactor_hydro_with_mode(
        mode_key, state.va_reactor,
        N=n_rpm / 60.0, D_imp=state.va_d_imp, D_tank=state.va_d_tank, H=h_liq,
        rho=state.va_rho, mu=state.va_mu, Np=state.va_np, Nq=state.va_nq,
        v_s=v_s, coalescing=coal, D_mol=state.va_dmol)
    return hydro


def on_va_compute(state):
    t_rxn = _auto_t_rxn(state.va_order, state.va_k, state.va_c0, state.va_trxn)
    if t_rxn <= 0:
        state.va_status = "Provide a reaction time or rate constant (> 0) to compute Damköhler numbers."
        notify(state, "E", state.va_status)
        return

    hydro = _hydro_at(state, state.va_n_rpm, state.va_v_l)

    # Solid-liquid suspension (optional)
    kla_sl = 0.0
    if state.va_sl_mode == "On":
        d_p = state.va_d50 * 1e-6
        nu = state.va_mu / state.va_rho if state.va_rho > 0 else 0.0
        delta_rho = abs(state.va_rho_p - state.va_rho)
        n_js_rps = zwietering_njs(state.va_szw, nu, d_p, delta_rho,
                                  state.va_rho, state.va_x_wt, state.va_d_imp)
        n_js_rpm = n_js_rps * 60.0
        n_rps = state.va_n_rpm / 60.0
        assess = particle_suspension_criterion(n_rps, n_js_rps)
        state.va_sl_df = pd.DataFrame([
            {"Parameter": "Just-suspended speed N_js", "Value": f"{n_js_rpm:.1f}", "Units": "RPM"},
            {"Parameter": "Operating speed N", "Value": f"{state.va_n_rpm:.1f}", "Units": "RPM"},
            {"Parameter": "N / N_js", "Value": f"{(state.va_n_rpm / n_js_rpm) if n_js_rpm > 0 else 0:.2f}", "Units": "–"},
            {"Parameter": "Suspension state", "Value": assess, "Units": "–"},
        ])
    else:
        state.va_sl_df = pd.DataFrame(columns=["Parameter", "Value", "Units"])

    # Gas-liquid mass transfer only counts when a gas phase is active.
    if state.va_gas_mode == "On":
        kla_da = hydro["kLa (1/s)"]
        klasurf_da = hydro["kLa_surface (1/s)"]
    else:
        kla_da = klasurf_da = 0.0

    dam = compute_damkohler_numbers(
        hydro["Blend time 95% (s)"], hydro["Micromix time t_E (s)"], t_rxn,
        kLa=kla_da, kLa_surface=klasurf_da, kLa_SL=kla_sl)

    # Hydrodynamics KPI table
    state.va_hydro_df = pd.DataFrame(
        [{"Parameter": name, "Value": f"{hydro[key]:,.4g}", "Units": unit}
         for key, name, unit in _HYDRO_ROWS])

    def _regime(da: float) -> str:
        if da <= 0:
            return "—"
        if da < 0.1:
            return "🟢 Mixing-insensitive"
        if da < 1.0:
            return "🟡 Transitional"
        return "🔴 Mixing-limited"

    # Mesomixing (only for fed-batch): feed-plume dispersion vs reaction. The
    # local energy dissipation depends on where the feed enters the vessel.
    da_meso = 0.0
    if state.va_fed_mode == "On":
        d_feed = _sf(state.va_feed_diam, 0.0) / 1000.0  # mm -> m
        loc = str(state.va_feed_location)
        if loc.startswith("Near impeller"):
            eps_feed = hydro["ε_max (W/kg)"]
        elif loc.startswith("Surface"):
            eps_feed = 0.2 * hydro["P/V (W/kg)"]
        else:  # Bulk / mid-liquid
            eps_feed = hydro["P/V (W/kg)"]
        t_meso = mesomixing_time(eps_feed, d_feed)
        da_meso = (t_meso / t_rxn) if (t_rxn > 0 and np.isfinite(t_meso)) else 0.0

    dam_rows = [
        {"Type": "Macromixing (bulk blending)", "Damköhler": "Da_macro", "Value": f"{dam['Da_macro']:.3g}", "Regime": _regime(dam["Da_macro"])},
    ]
    if state.va_fed_mode == "On":
        dam_rows.append({"Type": "Mesomixing (feed dispersion)", "Damköhler": "Da_meso", "Value": f"{da_meso:.3g}", "Regime": _regime(da_meso)})
    dam_rows.append({"Type": "Micromixing (engulfment)", "Damköhler": "Da_micro", "Value": f"{dam['Da_micro']:.3g}", "Regime": _regime(dam["Da_micro"])})
    if state.va_gas_mode == "On":
        dam_rows.append({"Type": "Gas–liquid mass transfer", "Damköhler": "Da_GL", "Value": f"{dam['Da_GL']:.3g}", "Regime": _regime(dam["Da_GL"])})
    if state.va_sl_mode == "On":
        dam_rows.append({"Type": "Solid–liquid mass transfer", "Damköhler": "Da_SL", "Value": f"{dam['Da_SL']:.3g}", "Regime": _regime(dam["Da_SL"])})
    state.va_dam_df = pd.DataFrame(dam_rows)
    state.va_assess = f"**Assessment:** {dam['Assessment']}"

    # Heat balance (optional — only when a heat of reaction is set)
    if abs(state.va_dH) > 0:
        r_mol_s = reaction_rate_mol_per_s(state.va_order, state.va_k, state.va_c0, state.va_v_l)
        q_gen = heat_generation_rate(state.va_dH, r_mol_s)
        row = _reactor_row(state.va_reactor)
        h_max = _sf(row.get("H_max_m"), _sf(row.get("H_m"), state.va_d_tank))
        dish = str(row.get("bottom_dish", "") or "")
        h_liq = liquid_height_from_volume(state.va_v_l, state.va_d_tank, h_max, dish)
        area = estimate_jacket_area(state.va_d_tank, h_liq, dish)
        u_val, _warn = estimate_U_detailed(
            N_rps=state.va_n_rpm / 60.0, D_imp=state.va_d_imp, D_tank=state.va_d_tank,
            rho=state.va_rho, mu=state.va_mu,
            material=str(row.get("shell_material", "") or ""),
            lining_material=str(row.get("lining_material", "") or ""),
            wall_thickness_mm=_sf(row.get("wall_thickness_mm"), 0.0),
            fluid_name=state.va_fluid)
        q_cool = heat_removal_capacity(u_val, area, abs(state.va_T - state.va_T_cool))
        state.va_heat_df = pd.DataFrame([
            {"Parameter": "Heat generation Q_gen", "Value": f"{q_gen:,.1f}", "Units": "W"},
            {"Parameter": "Overall U", "Value": f"{u_val:,.1f}", "Units": "W/m²·K"},
            {"Parameter": "Jacket area A", "Value": f"{area:,.4g}", "Units": "m²"},
            {"Parameter": "Cooling capacity Q_cool", "Value": f"{q_cool:,.1f}", "Units": "W"},
            {"Parameter": "Balance", "Value": heat_balance_assessment(q_gen, q_cool), "Units": "–"},
        ])
    else:
        state.va_heat_df = pd.DataFrame(columns=["Parameter", "Value", "Units"])

    _build_envelope(state, t_rxn)

    state.va_result_ready = True
    state.va_compute_class = "compute-btn-ok"
    state.va_stale = False
    state.va_pdf_ready = False
    state.va_status = (f"Computed at {state.va_n_rpm:.0f} RPM, {state.va_v_l:.3g} L "
                       f"({state.va_corr_mode}) — Re = {hydro['Re']:,.0f}, "
                       f"P/V = {hydro['P/V (W/L)']:.3g} W/L.")
    notify(state, "S", "Assessment computed.")


def _build_envelope(state, t_rxn: float):
    """Plot each SELECTED parameter as an operating *region*: an RPM sweep
    bounded by the vessel's minimum and maximum fill volume, with the current
    operating point marked. The subplot grid adapts to the number of chosen
    parameters."""
    params = [p for p in (state.va_env_params or []) if p in va_env_params_options]
    if not params:
        params = ["Da_macro"]
    row = _reactor_row(state.va_reactor)
    n_lo = _sf(row.get("N_rpm_min"), max(state.va_n_rpm * 0.1, 10.0))
    n_hi = _sf(row.get("N_rpm_max"), state.va_n_rpm)
    if n_hi <= n_lo:
        n_lo, n_hi = state.va_n_rpm * 0.2, state.va_n_rpm * 1.2
    n_arr = np.linspace(n_lo, n_hi, 40)

    # Fill-volume range: from the reactor DB, falling back around the current V.
    v_min = _sf(row.get("V_L_min"), 0.0)
    v_max = _sf(row.get("V_L_max"), 0.0)
    if v_max <= v_min or v_min <= 0:
        v_min = max(state.va_v_l * 0.5, 1e-6)
        v_max = max(state.va_v_l, v_min * 1.5)

    def _val(h: dict, d: dict, p: str) -> float:
        if p == "Da_macro":
            return d["Da_macro"]
        if p == "Da_micro":
            return d["Da_micro"]
        if p == "Da_GL":
            return d["Da_GL"]
        return h[p]

    def _sweep(v_l: float) -> dict:
        out = {p: [] for p in params}
        for n in n_arr:
            h = _hydro_at(state, n, v_l)
            d = compute_damkohler_numbers(
                h["Blend time 95% (s)"], h["Micromix time t_E (s)"], t_rxn,
                kLa=h["kLa (1/s)"], kLa_surface=h["kLa_surface (1/s)"])
            for p in params:
                out[p].append(_val(h, d, p))
        return {p: np.array(v) for p, v in out.items()}

    hi_v = _sweep(v_max)
    lo_v = _sweep(v_min)

    # Current operating point (current RPM at current fill volume).
    hc = _hydro_at(state, state.va_n_rpm, state.va_v_l)
    dc = compute_damkohler_numbers(
        hc["Blend time 95% (s)"], hc["Micromix time t_E (s)"], t_rxn,
        kLa=hc["kLa (1/s)"], kLa_surface=hc["kLa_surface (1/s)"])
    current = {p: _val(hc, dc, p) for p in params}

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
        # Max-volume boundary (solid) and min-volume boundary (dotted).
        fig.add_trace(go.Scatter(
            x=n_arr, y=y_hi, mode="lines", line={"width": 2, "color": "#000000"},
            name=f"V_max = {v_max:.0f} L", legendgroup="vmax",
            showlegend=first), row=r, col=c)
        fig.add_trace(go.Scatter(
            x=n_arr, y=y_lo, mode="lines",
            line={"width": 2, "color": "#000000", "dash": "dot"},
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
        plot_bgcolor="rgba(225,37,27,0.06)", paper_bgcolor="white",
        legend={"orientation": "h", "y": _legend_y, "yanchor": "bottom",
                "x": 0.5, "xanchor": "center"})
    state.va_env_fig = fig
    state.va_env_class = f"env-rows-{min(rows, 8)}"
    state.va_env_caption = (f"**Operating envelope** — RPM sweep across "
                            f"V = {v_min:.0f}–{v_max:.0f} L")


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------
page = Markdown(
    """
# 🌀 Vessel Assessment

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

<|layout|columns=1 2|
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

### 💧 Liquid / Solvent
<|layout|columns=1 1 1 1 1|
<|{va_fluid}|selector|lov={fluid_options}|dropdown|label=Solvent / fluid|on_change=on_va_fluid_change|>

<|{va_rho}|number|label=ρ (kg/m³)|on_change=on_va_input_change|>

<|{va_mu}|number|label=μ (Pa·s)|on_change=on_va_input_change|>

<|{va_dmol}|number|label=D_mol (m²/s)|on_change=on_va_input_change|>

<|{va_sigma}|number|label=σ (N/m)|on_change=on_va_input_change|>
|>

### 🟤 Solid
<|{va_sl_mode}|toggle|lov={va_sl_mode_options}|label=Include solid particles|class_name=onoff-toggle|on_change=on_va_input_change|>

<|part|render={va_sl_mode == "On"}|
<|layout|columns=1 1 1 1 1|
<|{va_particle}|selector|lov={particle_options}|dropdown|label=Particle|on_change=on_va_particle_change|>

<|{va_rho_p}|number|label=ρ_p (kg/m³)|on_change=on_va_input_change|>

<|{va_d50}|number|label=d50 (µm)|on_change=on_va_input_change|>

<|{va_phi}|number|label=Shape factor φ|on_change=on_va_input_change|>

<|{va_x_wt}|number|label=Solids loading X (wt-%)|on_change=on_va_input_change|>
|>
|>

### 🫧 Gas
<|{va_gas_mode}|toggle|lov={va_gas_mode_options}|label=Include gas phase|class_name=onoff-toggle|on_change=on_va_input_change|>

<|part|render={va_gas_mode == "On"}|
<|{va_gas_transfer}|toggle|lov={va_gas_transfer_options}|label=Mass-transfer mode|on_change=on_va_input_change|>

<|part|render={va_gas_transfer == "Sparging"}|
<|layout|columns=1 1|
<|{va_vs}|number|label=Superficial gas velocity v_s (m/s)|on_change=on_va_input_change|>

<|{va_coalescing}|toggle|lov={va_coalescing_options}|label=Coalescence|on_change=on_va_input_change|>
|>
|>
|>
|>

<|part|class_name=va-card|
## 3. Reaction
<|{va_reaction}|selector|lov={reaction_options}|dropdown|label=Reaction|on_change=on_va_reaction_change|>

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

<|{va_corr_mode}|selector|lov={va_corr_options}|dropdown|label=Correlation source|on_change=on_va_input_change|>

<|{va_corr_status}|text|>
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

### Mixing sensitivity (Damköhler)
<|{va_assess}|text|mode=markdown|>

<|{va_dam_df}|table|width=100%|show_all|>

<|part|render={va_sl_mode == "On"}|
### Solid suspension
<|{va_sl_df}|table|width=100%|show_all|>
|>

### Heat balance
<|{va_heat_df}|table|width=100%|show_all|>
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
## Export Report
Generate a PDF capturing the system configuration, hydrodynamics, Damköhler
mixing-sensitivity, optional solid-suspension / heat balance, and the operating
envelope chart.

<|Generate PDF report|button|on_action=on_va_export_pdf|class_name=compute-btn|>

<|part|render={va_pdf_ready}|
<|Download PDF|file_download|content={va_pdf_bytes}|name={va_pdf_name}|label=⬇️ Download PDF|>
|>
|>
|>
"""
)
