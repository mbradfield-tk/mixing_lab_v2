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

To keep the port maintainable, all vessels use the **Literature** correlation
source (the per-reactor ROM/experimental matrix of the Streamlit page is not
reproduced), and solid-particle properties are shared across the selection.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from taipy.gui import Markdown, notify

from utils.menu_icons import inject_icons
from utils.calculations import (
    compute_damkohler_numbers,
    estimate_U_detailed,
    estimate_jacket_area,
    gmb_njs,
    heat_balance_assessment,
    heat_generation_rate,
    heat_removal_capacity,
    liquid_height_from_volume,
    mesomixing_time,
    particle_reynolds,
    reaction_rate_mol_per_s,
    settling_velocity,
    solid_liquid_kla,
    solid_liquid_mass_transfer,
    zwietering_njs,
)
from utils.rom_registry import compute_reactor_hydro_with_mode
from utils.solvent_properties import (
    SOLVENT_DB,
    get_properties,
    is_known_solvent,
    list_solvents,
    resolve_solvent_name,
)
from utils.report_builder import build_reactor_comparison_pdf, report_filename
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

CORNER_LABELS = ["min RPM / max V", "max RPM / max V",
                 "min RPM / min V", "max RPM / min V"]

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
def _sf(val, default=0.0) -> float:
    try:
        f = float(val)
        return default if np.isnan(f) else f
    except (TypeError, ValueError):
        return default


def _reactor_row(name: str) -> pd.Series:
    df = db.fresh_csv(DATA_DIR / "reactors.csv", ["reactor_name"])
    row = df[df["reactor_name"].astype(str) == str(name)]
    return row.iloc[0] if not row.empty else pd.Series(dtype=object)


def _reaction_row(name: str) -> pd.Series:
    df = db.fresh_csv(DATA_DIR / "reactions.csv", ["reaction_name"])
    row = df[df["reaction_name"].astype(str) == str(name)]
    return row.iloc[0] if not row.empty else pd.Series(dtype=object)


def _particle_row(name: str) -> pd.Series:
    df = db.fresh_csv(DATA_DIR / "particles.csv", ["particle_name"])
    row = df[df["particle_name"].astype(str) == str(name)]
    return row.iloc[0] if not row.empty else pd.Series(dtype=object)


def _reactor_id(name: str) -> str:
    r = _reactor_row(name)
    return "" if r.empty else str(r.get("reactor_id", "") or "")


def _viewers_html(names) -> str:
    items = [(n, _reactor_id(n)) for n in (names or [])]
    return build_multi_vessel_viewer_html(items, height=260)


def _display(p: str) -> str:
    return _DISPLAY_NAMES.get(p, p)


def _solve_root(f, lo: float, hi: float, tol: float, maxit: int = 200):
    """Bracketed bisection root-finder (returns None when no sign change)."""
    flo, fhi = f(lo), f(hi)
    if flo == 0:
        return lo
    if fhi == 0:
        return hi
    if flo * fhi > 0:
        return None
    for _ in range(maxit):
        mid = 0.5 * (lo + hi)
        fmid = f(mid)
        if abs(fmid) < tol or (hi - lo) < tol:
            return mid
        if flo * fmid < 0:
            hi, fhi = mid, fmid
        else:
            lo, flo = mid, fmid
    return 0.5 * (lo + hi)


def _fluid_props(name: str, T_C: float, P_atm: float) -> tuple[float, float, float, bool, str]:
    """Return (rho, mu, D_mol, in_range, note)."""
    if is_known_solvent(name):
        canonical = resolve_solvent_name(name) or name
        p = get_properties(canonical, T_C, P_atm)
        note = ""
        if not p.get("in_range", True):
            note = (f"⚠️ {T_C:.1f} °C is outside the liquid range "
                    f"({p.get('mp_C', 0):.0f} – {p.get('bp_at_P_C', 0):.0f} °C) for {name}.")
        return (p["rho_kg_m3"], p["mu_Pa_s"], p["D_mol_m2_s"], p.get("in_range", True), note)
    fluids = db.fresh_csv(DATA_DIR / "fluids.csv", ["fluid_name"])
    row = fluids[fluids["fluid_name"].astype(str) == str(name)]
    if not row.empty:
        r = row.iloc[0]
        return (_sf(r.get("rho_kg_m3"), 1000.0), _sf(r.get("mu_Pa_s"), 0.001),
                _sf(r.get("D_mol_m2_s"), 2.3e-9), True, "Custom fluid — fixed properties.")
    return 1000.0, 0.001, 2.3e-9, True, ""


def _reaction_context(name: str) -> dict:
    row = _reaction_row(name)
    if row.empty:
        return {"t_rxn": 1.0, "k": 0.0, "C0": 0.0, "order": "1", "T_C": 25.0, "dH": 0.0,
                "solvent": "", "name": name}
    order = str(row.get("order", "1"))
    k = _sf(row.get("k_value"))
    C0 = _sf(row.get("C0_mol_L"))
    t_rxn = _sf(row.get("t_rxn_s"))
    if t_rxn <= 0:
        if order in ("1", "pseudo-1") and k > 0:
            t_rxn = 1.0 / k
        elif order in ("2", "pseudo-2") and k * C0 > 0:
            t_rxn = 1.0 / (k * C0)
        else:
            t_rxn = 1.0
    return {"t_rxn": t_rxn, "k": k, "C0": C0, "order": order,
            "T_C": _sf(row.get("T_C"), 25.0), "dH": _sf(row.get("delta_H_kJ_mol")),
            "solvent": str(row.get("solvent", "") or ""), "name": name}


# ---------------------------------------------------------------------------
# Option lists
# ---------------------------------------------------------------------------
reactor_options = reactors_df["reactor_name"].dropna().astype(str).tolist()
_solvent_names = sorted(SOLVENT_DB.keys())
_custom_names = fluids_df["fluid_name"].dropna().astype(str).tolist()
fluid_options = _solvent_names + _custom_names
reaction_options = reactions_df["reaction_name"].dropna().astype(str).tolist()
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
vc_reaction = reaction_options[0] if reaction_options else ""
vc_T_cool = 15.0
vc_viewers_html = _viewers_html(vc_reactors)

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
vc_fed_mode = "Off"
vc_feed_rate = 5.0
vc_feed_diam = 3.0
vc_feed_location = "Bulk (mid-liquid)"
vc_feed_location_options = ["Near impeller", "Bulk (mid-liquid)", "Surface"]

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
    """Auto-select the reaction's solvent + temperature when known."""
    ctx = _reaction_context(state.vc_reaction)
    resolved = resolve_solvent_name(ctx["solvent"]) if ctx["solvent"] else None
    if resolved and resolved in fluid_options:
        state.vc_fluid = resolved
        if ctx["T_C"] > 0:
            state.vc_T = ctx["T_C"]
    _mark_stale(state)


def on_vc_reactors_change(state):
    if state.vc_basis not in (state.vc_reactors or []):
        state.vc_basis = state.vc_reactors[0] if state.vc_reactors else ""
    state.vc_viewers_html = _viewers_html(state.vc_reactors)
    _build_targets(state)
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


def _avg(row, kmin, kmax, fallback):
    lo, hi = _sf(row.get(kmin)), _sf(row.get(kmax))
    if lo > 0 and hi > 0:
        return (lo + hi) / 2.0
    return hi or lo or fallback


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


# ---------------------------------------------------------------------------
# Core compute
# ---------------------------------------------------------------------------
def _corner_and_curves(names, ctx):
    """Return (env_rows, reactor_info, curve_data, skipped) for all reactors."""
    env_rows, reactor_info, curve_data, skipped = [], {}, {}, []
    rho, mu, D_mol = ctx["rho"], ctx["mu"], ctx["D_mol"]
    v_s, coal, t_rxn = ctx["v_s"], ctx["coalescing"], ctx["t_rxn"]
    incl_p, incl_h = ctx["incl_particles"], ctx["incl_heat"]

    for name in names:
        r = _reactor_row(name)
        D_imp, D_tank, H_max = _sf(r.get("D_imp_m")), _sf(r.get("D_tank_m")), _sf(r.get("H_m"))
        Np, Nq = _sf(r.get("Np"), 1.27), _sf(r.get("Nq"), 0.79)
        scale = str(r.get("scale", "") or "")
        if D_imp <= 0 or D_tank <= 0 or H_max <= 0:
            skipped.append(name)
            continue
        rpm_min, rpm_max = _sf(r.get("N_rpm_min")), _sf(r.get("N_rpm_max"))
        n_rps = _sf(r.get("N_rps"))
        if rpm_max <= 0 and n_rps > 0:
            rpm_max = n_rps * 60.0
        if rpm_max <= 0:
            skipped.append(name)
            continue
        # Without a distinct minimum, sweep from 10% of max so the envelope has
        # horizontal extent (otherwise the curve collapses to a single point).
        if rpm_min <= 0 or rpm_min >= rpm_max:
            rpm_min = rpm_max * 0.1
        N_lo, N_hi = rpm_min / 60.0, rpm_max / 60.0

        V_geo = np.pi / 4 * D_tank**2 * H_max * 1000.0
        V_max = _sf(r.get("V_L_max")) or _sf(r.get("V_L")) or V_geo
        V_min = _sf(r.get("V_L_min")) or V_max
        dish = str(r.get("bottom_dish", "") or "")

        info = {
            "D_imp": D_imp, "D_tank": D_tank, "H_max": H_max, "Np": Np, "Nq": Nq,
            "N_lo": N_lo, "N_hi": N_hi, "V_max_L": V_max, "V_min_L": V_min,
            "rpm_max": rpm_max, "bottom_dish": dish, "scale": scale,
            "shell_material": str(r.get("shell_material", "") or ""),
            "lining_material": str(r.get("lining_material", "") or ""),
            "wall_thickness_mm": _sf(r.get("wall_thickness_mm")),
        }
        reactor_info[name] = info

        # Static particle quantities (RPM-independent)
        part_static = None
        if incl_p and ctx["d50"] > 0:
            d_p = ctx["d50"] * 1e-6
            nu = mu / rho if rho > 0 else 0.0
            drho = abs(ctx["rho_p"] - rho)
            vt = settling_velocity(d_p, ctx["rho_p"], rho, mu, ctx["phi"])
            rep = particle_reynolds(d_p, vt, rho, mu)
            njs_zw = zwietering_njs(ctx["szw"], nu, d_p, drho, rho, ctx["x_wt"], D_imp)
            njs_gmb = gmb_njs(ctx["gmb_z"], Np, D_imp, d_p, drho, rho, ctx["x_vol"], ctx["cd"])
            njs = max(njs_zw, njs_gmb)
            part_static = {"d_p": d_p, "vt": vt, "rep": rep, "njs_rps": njs,
                           "njs_rpm": njs * 60.0, "phi_s": ctx["x_vol"] / 100.0}

        # 4 corners
        for label, N, V_L in [
            (CORNER_LABELS[0], N_lo, V_max), (CORNER_LABELS[1], N_hi, V_max),
            (CORNER_LABELS[2], N_lo, V_min), (CORNER_LABELS[3], N_hi, V_min),
        ]:
            row_vals = _point(name, info, N, V_L, ctx, part_static)
            env_rows.append({"Reactor": name, "Scale": scale, "Corner": label,
                             "N (rev/s)": N, "RPM": N * 60.0, "RPM_max": rpm_max,
                             "V_L": V_L, "Volume (L)": V_L, **row_vals})

        # Boundary curves (min & max V) across the RPM range
        N_arr = np.linspace(N_lo, N_hi, _N_INTERP)
        pct_arr = N_arr / N_hi * 100.0 if N_hi > 0 else np.zeros(_N_INTERP)
        curves = {"pct_arr": pct_arr}
        plot_params = ctx["plot_params"]
        for vol_key, V_L in [("maxV", V_max), ("minV", V_min)]:
            arrs = {p: np.full(_N_INTERP, np.nan) for p in plot_params}
            for j, N in enumerate(N_arr):
                vals = _point(name, info, N, V_L, ctx, part_static)
                for p in plot_params:
                    arrs[p][j] = vals.get(p, np.nan)
            curves[vol_key] = arrs
        curve_data[name] = curves

    return env_rows, reactor_info, curve_data, skipped


def _point(name, info, N, V_L, ctx, part_static) -> dict:
    """Full hydro + Da (+ particle + heat) values at one (RPM, volume) point."""
    rho, mu, D_mol = ctx["rho"], ctx["mu"], ctx["D_mol"]
    H_v = liquid_height_from_volume(V_L, info["D_tank"], info["H_max"], info["bottom_dish"])
    h, _src = compute_reactor_hydro_with_mode(
        "Literature", name, N=N, D_imp=info["D_imp"], D_tank=info["D_tank"], H=H_v,
        rho=rho, mu=mu, Np=info["Np"], Nq=info["Nq"],
        v_s=ctx["v_s"], coalescing=ctx["coalescing"], D_mol=D_mol)

    kla_sl = 0.0
    part_vals = {}
    if part_static is not None:
        d_p = part_static["d_p"]
        eps_kg = h.get("P/V (W/kg)", 0.0)
        v_slip = max(part_static["vt"], (eps_kg * d_p) ** (1.0 / 3.0) if eps_kg > 0 else 0.0)
        ksl = solid_liquid_mass_transfer(d_p, v_slip, rho, mu, D_mol)
        kla_sl = solid_liquid_kla(ksl, d_p, part_static["phi_s"])
        njs_rps = part_static["njs_rps"]
        part_vals = {
            "N_js (RPM)": part_static["njs_rpm"],
            "N/N_js": N / njs_rps if njs_rps > 0 else 0.0,
            "v_t (m/s)": part_static["vt"], "Re_p": part_static["rep"],
            "k_SL (m/s)": ksl, "kLa_SL (1/s)": kla_sl,
        }

    da = compute_damkohler_numbers(
        h["Blend time 95% (s)"], h["Micromix time t_E (s)"], ctx["t_rxn"],
        kLa=h.get("kLa (1/s)", 0.0), kLa_surface=h.get("kLa_surface (1/s)", 0.0),
        kLa_SL=kla_sl)

    meso_vals = {}
    if ctx["fed"]:
        d_feed = ctx["feed_diam"] / 1000.0  # mm -> m
        loc = str(ctx["feed_loc"])
        if loc.startswith("Near impeller"):
            eps_feed = h.get("ε_max (W/kg)", 0.0)
        elif loc.startswith("Surface"):
            eps_feed = 0.2 * h.get("P/V (W/kg)", 0.0)
        else:
            eps_feed = h.get("P/V (W/kg)", 0.0)
        t_meso = mesomixing_time(eps_feed, d_feed)
        meso_vals["Da_meso"] = (t_meso / ctx["t_rxn"]
                                if ctx["t_rxn"] > 0 and np.isfinite(t_meso) else 0.0)

    heat_vals = {}
    if ctx["incl_heat"]:
        r_mol_s = reaction_rate_mol_per_s(ctx["order"], ctx["k"], ctx["C0"], V_L)
        Q_gen = heat_generation_rate(ctx["dH"], r_mol_s)
        A_ht = estimate_jacket_area(info["D_tank"], H_v, info["bottom_dish"])
        U_ht, _w = estimate_U_detailed(
            N_rps=N, D_imp=info["D_imp"], D_tank=info["D_tank"], rho=rho, mu=mu,
            material=info["shell_material"], lining_material=info["lining_material"],
            wall_thickness_mm=info["wall_thickness_mm"], fluid_name=ctx["fluid_name"])
        dT = ctx["T_process"] - ctx["T_coolant"]
        Q_cool = heat_removal_capacity(U_ht, A_ht, dT)
        heat_vals = {
            "Q_gen (W)": Q_gen, "Q_cool (W)": Q_cool, "U (W/m²·K)": U_ht,
            "A_ht (m²)": A_ht,
            "Q_gen/Q_cool (%)": Q_gen / Q_cool * 100.0 if Q_cool > 0 else np.inf,
        }
    return {**h, **da, **meso_vals, **part_vals, **heat_vals}


def _hydro_only(name, info, N, V_L, ctx) -> dict:
    """Hydro dict at one point (used by the scale-up solver)."""
    H_v = liquid_height_from_volume(V_L, info["D_tank"], info["H_max"], info["bottom_dish"])
    h, _src = compute_reactor_hydro_with_mode(
        "Literature", name, N=N, D_imp=info["D_imp"], D_tank=info["D_tank"], H=H_v,
        rho=ctx["rho"], mu=ctx["mu"], Np=info["Np"], Nq=info["Nq"],
        v_s=ctx["v_s"], coalescing=ctx["coalescing"], D_mol=ctx["D_mol"])
    return h


def _reactor_geo(name):
    r = _reactor_row(name)
    D_imp, D_tank, H_max = _sf(r.get("D_imp_m")), _sf(r.get("D_tank_m")), _sf(r.get("H_m"))
    return {
        "D_imp": D_imp, "D_tank": D_tank, "H_max": H_max,
        "Np": _sf(r.get("Np"), 1.27), "Nq": _sf(r.get("Nq"), 0.79),
        "bottom_dish": str(r.get("bottom_dish", "") or ""),
    }


def on_vc_compute(state):
    names = list(state.vc_reactors or [])
    if not names:
        notify(state, "W", "Select at least one vessel to compare.")
        return

    rho, mu, D_mol, in_range, note = _fluid_props(state.vc_fluid, state.vc_T, state.vc_P)
    rxn = _reaction_context(state.vc_reaction)
    incl_p = state.vc_incl_particles == "On" and _sf(state.vc_d50) > 0
    incl_h = rxn["dH"] != 0.0
    gas_on = state.vc_gas_mode == "On"
    fed_on = state.vc_fed_mode == "On"
    x_wt = _sf(state.vc_x_wt)
    x_vol = (100.0 * x_wt * rho / (x_wt * rho + 100.0 * _sf(state.vc_rho_p))
             if incl_p and _sf(state.vc_rho_p) > 0 else 0.0)

    plot_params = list(_BASE_PLOT_PARAMS)
    if fed_on:
        plot_params.insert(plot_params.index("Da_micro") + 1, "Da_meso")
    if incl_h:
        plot_params += _HEAT_PARAMS
    if incl_p:
        plot_params += _PARTICLE_PARAMS

    v_s = _sf(state.vc_vs) if (gas_on and state.vc_gas_transfer == "Sparging") else 0.0
    ctx = {
        "rho": rho, "mu": mu, "D_mol": D_mol, "v_s": v_s,
        "coalescing": state.vc_coal.startswith("Coalescing"),
        "t_rxn": rxn["t_rxn"], "order": rxn["order"], "k": rxn["k"], "C0": rxn["C0"],
        "dH": rxn["dH"], "incl_heat": incl_h, "incl_particles": incl_p, "gas_on": gas_on,
        "fed": fed_on, "feed_diam": _sf(state.vc_feed_diam), "feed_loc": state.vc_feed_location,
        "rho_p": _sf(state.vc_rho_p), "d50": _sf(state.vc_d50), "phi": _sf(state.vc_phi),
        "x_wt": x_wt, "x_vol": x_vol, "szw": _sf(state.vc_szw, 5.5),
        "gmb_z": _sf(state.vc_gmb_z, 3.0), "cd": _sf(state.vc_cd, 0.33),
        "T_process": state.vc_T, "T_coolant": _sf(state.vc_T_cool),
        "fluid_name": state.vc_fluid, "plot_params": plot_params,
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

    state.vc_pdf_ready = False
    state.vc_ready = True
    state.vc_stale = False
    state.vc_compute_class = "compute-btn-ok"
    msg = f"Compared {len(reactor_info)} vessel(s) across the 4-corner envelope."
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

    b_info = reactor_info[basis]
    b_N = _sf(state.vc_basis_rpm) / 60.0
    b_hydro = _hydro_only(basis, b_info, b_N, _sf(state.vc_basis_vol), ctx)
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
        info = reactor_info[name]
        r = _reactor_row(name)
        rpm_max = _sf(r.get("N_rpm_max")) or _sf(r.get("N_rps")) * 60.0
        rpm_min = _sf(r.get("N_rpm_min")) or 1.0
        V_max = _sf(r.get("V_L_max")) or _sf(r.get("V_L")) or (
            np.pi / 4 * info["D_tank"]**2 * info["H_max"] * 1000.0)
        V_min = _sf(r.get("V_L_min")) or V_max * 0.1
        kv = known.get(name, 0.0)

        if solve_rpm:
            V_L = kv

            def _f(rpm, _V=V_L, _info=info, _name=name):
                return _hydro_only(_name, _info, rpm / 60.0, _V, ctx).get(param, np.nan) - target_value

            lo, hi = max(rpm_min, 0.5), rpm_max * 1.5
            root = _solve_root(_f, lo, hi, tol=0.01)
            if root is None:
                v_lo = _hydro_only(name, info, lo / 60.0, V_L, ctx).get(param, np.nan)
                v_hi = _hydro_only(name, info, hi / 60.0, V_L, ctx).get(param, np.nan)
                best = (lo, v_lo) if abs(v_lo - target_value) < abs(v_hi - target_value) else (hi, v_hi)
                solved_rpm, solved_val = best
                in_rng = rpm_min <= solved_rpm <= rpm_max
                status = f"Not achievable (closest {solved_val:.4g})" + ("" if in_rng else " [outside RPM]")
            else:
                solved_rpm = root
                sh = _hydro_only(name, info, solved_rpm / 60.0, V_L, ctx)
                solved_val = sh.get(param, np.nan)
                in_rng = rpm_min <= solved_rpm <= rpm_max
                status = "Matched" if in_rng else f"Matched (outside {rpm_min:.0f}–{rpm_max:.0f} RPM)"
            sh = _hydro_only(name, info, solved_rpm / 60.0, V_L, ctx)
            results.append({"Reactor": name, "Role": "Target", "RPM": solved_rpm,
                            "Volume (L)": V_L, param: solved_val, "Status": status})
            full.append({"Reactor": name, "Role": "Target", "RPM": solved_rpm,
                         "Volume (L)": V_L, **sh})
        else:
            rpm = kv
            N = rpm / 60.0

            def _f(vol, _N=N, _info=info, _name=name):
                return _hydro_only(_name, _info, _N, vol, ctx).get(param, np.nan) - target_value

            lo, hi = max(V_min * 0.5, 0.001), V_max * 1.2
            root = _solve_root(_f, lo, hi, tol=0.001)
            if root is None:
                v_lo = _hydro_only(name, info, N, lo, ctx).get(param, np.nan)
                v_hi = _hydro_only(name, info, N, hi, ctx).get(param, np.nan)
                best = (lo, v_lo) if abs(v_lo - target_value) < abs(v_hi - target_value) else (hi, v_hi)
                solved_vol, solved_val = best
                in_rng = V_min <= solved_vol <= V_max
                status = f"Not achievable (closest {solved_val:.4g})" + ("" if in_rng else " [outside V]")
            else:
                solved_vol = root
                sh = _hydro_only(name, info, N, solved_vol, ctx)
                solved_val = sh.get(param, np.nan)
                in_rng = V_min <= solved_vol <= V_max
                status = "Matched" if in_rng else f"Matched (outside {V_min:.1f}–{V_max:.1f} L)"
            sh = _hydro_only(name, info, N, solved_vol, ctx)
            results.append({"Reactor": name, "Role": "Target", "RPM": rpm,
                            "Volume (L)": solved_vol, param: solved_val, "Status": status})
            full.append({"Reactor": name, "Role": "Target", "RPM": rpm,
                         "Volume (L)": solved_vol, **sh})

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
    reactors = env_df["Reactor"].drop_duplicates().tolist()
    if len(reactors) < 2:
        state.vc_impact_df = pd.DataFrame()
        return
    mid = env_df.groupby("Reactor", sort=False)[
        [p for p in present if p in env_df.columns] + ["Volume (L)"]].mean()
    ref = mid.iloc[0]
    rows = []
    for name in reactors[1:]:
        row = mid.loc[name]

        def _ratio(col):
            return row[col] / ref[col] if col in ref and ref[col] not in (0, np.nan) and np.isfinite(ref[col]) and ref[col] != 0 else np.nan

        entry = {"From → To": f"{reactors[0]} → {name}",
                 "Volume ×": f"{_ratio('Volume (L)'):.2f}",
                 "P/V ×": f"{_ratio('P/V (W/L)'):.2f}",
                 "Tip speed ×": f"{_ratio('Tip speed (m/s)'):.2f}",
                 "Blend time ×": f"{_ratio('Blend time 95% (s)'):.2f}",
                 "Da_macro ×": f"{_ratio('Da_macro'):.2f}"}
        if ctx["incl_heat"] and "Q_gen/Q_cool (%)" in mid.columns:
            rp, tp = ref.get("Q_gen/Q_cool (%)", np.nan), row.get("Q_gen/Q_cool (%)", np.nan)
            if np.isfinite(rp) and np.isfinite(tp):
                delta = tp - rp
                verdict = ("≈ Similar" if abs(delta) < 1 else
                           (f"✅ Improves ({delta:+.1f} pp)" if delta < 0 else f"⚠️ Worse ({delta:+.1f} pp)"))
                entry["Cooling"] = verdict
        rows.append(entry)
    state.vc_impact_df = pd.DataFrame(rows)


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

<|layout|columns=1 1 1|class_name=form-grid|
<|{vc_fluid}|selector|lov={fluid_options}|dropdown|label=Fluid|on_change=on_vc_input_change|>

<|{vc_T}|number|label=Temperature (°C)|on_change=on_vc_input_change|>

<|{vc_P}|number|label=Pressure (atm)|on_change=on_vc_input_change|>
|>

<|layout|columns=1 1|class_name=form-grid|
<|{vc_reaction}|selector|lov={reaction_options}|dropdown|label=Reaction (for Da numbers)|on_change=on_vc_reaction_change|>

<|{vc_T_cool}|number|label=Coolant temperature (°C)|on_change=on_vc_input_change|>
|>
|>

<|part|class_name=va-card|
## Selected Vessels
Drag to rotate a 3D model; scroll to zoom. The row scrolls sideways when several vessels are selected.

<|part|content={vc_viewers_html}|height=340px|>
|>

<|part|class_name=va-card|
## 2. Options
### __ICON:Particle_Database__Solid particles
<|{vc_incl_particles}|toggle|lov={vc_onoff_options}|label=Include solid particles|class_name=onoff-toggle|on_change=on_vc_input_change|>

<|part|render={vc_incl_particles == "On"}|
Particle properties are shared across all compared vessels.
<|layout|columns=1 1 1 1|class_name=form-grid|
<|{vc_particle}|selector|lov={particle_options}|dropdown|label=Particle|on_change=on_vc_particle_change|>

<|{vc_rho_p}|number|label=ρ_p (kg/m³)|on_change=on_vc_input_change|>

<|{vc_d50}|number|label=d50 (µm)|on_change=on_vc_input_change|>

<|{vc_phi}|number|label=Shape factor φ|on_change=on_vc_input_change|>
|>

<|layout|columns=1 1 1 1|class_name=form-grid|
<|{vc_x_wt}|number|label=Solids loading X (wt-%)|on_change=on_vc_input_change|>

<|{vc_szw}|number|label=Zwietering S|on_change=on_vc_input_change|>

<|{vc_gmb_z}|number|label=GMB z constant|on_change=on_vc_input_change|>

<|{vc_cd}|number|label=C/D (clearance / dia)|on_change=on_vc_input_change|>
|>
|>

### 🫧 Gas
<|{vc_gas_mode}|toggle|lov={vc_onoff_options}|label=Include gas phase|class_name=onoff-toggle|on_change=on_vc_input_change|>

<|part|render={vc_gas_mode == "On"}|
<|{vc_gas_transfer}|toggle|lov={vc_gas_transfer_options}|label=Mass-transfer mode|on_change=on_vc_input_change|>

<|part|render={vc_gas_transfer == "Sparging"}|
<|layout|columns=1 1|class_name=form-grid|
<|{vc_vs}|number|label=Superficial gas velocity v_s (m/s)|on_change=on_vc_input_change|>

<|{vc_coal}|selector|lov={coal_options}|dropdown|label=Liquid type (for kLa)|on_change=on_vc_input_change|>
|>
|>
|>

### 🔁 Fed-batch
<|{vc_fed_mode}|toggle|lov={vc_onoff_options}|label=Fed-batch (semi-batch) addition|class_name=onoff-toggle|on_change=on_vc_input_change|>

<|part|render={vc_fed_mode == "On"}|
Feed inputs unlock the **mesomixing** Damköhler number (Da_meso), evaluated at the feed point.
<|layout|columns=1 1 1|class_name=form-grid|
<|{vc_feed_rate}|number|label=Feed rate (mL/min)|on_change=on_vc_input_change|>

<|{vc_feed_diam}|number|label=Feed pipe ID (mm)|on_change=on_vc_input_change|>

<|{vc_feed_location}|selector|lov={vc_feed_location_options}|dropdown|label=Feed location|on_change=on_vc_input_change|>
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

<|Full 4-corner detail|expandable|expanded=False|
<|{vc_detail_df}|table|width=100%|page_size=16|rebuild|>
|>
|>

<|part|class_name=va-card|
## Stir Speed Reference
Translates a percentage of each vessel's maximum RPM (the chart x-axis) to actual RPM.

<|{vc_rpm_ref_df}|table|width=100%|show_all|rebuild|>
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
|>

<|part|render={len(vc_scale_df) > 0}|class_name=va-card|
## Scale-Up Matching Results
Matched operating conditions that hold the chosen parameter constant relative to the basis vessel.

<|{vc_scale_df}|table|width=100%|show_all|rebuild|>

<|Full parameter comparison at matched conditions|expandable|expanded=False|
<|{vc_scale_full_df}|table|width=100%|show_all|rebuild|>
|>

<|Percentage difference vs. basis vessel|expandable|expanded=False|
<|{vc_scale_pct_df}|table|width=100%|show_all|rebuild|>
|>
|>

<|part|render={len(vc_impact_df) > 0}|class_name=va-card|
## Scale-Up Impact Summary
Ratios use the midpoint (average of the 4 corners) for each parameter, relative to the first selected vessel.

<|{vc_impact_df}|table|width=100%|show_all|rebuild|>
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
