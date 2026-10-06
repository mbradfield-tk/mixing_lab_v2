"""Vessel Comparison page (Taipy).

Ported from the Streamlit ``7_Reactor_Comparison.py`` page. Compares the mixing
hydrodynamics of several vessels side-by-side. Each vessel's full operating
envelope is mapped from its RPM range and fill-volume band (four corner
conditions plus a swept boundary curve), for a shared fluid + reaction system.

Sections (all in Takeda ``va-card`` panes):

1. **Reactors & conditions** — pick vessels to compare, the fluid (T/P),
   the reaction (for Damkohler numbers), gas velocity / coalescence, and the
   coolant temperature.
2. **Options** — optionally include solid particles (shared particle + loading)
   and, when the reaction has a heat of reaction, an automatic heat balance.
3. **Scale-up matching** — hold one parameter constant on a basis vessel and
   solve for the equivalent RPM (or fill volume) on every other vessel.

**Compute** then runs the four-corner envelope for every vessel and reports:
range-summary and 4-corner tables, a stir-speed reference table, overlaid
operating-envelope charts, a heat-balance summary, scale-up matching results,
scale-up impact ratios, a PDF report, and a save-to-Recorded-Results action.

Correlation source is selectable (literature, experimental or reduced-order CFD)
but limited to the sources registered for *every* selected vessel; solid-particle
properties are shared across the selection. Point evaluations come from
:mod:`core.operating_point`.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from taipy.gui import Markdown, notify

from utils.menu_icons import inject_icons
from utils.calculations import heat_balance_assessment
from utils.rom_registry import available_modes_multi
from utils.solvent_properties import SOLVENT_DB, resolve_solvent_name
from utils.report_builder import build_reactor_comparison_pdf, report_filename
from core import operating_point as op
from core import kinetics
from core import records
from core import scale_up
from core.records import (
    VesselGeometry,
    particle_row as _particle_row,
    range_midpoint as _avg,
    reactor_id as _reactor_id,
    reactor_row as _reactor_row,
    sf as _sf,
)
from pages import _db_common as db
from vessel_media import build_multi_vessel_viewer_html

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
reactors_df = pd.read_csv(DATA_DIR / "reactors.csv")
reactions_df = pd.read_csv(DATA_DIR / "reactions.csv")
particles_df = pd.read_csv(DATA_DIR / "particles.csv")
fluids_df = pd.read_csv(DATA_DIR / "fluids.csv")

RECORDED_CSV = DATA_DIR / "recorded_results.csv"

_N_INTERP = 40  # boundary-curve resolution per reactor
_PALETTE = ["#E1251B", "#1f77b4", "#2ca02c", "#9467bd", "#ff7f0e",
            "#17becf", "#8c564b", "#e377c2", "#5C6670", "#bcbd22"]

CORNER_LABELS = scale_up.CORNER_LABELS

# Parameters that can be plotted / summarised (subset present in the hydro+Da dict).
_BASE_PLOT_PARAMS = [
    "Power (W)", "P/V (W/L)", "Tip speed (m/s)", "Blend time 95% (s)",
    "Circulation time (s)", "Micromix time t_E (s)", "Kolmogorov η (µm)", "Re",
    "Avg shear rate (1/s)", "Max shear rate (1/s)", "Avg shear stress (Pa)",
    "Da_macro", "Da_micro", "Da_GL", "ε_max (W/kg)", "EDCF (W/kg/s)",
    "Torque (N·m)", "Froude number", "kLa (1/s)", "kLa_surface (1/s)",
]
_HEAT_PARAMS = ["Q_gen (W)", "Q_cool (W)", "U (W/m²·K)", "A_ht (m²)", "Q_gen/Q_cool (%)"]
_PARTICLE_PARAMS = ["N_js (RPM)", "N/N_js", "v_t (m/s)", "Re_p",
                    "k_SL (m/s)", "kLa_SL (1/s)", "Da_SL"]
_LOG_PARAMS = {"Da_macro", "Da_micro", "Da_meso", "Da_GL", "Da_SL"}
_DISPLAY_NAMES = {
    "Da_macro": "Macromixing (Da_macro)",
    "Da_micro": "Micromixing (Da_micro)",
    "Da_meso": "Mesomixing (Da_meso)",
    "Da_GL": "Gas–liquid transfer (Da_GL)",
    "Da_SL": "Solid–liquid transfer (Da_SL)",
    "Q_gen/Q_cool (%)": "Heat capacity (Q_gen/Q_cool %)",
}

SCALABLE_PARAMS = [
    "P/V (W/L)", "Tip speed (m/s)", "Blend time 95% (s)", "Micromix time t_E (s)",
    "Re", "kLa (1/s)", "kLa_surface (1/s)", "Avg shear rate (1/s)",
    "Max shear rate (1/s)", "Kolmogorov η (µm)", "EDCF (W/kg/s)", "Froude number",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _viewers_html(names) -> str:
    items = [(n, _reactor_id(n)) for n in (names or [])]
    return build_multi_vessel_viewer_html(items, height=260)


def _display(p: str) -> str:
    return _DISPLAY_NAMES.get(p, p)


def _corr_choices(names) -> tuple[list[str], str]:
    """Correlation-source labels shared by every selected vessel, plus a status note."""
    labels = [op.CORR_LABELS[m] for m in available_modes_multi(list(names or []))]
    if len(labels) > 1:
        return labels, "Sources available for every selected vessel: " + ", ".join(labels) + "."
    return labels, ("Only empirical (literature) correlations are shared by all selected "
                    "vessels. Experimental and reduced-order (CFD) sources appear once "
                    "fitted for every vessel in the selection.")


def _fluid_props(name: str, T_C: float, P_atm: float) -> tuple[float, float, float, bool, str]:
    """Return (rho, mu, D_mol, in_range, note)."""
    p = records.fluid_props(name, T_C, P_atm)
    return p["rho"], p["mu"], p["D_mol"], p["in_range"], p["note"]


# ---------------------------------------------------------------------------
# Option lists
# ---------------------------------------------------------------------------
reactor_options = reactors_df["reactor_name"].dropna().astype(str).tolist()
_solvent_names = sorted(SOLVENT_DB.keys())
_custom_names = fluids_df["fluid_name"].dropna().astype(str).tolist()
fluid_options = _solvent_names + _custom_names
reaction_class_options = db.reaction_names(reactions_df, "yes")
reaction_measured_options = db.reaction_names(reactions_df, "no")
reaction_source_options = ["Measured kinetics", "Reaction classes"]
reaction_options = reaction_measured_options or reaction_class_options
particle_options = particles_df["particle_name"].dropna().astype(str).tolist()
scale_solve_options = ["RPM (specify volume)", "Volume (specify RPM)"]
coal_options = ["Coalescing (pure liquid)", "Non-coalescing (electrolyte)"]


# ---------------------------------------------------------------------------
# State — Section 1: reactors & conditions
# ---------------------------------------------------------------------------
_DEFAULT_REACTORS = ["TMA EasyMax-102", "TMA 15 L Buchi", "Cambrex R-101", "Cambrex R-B01"]
vc_reactors = [r for r in _DEFAULT_REACTORS if r in reactor_options] \
    or reactor_options[: min(3, len(reactor_options))]
vc_fluid = ("Water" if "Water" in fluid_options
            else (fluid_options[0] if fluid_options else ""))
vc_T = 25.0
vc_P = 1.0
vc_reaction_source = reaction_source_options[0]
vc_reaction_options = reaction_options
vc_reaction = vc_reaction_options[0] if vc_reaction_options else ""
vc_T_cool = 15.0
vc_viewers_html = _viewers_html(vc_reactors)
vc_corr_options, vc_corr_status = _corr_choices(vc_reactors)
vc_corr_mode = vc_corr_options[0]

# Editable reaction conditions & kinetics (seeded from the database)
vc_rxn_order_options = kinetics.ORDER_OPTIONS
_kin_defaults = kinetics.kinetics_defaults


def _derive_trxn(order: str, k: float, C0: float, t_specified: float) -> float:
    # Falls back to 1 s so the comparison still runs when kinetics are incomplete.
    return kinetics.effective_t_rxn(order, k, C0, t_specified, fallback=1.0)


def _kin_caption(order: str, k: float, C0: float, t_spec: float, dH: float) -> str:
    t = _derive_trxn(order, k, C0, t_spec)
    basis = "specified" if t_spec > 0 else ("derived from k" if k > 0 else "fallback")
    txt = f"Effective reaction time **t_rxn = {t:.4g} s** ({basis})  •  ΔH = {dH:.1f} kJ/mol"
    if dH == 0.0:
        txt += " (heat balance disabled)"
    return txt


_kd0 = _kin_defaults(vc_reaction)
vc_rxn_order = _kd0["order"]
vc_rxn_k = _kd0["k"]
vc_rxn_c0 = _kd0["C0"]
vc_rxn_trxn = _kd0["t_rxn"]
vc_rxn_dh = _kd0["dH"]
vc_rxn_caption = _kin_caption(vc_rxn_order, vc_rxn_k, vc_rxn_c0, vc_rxn_trxn, vc_rxn_dh)

# Section 2: options
vc_onoff_options = ["Off", "On"]

# Solid particles
vc_incl_particles = "Off"
vc_particle = particle_options[0] if particle_options else ""
_pp0 = _particle_row(vc_particle) if particle_options else pd.Series(dtype=object)
vc_rho_p = _sf(_pp0.get("rho_p_kg_m3"), 1500.0)
vc_d50 = _sf(_pp0.get("d50_um"), 50.0)
vc_phi = _sf(_pp0.get("shape_factor"), 1.0)
vc_x_wt = 5.0
vc_szw = 5.5
vc_gmb_z = 3.0
vc_cd = 0.33

# Gas phase
vc_gas_mode = "Off"
vc_gas_transfer = "Sparging"
vc_gas_transfer_options = ["Headspace", "Sparging"]
vc_vs = 0.005
vc_coal = coal_options[0]

# Fed-batch (mesomixing)
_DEFAULT_FEED_PIPE_MM = 3.0
vc_fed_mode = "Off"
vc_feed_location = "Bulk (mid-liquid)"
vc_feed_location_options = ["Near impeller", "Bulk (mid-liquid)", "Surface"]
vc_feed_basis = vc_reactors[0] if vc_reactors else ""
vc_feed_volume_mL = 100.0
vc_feed_time_hr = 1.0


def _seed_feed_pipe_rows(names) -> pd.DataFrame:
    """Default each vessel's feed-pipe ID from reactors.csv (mm); 0 if not recorded."""
    rows = []
    for name in names:
        csv_m = _sf(_reactor_row(name).get("D_feed_pipe_m"))
        val = round(csv_m * 1000.0, 2) if csv_m > 0 else 0.0
        rows.append({"Reactor": name, "Feed pipe ID (mm)": val})
    return pd.DataFrame(rows) if rows else pd.DataFrame(columns=["Reactor", "Feed pipe ID (mm)"])


vc_feed_pipe_df = _seed_feed_pipe_rows(vc_reactors)

# Section 3: scale-up matching
vc_incl_scaling = "Off"
vc_basis = vc_reactors[0] if vc_reactors else ""
vc_scale_param = SCALABLE_PARAMS[0]
vc_scale_solve_for = scale_solve_options[0]
vc_basis_rpm = 100.0
vc_basis_vol = 1.0
vc_targets_df = pd.DataFrame(columns=["Reactor", "Known value"])

# Compute state / results
vc_status = "Select vessels and conditions, then Compute comparison."
vc_ready = False
vc_stale = False
vc_compute_class = "compute-btn"
vc_summary_df = pd.DataFrame()
vc_detail_df = pd.DataFrame()
vc_rpm_ref_df = pd.DataFrame()
vc_env_params_options = list(_BASE_PLOT_PARAMS)
vc_env_params = ["Da_micro", "Da_macro", "Blend time 95% (s)", "P/V (W/L)"]
vc_env_fig = go.Figure()
vc_env_class = "env-rows-2"
vc_heat_df = pd.DataFrame()
vc_scale_df = pd.DataFrame()
vc_scale_full_df = pd.DataFrame()
vc_scale_pct_df = pd.DataFrame()
vc_impact_df = pd.DataFrame()
vc_feed_plan_df = pd.DataFrame()
vc_summary_csv = b""
vc_detail_csv = b""
vc_rpm_ref_csv = b""
vc_heat_csv = b""
vc_scale_csv = b""
vc_scale_full_csv = b""
vc_scale_pct_csv = b""
vc_impact_csv = b""
vc_feed_plan_csv = b""

vc_pdf_bytes = b""
vc_pdf_name = "Vessel_Comparison.pdf"
vc_pdf_ready = False

# per-state compute cache (env_df, agg_df, reactor_info, curve_data, context)
_vc_cache: dict = {}


# ---------------------------------------------------------------------------
# Handlers — input changes
# ---------------------------------------------------------------------------
def _mark_stale(state):
    if state.vc_ready and not state.vc_stale:
        state.vc_stale = True
        state.vc_compute_class = "compute-btn"


def on_vc_input_change(state):
    _mark_stale(state)


def on_vc_reaction_change(state):
    """Auto-select the reaction's solvent + temperature and refill the editable kinetics."""
    kd = _kin_defaults(state.vc_reaction)
    state.vc_rxn_order = kd["order"]
    state.vc_rxn_k = kd["k"]
    state.vc_rxn_c0 = kd["C0"]
    state.vc_rxn_trxn = kd["t_rxn"]
    state.vc_rxn_dh = kd["dH"]
    state.vc_rxn_caption = _kin_caption(kd["order"], kd["k"], kd["C0"], kd["t_rxn"], kd["dH"])
    resolved = resolve_solvent_name(kd["solvent"]) if kd["solvent"] else None
    if resolved and resolved in fluid_options:
        state.vc_fluid = resolved
        if kd["T"] > 0:
            state.vc_T = kd["T"]
    _mark_stale(state)


def on_vc_reaction_source_change(state):
    state.vc_reaction_options = (reaction_class_options if state.vc_reaction_source == "Reaction classes"
                                 else reaction_measured_options) or ["(none available)"]
    if state.vc_reaction not in state.vc_reaction_options:
        state.vc_reaction = state.vc_reaction_options[0]
    on_vc_reaction_change(state)


def on_vc_kin_change(state):
    state.vc_rxn_caption = _kin_caption(
        str(state.vc_rxn_order or "1"), _sf(state.vc_rxn_k), _sf(state.vc_rxn_c0),
        _sf(state.vc_rxn_trxn), _sf(state.vc_rxn_dh))
    _mark_stale(state)


def on_vc_reactors_change(state):
    if state.vc_basis not in (state.vc_reactors or []):
        state.vc_basis = state.vc_reactors[0] if state.vc_reactors else ""
    if state.vc_feed_basis not in (state.vc_reactors or []):
        state.vc_feed_basis = state.vc_reactors[0] if state.vc_reactors else ""
    state.vc_viewers_html = _viewers_html(state.vc_reactors)
    state.vc_corr_options, state.vc_corr_status = _corr_choices(state.vc_reactors)
    if state.vc_corr_mode not in state.vc_corr_options:
        state.vc_corr_mode = state.vc_corr_options[0]
    _build_targets(state)
    state.vc_feed_pipe_df = _seed_feed_pipe_rows(state.vc_reactors or [])
    _mark_stale(state)


def on_vc_feed_pipe_edit(state, var_name, payload):
    df = state.vc_feed_pipe_df.copy()
    df.iloc[payload["index"], df.columns.get_loc(payload["col"])] = payload["value"]
    state.vc_feed_pipe_df = df
    _mark_stale(state)


def on_vc_particle_change(state):
    row = _particle_row(state.vc_particle)
    state.vc_rho_p = _sf(row.get("rho_p_kg_m3"), state.vc_rho_p)
    state.vc_d50 = _sf(row.get("d50_um"), state.vc_d50)
    state.vc_phi = _sf(row.get("shape_factor"), state.vc_phi)
    _mark_stale(state)


def on_vc_scaling_change(state):
    _build_targets(state)
    _mark_stale(state)


def on_vc_basis_change(state):
    row = _reactor_row(state.vc_basis)
    rpm_mid = _avg(row, "N_rpm_min", "N_rpm_max", 100.0)
    vol_mid = _avg(row, "V_L_min", "V_L_max", _sf(row.get("V_L"), 1.0))
    state.vc_basis_rpm = round(max(rpm_mid, 0.1), 1)
    state.vc_basis_vol = round(max(vol_mid, 0.001), 2)
    _build_targets(state)
    _mark_stale(state)


def _build_targets(state):
    """Rebuild the editable per-target known-value table for scale-up matching."""
    solve_rpm = state.vc_scale_solve_for.startswith("RPM")
    label = "Fill volume (L)" if solve_rpm else "Stir speed (RPM)"
    rows = []
    for name in (state.vc_reactors or []):
        if name == state.vc_basis:
            continue
        row = _reactor_row(name)
        if solve_rpm:
            val = _avg(row, "V_L_min", "V_L_max", _sf(row.get("V_L"), 1.0))
        else:
            val = _avg(row, "N_rpm_min", "N_rpm_max", 100.0)
        rows.append({"Reactor": name, label: round(max(val, 0.001), 2)})
    state.vc_targets_df = pd.DataFrame(rows) if rows else pd.DataFrame(columns=["Reactor", label])


def on_vc_targets_edit(state, var_name, payload):
    df = state.vc_targets_df.copy()
    df.iloc[payload["index"], df.columns.get_loc(payload["col"])] = payload["value"]
    state.vc_targets_df = df
    _mark_stale(state)


def on_vc_env_change(state):
    if not state.vc_ready or not state._vc_cache:
        return
    _build_env_fig(state)


def _build_csv_exports(state):
    """Refresh CSV download content from the current comparison tables."""
    state.vc_summary_csv = db.csv_bytes(state.vc_summary_df)
    state.vc_detail_csv = db.csv_bytes(state.vc_detail_df)
    state.vc_rpm_ref_csv = db.csv_bytes(state.vc_rpm_ref_df)
    state.vc_heat_csv = db.csv_bytes(state.vc_heat_df)
    state.vc_scale_csv = db.csv_bytes(state.vc_scale_df)
    state.vc_scale_full_csv = db.csv_bytes(state.vc_scale_full_df)
    state.vc_scale_pct_csv = db.csv_bytes(state.vc_scale_pct_df)
    state.vc_impact_csv = db.csv_bytes(state.vc_impact_df)
    state.vc_feed_plan_csv = db.csv_bytes(state.vc_feed_plan_df)


# ---------------------------------------------------------------------------
# Core compute
# ---------------------------------------------------------------------------
def _point_inputs(name: str, geo: VesselGeometry, d_feed_m: float, ctx: dict) -> op.PointInputs:
    """Operating-point inputs for one vessel under the shared comparison conditions."""
    solids = (op.Solids(rho_p=ctx["rho_p"], d50_um=ctx["d50"], phi=ctx["phi"], x_wt=ctx["x_wt"],
                        S_zw=ctx["szw"], gmb_z=ctx["gmb_z"], cd=ctx["cd"])
              if ctx["incl_particles"] else None)
    feed = (op.Feed(str(ctx["feed_loc"]),
                    d_feed_m if d_feed_m > 0 else _DEFAULT_FEED_PIPE_MM / 1000.0)
            if ctx["fed"] else None)
    return op.PointInputs(
        reactor=name, geometry=geo,
        fluid=op.Fluid(ctx["fluid_name"], ctx["rho"], ctx["mu"], ctx["D_mol"]),
        reaction=op.Reaction(ctx["order"], ctx["k"], ctx["C0"], ctx["t_rxn"], ctx["dH"]),
        corr_mode=ctx["corr_mode"], gas=op.Gas(ctx["v_s"], ctx["coalescing"]),
        solids=solids, feed=feed,
        heat=op.Heat(ctx["T_process"], ctx["T_coolant"]) if ctx["incl_heat"] else None)


def _corner_and_curves(names, ctx):
    """Return (env_rows, reactor_info, curve_data, skipped) for all reactors.

    Also stores each vessel's ``PointInputs`` in ``ctx["inputs"]`` for the scale-up solver.
    """
    env_rows, reactor_info, curve_data, skipped = [], {}, {}, []
    ctx["inputs"] = {}

    for name in names:
        r = _reactor_row(name)
        geo = VesselGeometry.from_row(r)
        window = scale_up.vessel_window(r, geo)
        if window is None:
            skipped.append(name)
            continue
        scale = str(r.get("scale", "") or "")
        feed_pipe_mm = ctx.get("feed_pipe_mm", {}).get(name)
        d_feed_pipe_m = (feed_pipe_mm / 1000.0 if feed_pipe_mm and feed_pipe_mm > 0
                         else _sf(r.get("D_feed_pipe_m")))

        reactor_info[name] = {
            "D_imp": geo.D_imp, "D_tank": geo.D_tank, "H_max": geo.H_max,
            "Np": geo.Np, "Nq": geo.Nq, **window,
            "bottom_dish": geo.bottom_dish, "scale": scale,
            "bottom_dish_height": geo.bottom_dish_height,
            "D_feed_pipe_m": d_feed_pipe_m,
            "shell_material": geo.shell_material,
            "lining_material": geo.lining_material,
            "wall_thickness_mm": geo.wall_thickness_mm,
        }
        inp = ctx["inputs"][name] = _point_inputs(name, geo, d_feed_pipe_m, ctx)
        corners, curve_data[name] = scale_up.corner_envelope(
            inp, window, ctx["plot_params"], _N_INTERP)
        env_rows += [{"Reactor": name, "Scale": scale, **c} for c in corners]

    return env_rows, reactor_info, curve_data, skipped


def on_vc_compute(state):
    names = list(state.vc_reactors or [])
    if not names:
        notify(state, "W", "Select at least one vessel to compare.")
        return

    rho, mu, D_mol, in_range, note = _fluid_props(state.vc_fluid, state.vc_T, state.vc_P)
    # user-editable kinetics override the database values
    _order = str(state.vc_rxn_order or "1")
    _k, _C0 = _sf(state.vc_rxn_k), _sf(state.vc_rxn_c0)
    rxn = {"order": _order, "k": _k, "C0": _C0,
           "t_rxn": _derive_trxn(_order, _k, _C0, _sf(state.vc_rxn_trxn)),
           "dH": _sf(state.vc_rxn_dh)}
    incl_p = state.vc_incl_particles == "On" and _sf(state.vc_d50) > 0
    incl_h = rxn["dH"] != 0.0
    gas_on = state.vc_gas_mode == "On"
    fed_on = state.vc_fed_mode == "On"
    x_wt = _sf(state.vc_x_wt)

    plot_params = list(_BASE_PLOT_PARAMS)
    if fed_on:
        plot_params.insert(plot_params.index("Da_micro") + 1, "Da_meso")
    if incl_h:
        plot_params += _HEAT_PARAMS
    if incl_p:
        plot_params += _PARTICLE_PARAMS

    v_s = _sf(state.vc_vs) if (gas_on and state.vc_gas_transfer == "Sparging") else 0.0
    feed_pipe_mm = ({str(r["Reactor"]): _sf(r["Feed pipe ID (mm)"])
                    for _, r in state.vc_feed_pipe_df.iterrows()} if fed_on else {})
    ctx = {
        "rho": rho, "mu": mu, "D_mol": D_mol, "v_s": v_s,
        "coalescing": state.vc_coal.startswith("Coalescing"),
        "t_rxn": rxn["t_rxn"], "order": rxn["order"], "k": rxn["k"], "C0": rxn["C0"],
        "dH": rxn["dH"], "incl_heat": incl_h, "incl_particles": incl_p, "gas_on": gas_on,
        "fed": fed_on, "feed_pipe_mm": feed_pipe_mm, "feed_loc": state.vc_feed_location,
        "rho_p": _sf(state.vc_rho_p), "d50": _sf(state.vc_d50), "phi": _sf(state.vc_phi),
        "x_wt": x_wt, "szw": _sf(state.vc_szw, 5.5),
        "gmb_z": _sf(state.vc_gmb_z, 3.0), "cd": _sf(state.vc_cd, 0.33),
        "T_process": state.vc_T, "T_coolant": _sf(state.vc_T_cool),
        "fluid_name": state.vc_fluid, "plot_params": plot_params,
        "corr_mode": op.CORR_SOURCES.get(state.vc_corr_mode, "Literature"),
    }

    env_rows, reactor_info, curve_data, skipped = _corner_and_curves(names, ctx)
    if not env_rows:
        notify(state, "E", "No computable vessels in the selection (missing geometry).")
        return
    env_df = pd.DataFrame(env_rows)
    env_df["RPM_pct"] = env_df["RPM"] / env_df["RPM_max"] * 100.0

    present = [p for p in plot_params if p in env_df.columns]
    agg = env_df.groupby("Reactor", sort=False).agg(
        {**{p: ["min", "max"] for p in present}, "Scale": "first",
         "Volume (L)": ["min", "max"]})
    agg.columns = ["_".join(c).strip("_") for c in agg.columns]
    agg_df = agg.reset_index()

    # cache for chart rebuild / PDF / save
    state._vc_cache = {
        "env_df": env_df, "agg_df": agg_df, "reactor_info": reactor_info,
        "curve_data": curve_data, "ctx": ctx, "present": present,
        "rxn_name": state.vc_reaction, "fluid_name": state.vc_fluid,
        "fluid_T_C": state.vc_T, "t_rxn": rxn["t_rxn"], "incl_heat": incl_h,
        "incl_particles": incl_p, "particle": state.vc_particle if incl_p else "",
    }

    # Update the plot-parameter picker to what's available
    state.vc_env_params_options = present
    state.vc_env_params = [p for p in state.vc_env_params if p in present] or present[:4]

    _build_summary_tables(state, env_df, agg_df, present, ctx)
    _build_env_fig(state)
    _build_heat_summary(state, env_df, reactor_info, ctx)
    _build_scaling(state, names, reactor_info, ctx)
    _build_impact(state, env_df, present, ctx)
    feed_ok = _build_feed_plan(state, reactor_info, fed_on)
    _build_csv_exports(state)

    state.vc_pdf_ready = False
    if not feed_ok:
        state.vc_ready = False
        state.vc_stale = False
        state.vc_compute_class = "compute-btn"
        state.vc_status = ("Fed-batch feed volume exceeds max volume for one or more vessels — "
                           "adjust the feed schedule and recompute.")
        return

    state.vc_ready = True
    state.vc_stale = False
    state.vc_compute_class = "compute-btn-ok"
    msg = (f"Compared {len(reactor_info)} vessel(s) across the 4-corner envelope "
           f"({state.vc_corr_mode}).")
    if skipped:
        msg += f" Skipped (missing geometry): {', '.join(skipped)}."
    state.vc_status = msg
    notify(state, "S", "Comparison computed.")


def _fmt_range(lo, hi) -> str:
    if not (np.isfinite(lo) and np.isfinite(hi)):
        return "—"
    if abs(lo - hi) < 1e-12:
        return f"{lo:.3g}"
    return f"{lo:.3g} – {hi:.3g}"


def _build_summary_tables(state, env_df, agg_df, present, ctx):
    # Range summary (one row per reactor)
    key_cols = [p for p in ["P/V (W/L)", "Blend time 95% (s)", "Tip speed (m/s)",
                            "Da_macro", "Da_meso", "Da_micro", "Da_GL", "Re"] if p in present]
    rows = []
    for _, a in agg_df.iterrows():
        row = {"Reactor": a["Reactor"], "Scale": a.get("Scale_first", ""),
               "Volume (L)": _fmt_range(a["Volume (L)_min"], a["Volume (L)_max"])}
        for p in key_cols:
            row[p] = _fmt_range(a[f"{p}_min"], a[f"{p}_max"])
        rows.append(row)
    state.vc_summary_df = pd.DataFrame(rows)

    # 4-corner detail
    detail_cols = [c for c in ["Reactor", "Corner", "RPM", "V_L", "Re", "P/V (W/L)",
                               "Tip speed (m/s)", "Blend time 95% (s)",
                               "Micromix time t_E (s)", "Kolmogorov η (µm)",
                               "Da_macro", "Da_meso", "Da_micro", "Da_GL", "Da_SL"] if c in env_df.columns]
    det = env_df[detail_cols].copy()
    for c in detail_cols:
        if c not in ("Reactor", "Corner"):
            det[c] = det[c].map(lambda v: f"{v:.3g}" if pd.notna(v) and np.isfinite(v) else "—")
    state.vc_detail_df = det

    # Stir-speed reference table
    pct_steps = [10, 20, 30, 40, 50, 60, 70, 80, 90, 100]
    ref_rows = []
    for name in agg_df["Reactor"].tolist():
        sub = env_df[env_df["Reactor"] == name]
        rpm_max = sub["RPM_max"].iloc[0]
        rpm_min = sub[sub["Corner"] == CORNER_LABELS[0]]["RPM"].iloc[0]
        row = {"Reactor": name, "RPM min": f"{rpm_min:.0f}", "RPM max": f"{rpm_max:.0f}"}
        for pct in pct_steps:
            row[f"{pct}%"] = f"{rpm_max * pct / 100:.0f}"
        ref_rows.append(row)
    state.vc_rpm_ref_df = pd.DataFrame(ref_rows)


def _build_env_fig(state):
    cache = state._vc_cache
    if not cache:
        return
    env_df = cache["env_df"]
    curve_data = cache["curve_data"]
    params = [p for p in (state.vc_env_params or []) if p in cache["present"]]
    if not params:
        params = cache["present"][:1]

    n = len(params)
    cols = min(2, n)
    rows = int(np.ceil(n / cols))
    positions = [(i // cols + 1, i % cols + 1) for i in range(n)]
    vspace = min(0.22, 0.6 / max(rows - 1, 1))
    fig = make_subplots(rows=rows, cols=cols, subplot_titles=[_display(p) for p in params],
                        vertical_spacing=vspace, horizontal_spacing=0.08)

    reactor_list = env_df["Reactor"].drop_duplicates().tolist()
    for pi, (param, (r, c)) in enumerate(zip(params, positions)):
        first_param = (pi == 0)
        for i, name in enumerate(reactor_list):
            color = _PALETTE[i % len(_PALETTE)]
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
        if param in _LOG_PARAMS:
            fig.update_yaxes(type="log", row=r, col=c)
            for thr, col_ in ((0.1, "orange"), (1.0, "red")):
                fig.add_hline(y=thr, line_dash="dash", line_color=col_, row=r, col=c)
        if param == "N/N_js":
            fig.add_hline(y=1.0, line_dash="dash", line_color="red", row=r, col=c)
        if param == "Q_gen/Q_cool (%)":
            fig.add_hline(y=100.0, line_dash="dash", line_color="red", row=r, col=c)

    fig_height = max(360, rows * 360)
    _t_margin = 90
    _plot_area = max(fig_height - _t_margin - 40, 120)
    _legend_y = 1 + 45 / _plot_area
    fig.update_layout(height=fig_height, margin={"t": _t_margin, "b": 40},
                      # No explicit paper/font colors: Taipy swaps the plotly
                      # template per theme, keeping legends legible in dark mode.
                      plot_bgcolor="rgba(225,37,27,0.06)",
                      legend={"title": "Vessel", "orientation": "h", "y": _legend_y,
                              "yanchor": "bottom", "x": 0.5, "xanchor": "center"})
    state.vc_env_fig = fig
    state.vc_env_class = f"env-rows-{min(rows, 8)}"


def _build_heat_summary(state, env_df, reactor_info, ctx):
    if not ctx["incl_heat"]:
        state.vc_heat_df = pd.DataFrame()
        return
    rows = []
    for name in reactor_info:
        sub = env_df[(env_df["Reactor"] == name) & (env_df["Corner"] == CORNER_LABELS[1])]
        if sub.empty:
            continue
        c = sub.iloc[0]
        Q_gen, Q_cool = c.get("Q_gen (W)", 0.0), c.get("Q_cool (W)", 0.0)
        ratio = Q_gen / Q_cool * 100.0 if Q_cool > 0 else np.inf
        rows.append({
            "Reactor": name, "Volume (L)": f"{c['V_L']:.1f}",
            "U (W/m²·K)": f"{c.get('U (W/m²·K)', 0):.0f}",
            "A (m²)": f"{c.get('A_ht (m²)', 0):.3f}",
            "Q_gen (W)": f"{Q_gen:.1f}", "Q_cool (W)": f"{Q_cool:.1f}",
            "Q_gen/Q_cool (%)": f"{ratio:.1f}%" if ratio < 1e4 else "∞",
            "Assessment": heat_balance_assessment(Q_gen, Q_cool),
        })
    state.vc_heat_df = pd.DataFrame(rows)


def _build_scaling(state, names, reactor_info, ctx):
    if state.vc_incl_scaling != "On" or len(names) < 2:
        state.vc_scale_df = pd.DataFrame()
        state.vc_scale_full_df = pd.DataFrame()
        state.vc_scale_pct_df = pd.DataFrame()
        return
    basis = state.vc_basis
    param = state.vc_scale_param
    solve_rpm = state.vc_scale_solve_for.startswith("RPM")
    if basis not in reactor_info:
        state.vc_scale_df = pd.DataFrame([{"Reactor": basis, "Status": "Basis geometry missing"}])
        state.vc_scale_full_df = pd.DataFrame()
        state.vc_scale_pct_df = pd.DataFrame()
        return

    b_N = _sf(state.vc_basis_rpm) / 60.0
    b_hydro = op.hydro(ctx["inputs"][basis], b_N, _sf(state.vc_basis_vol))
    target_value = b_hydro.get(param, np.nan)

    results = [{"Reactor": basis, "Role": "Basis", "RPM": _sf(state.vc_basis_rpm),
                "Volume (L)": _sf(state.vc_basis_vol), param: target_value, "Status": "—"}]
    full = [{"Reactor": basis, "Role": "Basis", "RPM": _sf(state.vc_basis_rpm),
             "Volume (L)": _sf(state.vc_basis_vol), **b_hydro}]

    known = {}
    if not state.vc_targets_df.empty:
        val_col = [c for c in state.vc_targets_df.columns if c != "Reactor"][0]
        known = {str(r["Reactor"]): _sf(r[val_col]) for _, r in state.vc_targets_df.iterrows()}

    for name in names:
        if name == basis or name not in reactor_info:
            continue
        inp = ctx["inputs"][name]
        rpm_window, vol_window = scale_up.matching_window(_reactor_row(name), inp.geometry)
        m = scale_up.match_parameter(
            lambda n, v, _inp=inp: op.hydro(_inp, n, v), param, target_value,
            solve_rpm=solve_rpm, known=known.get(name, 0.0),
            rpm_window=rpm_window, vol_window=vol_window)
        results.append({"Reactor": name, "Role": "Target", "RPM": m["RPM"],
                        "Volume (L)": m["Volume (L)"], param: m["value"], "Status": m["status"]})
        full.append({"Reactor": name, "Role": "Target", "RPM": m["RPM"],
                     "Volume (L)": m["Volume (L)"], **m["hydro"]})

    res_df = pd.DataFrame(results)
    for c in res_df.columns:
        if c not in ("Reactor", "Role", "Status"):
            res_df[c] = res_df[c].map(lambda v: f"{v:.4g}" if isinstance(v, (int, float)) and np.isfinite(v) else v)
    state.vc_scale_df = res_df

    full_df = pd.DataFrame(full)
    show_cols = [c for c in ["Reactor", "Role", "RPM", "Volume (L)", "Re", "P/V (W/L)",
                             "Tip speed (m/s)", "Blend time 95% (s)", "Micromix time t_E (s)",
                             "Kolmogorov η (µm)", "kLa (1/s)", "Torque (N·m)",
                             "EDCF (W/kg/s)", "Froude number"] if c in full_df.columns]
    disp = full_df[show_cols].copy()
    num_cols = [c for c in show_cols if c not in ("Reactor", "Role")]
    for c in num_cols:
        disp[c] = disp[c].map(lambda v: f"{v:.4g}" if pd.notna(v) and np.isfinite(v) else "—")
    state.vc_scale_full_df = disp

    # % difference vs basis
    basis_row = full_df[full_df["Role"] == "Basis"].iloc[0]
    pct_rows = []
    for _, row in full_df.iterrows():
        entry = {"Reactor": row["Reactor"], "Role": row["Role"]}
        for c in num_cols:
            b, t = basis_row.get(c, 0.0), row.get(c, 0.0)
            if b and np.isfinite(b) and b != 0 and np.isfinite(t):
                entry[c] = f"{(t - b) / abs(b) * 100:+.1f}%"
            else:
                entry[c] = "—"
        pct_rows.append(entry)
    state.vc_scale_pct_df = pd.DataFrame(pct_rows)


def _build_impact(state, env_df, present, ctx):
    state.vc_impact_df = pd.DataFrame(scale_up.impact_ratios(env_df, present, ctx["incl_heat"]))


def _build_feed_plan(state, reactor_info, fed_on) -> bool:
    """Scale the basis vessel's feed volume to every vessel by V_L_max ratio.

    Feed time is shared across vessels; only feed volume (and thus rate)
    scales. Returns False (and warns) when the projected end volume (start =
    V_L_min) would exceed any vessel's recorded V_L_max.
    """
    if not fed_on or not reactor_info:
        state.vc_feed_plan_df = pd.DataFrame()
        return True
    rows, exceeded, error = scale_up.feed_plan(
        reactor_info, state.vc_feed_basis, _sf(state.vc_feed_volume_mL), _sf(state.vc_feed_time_hr))
    state.vc_feed_plan_df = pd.DataFrame(rows)
    if error:
        return False
    if exceeded:
        notify(state, "W", "Feed volume exceeds max volume for: " + "; ".join(exceeded))
        return False
    return True


# ---------------------------------------------------------------------------
# Export / save
# ---------------------------------------------------------------------------
def on_vc_export_pdf(state):
    if not state.vc_ready or not state._vc_cache:
        notify(state, "W", "Compute the comparison before exporting.")
        return
    cache = state._vc_cache
    try:
        report_chart_params = [p for p in ["Da_micro", "Da_macro", "Da_GL", "P/V (W/L)",
                                           "Blend time 95% (s)", "Tip speed (m/s)"]
                               if p in cache["present"]]
        snap = {
            "selected_names": cache["env_df"]["Reactor"].drop_duplicates().tolist(),
            "fluid": cache["fluid_name"], "fluid_T_C": cache["fluid_T_C"],
            "reaction": cache["rxn_name"], "t_rxn": cache["t_rxn"],
            "env_df": cache["env_df"], "agg_df": cache["agg_df"],
            "reactor_info": cache["reactor_info"], "include_heat": cache["incl_heat"],
            "include_particles": cache["incl_particles"],
            "scaling_results": [], "scaling_all_params": [],
            "scale_param": state.vc_scale_param if state.vc_incl_scaling == "On" else "",
            "scale_basis_reactor": state.vc_basis if state.vc_incl_scaling == "On" else "",
            "curve_data": cache["curve_data"], "report_chart_params": report_chart_params,
        }
        state.vc_pdf_bytes = build_reactor_comparison_pdf(snap)
        state.vc_pdf_name = report_filename(
            "Vessel_Comparison", snap["selected_names"][0] if snap["selected_names"] else "")
        state.vc_pdf_ready = True
        notify(state, "S", "PDF report generated — click Download.")
    except Exception as exc:  # noqa: BLE001
        notify(state, "E", f"PDF generation failed: {exc}")


def on_vc_save_results(state):
    if not state.vc_ready or not state._vc_cache:
        notify(state, "W", "Compute the comparison before saving.")
        return
    cache = state._vc_cache
    env_df = cache["env_df"]
    rows = []
    for name in env_df["Reactor"].drop_duplicates().tolist():
        sub = env_df[(env_df["Reactor"] == name) & (env_df["Corner"] == CORNER_LABELS[1])]
        if sub.empty:
            continue
        c = sub.iloc[0]
        rows.append({
            "reactor": name, "reaction": cache["rxn_name"], "fluid": cache["fluid_name"],
            "fluid_T_C": cache["fluid_T_C"], "RPM": c["RPM"], "Volume (L)": c["V_L"],
            "Re": c.get("Re", ""), "P/V (W/L)": c.get("P/V (W/L)", ""),
            "Tip speed (m/s)": c.get("Tip speed (m/s)", ""),
            "Blend time (s)": c.get("Blend time 95% (s)", ""),
            "Kolmogorov η (µm)": c.get("Kolmogorov η (µm)", ""),
            "t_rxn (s)": cache["t_rxn"], "Da_macro": c.get("Da_macro", ""),
            "Da_micro": c.get("Da_micro", ""), "Da_GL": c.get("Da_GL", ""),
            "Da_SL": c.get("Da_SL", ""), "Assessment": c.get("Assessment", ""),
        })
    if not rows:
        notify(state, "W", "Nothing to save.")
        return
    new_df = pd.DataFrame(rows)
    try:
        db.append_csv(new_df, RECORDED_CSV)
        notify(state, "S",
               f"Saved {len(rows)} vessel result(s) — view them on the Recorded Results page.")
    except Exception as exc:  # noqa: BLE001
        notify(state, "E", f"Save failed: {exc}")


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------
page = Markdown(
    inject_icons("""
# __ICON:Vessel_Comparison__Vessel Comparison

Compare the mixing performance of several vessels side-by-side. Each vessel's
operating envelope is mapped from its RPM range and fill-volume band for a shared
fluid and reaction system.

<|{vc_status}|text|>

<|part|class_name=va-card|
## 1. Reactors & Conditions
<|{vc_reactors}|selector|lov={reactor_options}|multiple|dropdown|label=Vessels to compare|on_change=on_vc_reactors_change|>

<|layout|columns=1 2|
<|{vc_corr_mode}|selector|lov={vc_corr_options}|dropdown|label=Correlation source|on_change=on_vc_input_change|>

<|{vc_corr_status}|text|class_name=phase-hint|>
|>

<|layout|columns=1 1 1|class_name=form-grid|
<|{vc_fluid}|selector|lov={fluid_options}|dropdown|label=Fluid|on_change=on_vc_input_change|>

<|{vc_T}|number|label=Temperature (°C)|on_change=on_vc_input_change|>

<|{vc_P}|number|label=Pressure (atm)|on_change=on_vc_input_change|>
|>

<|layout|columns=1 1 1|class_name=form-grid|
<|{vc_reaction_source}|selector|lov={reaction_source_options}|dropdown|label=Reaction source|on_change=on_vc_reaction_source_change|>

<|{vc_reaction}|selector|lov={vc_reaction_options}|dropdown|label=Reaction (for Da numbers)|on_change=on_vc_reaction_change|>

<|{vc_T_cool}|number|label=Coolant temperature (°C)|on_change=on_vc_input_change|>
|>

**Reaction conditions & kinetics** — auto-filled from the database; edit any value to override.

<|layout|columns=1 1 1|class_name=form-grid|
<|{vc_rxn_order}|selector|lov={vc_rxn_order_options}|dropdown|label=Reaction order|on_change=on_vc_kin_change|>

<|{vc_rxn_k}|number|label=Rate constant k (1/s or L/mol·s)|on_change=on_vc_kin_change|>

<|{vc_rxn_c0}|number|label=C₀ (mol/L)|on_change=on_vc_kin_change|>
|>

<|layout|columns=1 1 1|class_name=form-grid|
<|{vc_rxn_trxn}|number|label=t_rxn (s, 0 = derive from k)|on_change=on_vc_kin_change|>

<|{vc_rxn_dh}|number|label=ΔH (kJ/mol)|on_change=on_vc_kin_change|>
|>

<|{vc_rxn_caption}|text|mode=markdown|>
|>

<|part|class_name=va-card|
## Selected Vessels
Drag to rotate a 3D model; scroll to zoom. The row scrolls sideways when several vessels are selected.

<|part|content={vc_viewers_html}|height=340px|>
|>

<|part|class_name=va-card|
## 2. Options
<|layout|columns=1 1 1|gap=16px|class_name=phase-grid|
<|part|class_name=phase-panel|
### __ICON:Particle_Database__Solid particles
<|{vc_incl_particles}|toggle|lov={vc_onoff_options}|label=Include solid particles|class_name=onoff-toggle|on_change=on_vc_input_change|>

<|part|render={vc_incl_particles == "On"}|
<|{vc_particle}|selector|lov={particle_options}|dropdown|label=Particle|on_change=on_vc_particle_change|>

<|layout|columns=1 1|
<|{vc_rho_p}|number|label=ρ_p (kg/m³)|on_change=on_vc_input_change|>

<|{vc_d50}|number|label=d50 (µm)|on_change=on_vc_input_change|>

<|{vc_phi}|number|label=Shape factor φ|on_change=on_vc_input_change|>

<|{vc_x_wt}|number|label=Solids loading (wt-%)|on_change=on_vc_input_change|>

<|{vc_szw}|number|label=Zwietering S|on_change=on_vc_input_change|>

<|{vc_gmb_z}|number|label=GMB z constant|on_change=on_vc_input_change|>

<|{vc_cd}|number|label=C/D (clearance / dia)|on_change=on_vc_input_change|>
|>
|>

<|part|render={vc_incl_particles == "Off"}|class_name=phase-hint|
Enable to check off-bottom suspension in each vessel. Particle properties are shared across all compared vessels.
|>
|>

<|part|class_name=phase-panel|
### 🫧 Gas
<|{vc_gas_mode}|toggle|lov={vc_onoff_options}|label=Include gas phase|class_name=onoff-toggle|on_change=on_vc_input_change|>

<|part|render={vc_gas_mode == "On"}|
<|{vc_gas_transfer}|toggle|lov={vc_gas_transfer_options}|label=Mass-transfer mode|on_change=on_vc_input_change|>

<|part|render={vc_gas_transfer == "Sparging"}|
<|{vc_vs}|number|label=Superficial gas velocity v_s (m/s)|on_change=on_vc_input_change|>

<|{vc_coal}|selector|lov={coal_options}|dropdown|label=Liquid type (for kLa)|on_change=on_vc_input_change|>
|>
|>

<|part|render={vc_gas_mode == "Off"}|class_name=phase-hint|
Enable to include gas–liquid mass transfer (headspace or sparged) in each vessel.
|>
|>

<|part|class_name=phase-panel|
### 🔁 Fed-batch
<|{vc_fed_mode}|toggle|lov={vc_onoff_options}|label=Fed-batch addition|class_name=onoff-toggle|on_change=on_vc_input_change|>

<|part|render={vc_fed_mode == "On"}|
<|{vc_feed_location}|selector|lov={vc_feed_location_options}|dropdown|label=Feed location|on_change=on_vc_input_change|>

**Feed pipe diameter per vessel** — defaults from each reactor's recorded feed-pipe ID; edit to override.
<|{vc_feed_pipe_df}|table|editable|rebuild|on_edit=on_vc_feed_pipe_edit|width=100%|show_all|>

**Feed schedule** — feed volume is set at the basis vessel and scaled to the others by V_L_max.
<|{vc_feed_basis}|selector|lov={vc_reactors}|dropdown|label=Basis vessel|on_change=on_vc_input_change|>

<|layout|columns=1 1|
<|{vc_feed_volume_mL}|number|label=Feed volume (mL)|on_change=on_vc_input_change|>

<|{vc_feed_time_hr}|number|label=Feed time (h)|on_change=on_vc_input_change|>
|>
|>

<|part|render={vc_fed_mode == "Off"}|class_name=phase-hint|
Enable to add the mesomixing Damköhler number (Da_meso), evaluated at the feed point.
|>
|>
|>
|>

<|part|class_name=va-card|
## 3. Scale-Up Matching
Hold one parameter constant on a **basis** vessel and solve for the equivalent
operating point on every other selected vessel.

<|{vc_incl_scaling}|toggle|lov={vc_onoff_options}|label=Perform scale-up matching|class_name=onoff-toggle|on_change=on_vc_scaling_change|>

<|part|render={vc_incl_scaling == "On"}|
<|layout|columns=1 1|class_name=form-grid|
<|{vc_basis}|selector|lov={vc_reactors}|dropdown|label=Basis vessel|on_change=on_vc_basis_change|>

<|{vc_scale_param}|selector|lov={scalable_params}|dropdown|label=Parameter to hold constant|on_change=on_vc_input_change|>
|>

<|{vc_scale_solve_for}|selector|lov={scale_solve_options}|dropdown|label=For target vessels, solve for|on_change=on_vc_scaling_change|class_name=form-grid|>

<|layout|columns=1 1|class_name=form-grid|
<|{vc_basis_rpm}|number|label=Basis RPM|on_change=on_vc_input_change|>

<|{vc_basis_vol}|number|label=Basis volume (L)|on_change=on_vc_input_change|>
|>

**Target vessel known values**
<|{vc_targets_df}|table|editable|rebuild|on_edit=on_vc_targets_edit|width=60%|show_all|>
|>
|>

<|Compute comparison|button|on_action=on_vc_compute|class_name={vc_compute_class}|>

<|part|render={vc_stale}|
**⚠️ Inputs changed since the last run — click _Compute comparison_ to refresh.**
|>

<|part|render={vc_ready}|
<|part|class_name=va-card|
## Operating Envelope Summary
Each row shows the range across the 4 corner conditions (min/max RPM × min/max volume).

<|{vc_summary_df}|table|width=100%|show_all|rebuild|>

<|part|render={not vc_stale}|
<|Download summary CSV|file_download|content={vc_summary_csv}|name=vessel_comparison_summary.csv|label=Download summary CSV|>
|>

<|Full 4-corner detail|expandable|expanded=False|
<|{vc_detail_df}|table|width=100%|page_size=16|rebuild|>

<|part|render={not vc_stale}|
<|Download detail CSV|file_download|content={vc_detail_csv}|name=vessel_comparison_detail.csv|label=Download detail CSV|>
|>
|>
|>

<|part|class_name=va-card|
## Stir Speed Reference
Translates a percentage of each vessel's maximum RPM (the chart x-axis) to actual RPM.

<|{vc_rpm_ref_df}|table|width=100%|show_all|rebuild|>

<|part|render={not vc_stale}|
<|Download stir-speed CSV|file_download|content={vc_rpm_ref_csv}|name=vessel_comparison_stir_speed.csv|label=Download stir-speed CSV|>
|>
|>

<|part|class_name=va-card|
## Operating Envelope Charts
Each vessel's reachable region is a filled polygon spanning its RPM range (as % of
max). The **solid** line is the maximum-fill-volume edge, the **dotted** line the
minimum-fill edge. Dashed lines on the Damköhler panels mark the 0.1 and 1.0
mixing-sensitivity thresholds.

<|{vc_env_params}|selector|lov={vc_env_params_options}|multiple|dropdown|label=Parameters to plot|on_change=on_vc_env_change|>

<|chart|figure={vc_env_fig}|class_name={vc_env_class}|rebuild=True|>
|>

<|part|render={len(vc_heat_df) > 0}|class_name=va-card|
## Heat Balance Summary
Evaluated at each vessel's max-RPM / max-volume corner.

<|{vc_heat_df}|table|width=100%|show_all|rebuild|>

<|part|render={not vc_stale}|
<|Download heat-balance CSV|file_download|content={vc_heat_csv}|name=vessel_comparison_heat_balance.csv|label=Download heat-balance CSV|>
|>
|>

<|part|render={len(vc_scale_df) > 0}|class_name=va-card|
## Scale-Up Matching Results
Matched operating conditions that hold the chosen parameter constant relative to the basis vessel.

<|{vc_scale_df}|table|width=100%|show_all|rebuild|>

<|part|render={not vc_stale}|
<|Download matching CSV|file_download|content={vc_scale_csv}|name=vessel_comparison_matching.csv|label=Download matching CSV|>
|>

<|Full parameter comparison at matched conditions|expandable|expanded=False|
<|{vc_scale_full_df}|table|width=100%|show_all|rebuild|>

<|part|render={not vc_stale}|
<|Download matched-parameters CSV|file_download|content={vc_scale_full_csv}|name=vessel_comparison_matched_parameters.csv|label=Download matched-parameters CSV|>
|>
|>

<|Percentage difference vs. basis vessel|expandable|expanded=False|
<|{vc_scale_pct_df}|table|width=100%|show_all|rebuild|>

<|part|render={not vc_stale}|
<|Download scale-up differences CSV|file_download|content={vc_scale_pct_csv}|name=vessel_comparison_scale_up_differences.csv|label=Download scale-up differences CSV|>
|>
|>
|>

<|part|render={len(vc_impact_df) > 0}|class_name=va-card|
## Scale-Up Impact Summary
Ratios use the midpoint (average of the 4 corners) for each parameter, relative to the first selected vessel.

<|{vc_impact_df}|table|width=100%|show_all|rebuild|>

<|part|render={not vc_stale}|
<|Download impact CSV|file_download|content={vc_impact_csv}|name=vessel_comparison_impact.csv|label=Download impact CSV|>
|>
|>

<|part|render={len(vc_feed_plan_df) > 0}|class_name=va-card|
## Fed-Batch Feed Plan
Feed volume (and rate) scales linearly with each vessel's max fill volume (V_L_max) relative to
the basis vessel; feed time is shared. Start volume is each vessel's V_L_min; flagged rows would
exceed that vessel's recorded V_L_max.

<|{vc_feed_plan_df}|table|width=100%|show_all|rebuild|>

<|part|render={not vc_stale}|
<|Download feed-plan CSV|file_download|content={vc_feed_plan_csv}|name=vessel_comparison_feed_plan.csv|label=Download feed-plan CSV|>
|>
|>

<|part|class_name=va-card|
## Export & Save
<|layout|columns=1 1|
<|Generate PDF report|button|on_action=on_vc_export_pdf|class_name=compute-btn|>

<|Save results to Recorded Results|button|on_action=on_vc_save_results|>
|>

<|part|render={vc_pdf_ready}|
<|Download PDF|file_download|content={vc_pdf_bytes}|name={vc_pdf_name}|label=Download PDF|>
|>
|>
|>
""")
)

# Expose the scalable-parameter list to the page markdown.
scalable_params = SCALABLE_PARAMS
