"""Bourne Protocol page (Taipy).

Ported (core workflow) from the Streamlit ``6_Bourne_Protocol.py`` page. Guides
the user through the Bourne (2003) mixing-sensitivity screening protocol:

* **Test 1 — Impeller speed:** does mixing matter at all? (vary P/m over 100×)
* **Test 2 — Feed rate/time:** micromixing vs mesomixing (vary feed rate 9×)
* **Test 3 — Feed location:** macromixing vs mesomixing (surface / mid / impeller)

Each test is *gated*: it only unlocks once the previous test is assessed as
mixing-sensitive. A decision tree then identifies the dominant mixing scale and
gives scale-up recommendations.

Test 1 supports three centre-point selection modes (default 0.2 W/kg, custom
P/m, or custom RPM), tracking of multiple KPIs (combined by majority vote), and
discrete impeller-speed setpoints that hold P/m constant as a fed-batch volume
grows.

Deferred vs the Streamlit page (follow-ups): the speed-vs-fill-volume iso-line
plot, qualitative KPI capture, confirmatory experiments, and PDF/CSV export.
"""
from __future__ import annotations

import csv
import io
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from taipy.gui import Markdown, notify

from utils.menu_icons import inject_icons
from utils.calculations import (
    blend_time_turbulent,
    impeller_power,
    kolmogorov_length,
    liquid_height_from_volume,
    micromixing_time_engulfment,
    power_per_volume,
    reynolds_number,
    tip_speed,
)
from utils.solvent_properties import (
    get_properties,
    is_known_solvent,
    list_solvents,
    resolve_solvent_name,
)
from utils.report_builder import build_bourne_protocol_pdf, report_filename
from pages import _db_common as db
from vessel_media import build_image_html, build_vessel_viewer_html, media_caption

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
reactors_df = pd.read_csv(DATA_DIR / "reactors.csv")
fluids_df = pd.read_csv(DATA_DIR / "fluids.csv")

IMAGES_DIR = Path(__file__).resolve().parent.parent / "images" / "general"
bp_decision_tree_html = build_image_html(
    IMAGES_DIR / "bourne_protocol_decision_tree.png", alt="Bourne Protocol decision tree")

VIEWER_H = 360
RESPONSE_METRICS = ["Yield", "Purity", "Conversion", "Selectivity",
                    "Impurity level", "Particle size (D50)", "Other"]
# Per-column dropdown options for the editable KPI tables. A trailing ``None``
# keeps the cell "free" (a custom value can still be typed in).
KPI_METRIC_OPTIONS = RESPONSE_METRICS + [None]
UNIT_OPTIONS = ["%", "ppm", "area%", "wt%", "mol%", "µm", "g/L", "AU", None]
_SENS_THRESHOLD = 5.0  # % change from centre that counts as "sensitive"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _sf(val, default=0.0) -> float:
    try:
        f = float(val)
        return default if np.isnan(f) else f
    except (TypeError, ValueError):
        return default


def _avg_range(row: pd.Series, min_key: str, max_key: str, fallback: float) -> float:
    """Midpoint of a reactor's min/max range (fill volume, agitation speed).

    Falls back to whichever bound is available, then to ``fallback``."""
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
    df = db.fresh_csv(DATA_DIR / "reactors.csv", ["reactor_name"])
    row = df[df["reactor_name"].astype(str) == str(name)]
    return row.iloc[0] if not row.empty else pd.Series(dtype=object)


def _blend_geometry(state) -> tuple[float, float]:
    """Return tank diameter and current liquid height in metres."""
    row = _reactor_row(state.bp_reactor)
    tank_diameter = _sf(row.get("D_tank_m"))
    max_height = _sf(row.get("H_max_m"), _sf(row.get("H_m")))
    dish = str(row.get("bottom_dish", "") or "")
    liquid_height = liquid_height_from_volume(
        state.bp_v_l, tank_diameter, max_height, dish,
    )
    return tank_diameter, liquid_height


def _reactor_id(name: str) -> str:
    row = _reactor_row(name)
    return "" if row.empty else str(row.get("reactor_id", "") or "")


def _fluid_props(name: str, T_C: float, P_atm: float = 1.0) -> tuple[float, float]:
    """Return (rho, mu) for a solvent (at T, P) or a custom fluid."""
    if is_known_solvent(name):
        p = get_properties(resolve_solvent_name(name) or name, T_C, P_atm)
        return p["rho_kg_m3"], p["mu_Pa_s"]
    fluids = db.fresh_csv(DATA_DIR / "fluids.csv", ["fluid_name"])
    row = fluids[fluids["fluid_name"].astype(str) == str(name)]
    if not row.empty:
        r = row.iloc[0]
        return _sf(r.get("rho_kg_m3"), 1000.0), _sf(r.get("mu_Pa_s"), 0.001)
    return 1000.0, 0.001


def _assess(low: float, center: float, high: float) -> tuple[float, bool]:
    """Return (max % change from centre, sensitive?)."""
    if center == 0:
        span = max(abs(low), abs(high))
        if span == 0:
            return 0.0, False
        max_pct = 100.0
        return max_pct, True
    max_pct = max(abs(v - center) / abs(center) * 100.0 for v in (low, center, high))
    return max_pct, max_pct >= _SENS_THRESHOLD


def _n_for_pm(pm_wkg: float, V_m3: float, Np: float, D: float) -> float:
    """Impeller speed (rev/s) that delivers a given specific power P/m (W/kg)."""
    if Np <= 0 or D <= 0 or V_m3 <= 0 or pm_wkg <= 0:
        return 0.0
    return (pm_wkg * V_m3 / (Np * D**5)) ** (1.0 / 3.0)


def _reactor_summary_df(row: pd.Series) -> pd.DataFrame:
    """Small Property/Value/Units table of a reactor's volume & speed limits."""
    vmin = _sf(row.get("V_L_min"))
    vmax = _sf(row.get("V_L_max"), _sf(row.get("V_L")))
    nmin = _sf(row.get("N_rpm_min"))
    nmax = _sf(row.get("N_rpm_max"))
    dimp = _sf(row.get("D_imp_m"))
    Np = _sf(row.get("Np"))

    def _rng(a, b):
        if a <= 0 and b <= 0:
            return "—"
        if a > 0 and b > 0:
            return f"{a:g} – {b:g}"
        return f"{(a or b):g}"

    rows = [
        {"Property": "Working volume", "Value": _rng(vmin, vmax), "Units": "L"},
        {"Property": "Impeller speed", "Value": _rng(nmin, nmax), "Units": "RPM"},
        {"Property": "Impeller diameter", "Value": f"{dimp:g}" if dimp > 0 else "—", "Units": "m"},
        {"Property": "Power number Np", "Value": f"{Np:g}" if Np > 0 else "—", "Units": "–"},
    ]
    return pd.DataFrame(rows)


# Per-test KPI response column names (low / centre / high condition).
KPI_COLUMNS = {
    1: ("Low speed", "Centre", "High speed"),
    2: ("Slow feed", "Centre", "Fast feed"),
    3: ("Surface", "Mid", "Impeller"),
}


def _new_kpi_df(test: int, seed_names=(("Yield", "%"),)) -> pd.DataFrame:
    """Build a fresh KPI response table for a test with zeroed responses."""
    low, ctr, high = KPI_COLUMNS[test]
    rows = [{"KPI": n, "Unit": u, low: 0.0, ctr: 0.0, high: 0.0}
            for n, u in seed_names]
    return pd.DataFrame(rows)


def _mirror_kpis(src_df: pd.DataFrame, test: int) -> pd.DataFrame:
    """Copy KPI names/units from an upstream test, zeroing the responses."""
    names = [(str(r.get("KPI", "") or "Yield").strip() or "Yield",
              str(r.get("Unit", "") or "").strip())
             for _, r in src_df.iterrows()]
    if not names:
        names = [("Yield", "%")]
    return _new_kpi_df(test, seed_names=names)


def _empty_result(test: int) -> pd.DataFrame:
    low, ctr, high = KPI_COLUMNS[test]
    return pd.DataFrame(columns=["KPI", low, ctr, high, "Max Δ (%)", "Sensitive?"])


def _assess_kpis(df: pd.DataFrame, test: int):
    """Assess a KPI response table; return a result dict or None if no data.

    Each KPI is judged sensitive at a >= ``_SENS_THRESHOLD`` % change from its
    centre value. Rows with no data (all three responses zero) are skipped. The
    overall verdict uses a majority vote across KPIs.
    """
    low, ctr, high = KPI_COLUMNS[test]
    results = []
    for _, r in df.iterrows():
        lo, ce, hi = _sf(r.get(low)), _sf(r.get(ctr)), _sf(r.get(high))
        if lo == 0.0 and ce == 0.0 and hi == 0.0:
            continue
        name = (str(r.get("KPI", "") or "KPI").strip() or "KPI")
        unit = str(r.get("Unit", "") or "").strip()
        max_pct, sensitive = _assess(lo, ce, hi)
        results.append({"name": name, "unit": unit, "low": lo, "ctr": ce,
                        "high": hi, "max_pct": max_pct, "sensitive": sensitive})
    if not results:
        return None
    n_total = len(results)
    n_sensitive = sum(1 for r in results if r["sensitive"])
    if n_sensitive == 0:
        status = "not_sensitive"
    elif n_sensitive > n_total / 2:
        status = "sensitive"
    else:
        status = "may_be_sensitive"
    table = pd.DataFrame([{
        "KPI": f'{r["name"]} ({r["unit"]})' if r["unit"] else r["name"],
        low: f'{r["low"]:g}', ctr: f'{r["ctr"]:g}', high: f'{r["high"]:g}',
        "Max Δ (%)": f'{r["max_pct"]:.1f}%',
        "Sensitive?": "Yes" if r["sensitive"] else "No",
    } for r in results])
    sens_names = "; ".join(
        f'{r["name"]} ({r["max_pct"]:.1f}%)' for r in results if r["sensitive"])
    return {
        "results": results, "n_total": n_total, "n_sensitive": n_sensitive,
        "status": status, "sensitive": status != "not_sensitive",
        "sensitive_names": sens_names, "table": table,
    }


def _kpi_prefix(res: dict) -> str:
    """Leading verdict sentence summarising the majority-vote KPI outcome."""
    n, N = res["n_sensitive"], res["n_total"]
    thr = _SENS_THRESHOLD
    if res["status"] == "sensitive":
        return (f"⚠️ **Sensitive** — {n} of {N} KPI(s) changed ≥ {thr:.0f}% "
                f"({res['sensitive_names']}).")
    if res["status"] == "may_be_sensitive":
        return (f"⚠️ **Possibly sensitive** — only {n} of {N} KPI(s) changed "
                f"≥ {thr:.0f}% ({res['sensitive_names']}); mixed signal.")
    return f"✅ **Not sensitive** — no KPI changed ≥ {thr:.0f}% across {N} KPI(s)."


def _resolve_center_pm(state) -> tuple[float, str]:
    """Resolve the Test 1 centre-point P/m (W/kg) and an info caption.

    Modes: default 0.2 W/kg (Sarafinas 2018), a custom P/m, or a custom RPM
    (converted to P/m via the power draw).
    """
    D, Np, rho = state.bp_d_imp, state.bp_np, state.bp_rho
    V_m3 = state.bp_v_l / 1000.0
    n_min, n_max = state.bp_n_min, state.bp_n_max
    mode = state.bp_t1_ctr_mode

    if mode == "Custom RPM":
        rpm = max(_sf(state.bp_t1_rpm_center), 1e-9)
        n_rps = rpm / 60.0
        P = impeller_power(Np, rho, n_rps, D)
        pm = (power_per_volume(P, V_m3) / rho) if (V_m3 > 0 and rho > 0) else 0.0
        info = (f"Custom centre: **N = {rpm:.1f} RPM** → **P/m = {pm:.4g} W/kg** "
                f"({power_per_volume(P, V_m3) / 1000:.4g} W/L).")
        if n_max > 0 and (rpm > n_max or rpm < n_min):
            info += f" ⚠ Outside reactor range ({n_min:.0f}–{n_max:.0f} RPM)."
        return pm, info

    if mode == "Custom P/m":
        pm = max(_sf(state.bp_t1_pm_center), 0.0)
        n_rpm = _n_for_pm(pm, V_m3, Np, D) * 60.0
        return pm, f"Custom centre: **P/m = {pm:.4g} W/kg** at **N = {n_rpm:.0f} RPM**."

    # Default 0.2 W/kg
    pm = 0.2
    n_rpm = _n_for_pm(pm, V_m3, Np, D) * 60.0
    info = f"Default centre (Sarafinas 2018): **P/m = 0.2 W/kg** at **N = {n_rpm:.0f} RPM**."
    if n_max > 0:
        if n_rpm < n_min or n_rpm > n_max:
            info += (f" ⚠ Requires {n_rpm:.0f} RPM — outside reactor range "
                     f"({n_min:.0f}–{n_max:.0f} RPM).")
        else:
            info += f" Within reactor range ({n_min:.0f}–{n_max:.0f} RPM)."
    return pm, info


# ---------------------------------------------------------------------------
# Option lists
# ---------------------------------------------------------------------------
reactor_options = sorted(reactors_df["reactor_name"].dropna().astype(str).unique().tolist())
fluid_options = sorted(list_solvents() + fluids_df["fluid_name"].dropna().astype(str).tolist())

# ---------------------------------------------------------------------------
# State — system definition
# ---------------------------------------------------------------------------
bp_reactor = ("TMA EasyMax-102" if "TMA EasyMax-102" in reactor_options
              else (reactor_options[0] if reactor_options else ""))
bp_fluid = "Water" if "Water" in fluid_options else fluid_options[0]
bp_T = 25.0
bp_P = 1.0

_r0 = _reactor_row(bp_reactor)
bp_d_imp = _sf(_r0.get("D_imp_m"), 0.05)
bp_np = _sf(_r0.get("Np"), 5.0)
bp_nq = _sf(_r0.get("Nq"), 0.79)
bp_n_min = _sf(_r0.get("N_rpm_min"), 0.0)
bp_n_max = _sf(_r0.get("N_rpm_max"), 1000.0)
bp_v_l = _avg_range(_r0, "V_L_min", "V_L_max", _sf(_r0.get("V_L"), 1.0))
bp_v_min = _sf(_r0.get("V_L_min"), 0.0)
bp_v_max = _sf(_r0.get("V_L_max"), _sf(_r0.get("V_L"), bp_v_l))
bp_reactor_summary_df = _reactor_summary_df(_r0)
bp_rho, bp_mu = _fluid_props(bp_fluid, bp_T, bp_P)

bp_viewer_html = build_vessel_viewer_html(_reactor_id(bp_reactor), VIEWER_H)
bp_media_caption = media_caption(_reactor_id(bp_reactor))

bp_status = "Define the system, then click Start Protocol."
bp_started = False

# ---------------------------------------------------------------------------
# State — Test 1 (impeller speed)
# ---------------------------------------------------------------------------
bp_t1_ctr_mode = "Default (0.2 W/kg)"
bp_t1_ctr_mode_options = ["Default (0.2 W/kg)", "Custom P/m", "Custom RPM"]
bp_t1_pm_center = 0.2    # W/kg (Custom P/m mode)
bp_t1_rpm_center = _avg_range(_r0, "N_rpm_min", "N_rpm_max", 300.0)  # RPM (Custom RPM mode)
bp_t1_pm_eff = 0.2       # resolved centre P/m (W/kg), used by Tests 1 & 3
bp_t1_ctr_info = ""
bp_t1_hydro_df = pd.DataFrame(columns=["Condition", "N (RPM)", "P/m (W/kg)", "P/V (W/L)",
                                       "Tip speed (m/s)", "Re", "Blend time (s)",
                                       "t_E micro (s)", "η (µm)"])
bp_t1_kpi_df = _new_kpi_df(1)
bp_t1_kpi_result_df = _empty_result(1)
bp_t1_result = None
bp_t1_assessed = False
bp_t1_sensitive = False
bp_t1_verdict = ""
bp_show_t2 = False

# Discrete speed adjustments (fed-batch: hold P/m as volume grows)
bp_t1_adj_mode = "Off"
bp_t1_adj_mode_options = ["Off", "On"]
bp_t1_adj_vols_df = pd.DataFrame(columns=["Volume (L)"])
bp_t1_adj_result_df = pd.DataFrame(columns=["Step", "Volume (L)", "Low (RPM)",
                                            "Centre (RPM)", "High (RPM)"])
bp_t1_adj_caption = ""

# Speed vs fill-volume iso-P/m plot
bp_t1_plot = go.Figure()
bp_t1_show_plot = False

# ---------------------------------------------------------------------------
# State — Test 2 (feed rate / time)
# ---------------------------------------------------------------------------
bp_t2_feed_vol = 100.0  # mL
bp_t2_mode = "Feed rate"
bp_t2_mode_options = ["Feed rate", "Feed time"]
bp_t2_rate = 5.0        # mL/min
bp_t2_time = 20.0       # min
bp_t2_cond_df = pd.DataFrame(columns=["Condition", "Feed time (min)", "Flow rate (mL/min)", "Note"])
bp_t2_kpi_df = _new_kpi_df(2)
bp_t2_kpi_result_df = _empty_result(2)
bp_t2_result = None
bp_t2_assessed = False
bp_t2_sensitive = False
bp_t2_verdict = ""
bp_show_t3 = False

# ---------------------------------------------------------------------------
# State — Test 3 (feed location)
# ---------------------------------------------------------------------------
bp_t3_cond_df = pd.DataFrame(columns=["Feed location", "ε_loc/ε_avg", "ε_loc (W/kg)", "t_E micro (s)"])
bp_t3_kpi_df = _new_kpi_df(3)
bp_t3_kpi_result_df = _empty_result(3)
bp_t3_result = None
bp_t3_assessed = False
bp_t3_sensitive = False
bp_t3_verdict = ""

# ---------------------------------------------------------------------------
# State — summary
# ---------------------------------------------------------------------------
bp_summary = ""
bp_show_summary = False

# PDF export
bp_pdf_bytes = b""
bp_pdf_name = "Bourne_Protocol.pdf"
bp_pdf_ready = False

# CSV export for the Reaction Sensitivity Protocol
bp_sens_csv_bytes = b""
bp_sens_csv_name = "Bourne_for_Sensitivity.csv"
bp_sens_csv_ready = False


# ---------------------------------------------------------------------------
# Change handlers
# ---------------------------------------------------------------------------
def on_bp_reactor_change(state):
    row = _reactor_row(state.bp_reactor)
    state.bp_d_imp = _sf(row.get("D_imp_m"), state.bp_d_imp)
    state.bp_np = _sf(row.get("Np"), state.bp_np)
    state.bp_nq = _sf(row.get("Nq"), state.bp_nq)
    state.bp_n_min = _sf(row.get("N_rpm_min"), 0.0)
    state.bp_n_max = _sf(row.get("N_rpm_max"), 1000.0)
    state.bp_t1_rpm_center = _avg_range(row, "N_rpm_min", "N_rpm_max", state.bp_t1_rpm_center)
    state.bp_v_l = _avg_range(row, "V_L_min", "V_L_max", _sf(row.get("V_L"), state.bp_v_l))
    state.bp_v_min = _sf(row.get("V_L_min"), 0.0)
    state.bp_v_max = _sf(row.get("V_L_max"), _sf(row.get("V_L"), state.bp_v_l))
    state.bp_reactor_summary_df = _reactor_summary_df(row)
    rid = _reactor_id(state.bp_reactor)
    state.bp_viewer_html = build_vessel_viewer_html(rid, VIEWER_H)
    state.bp_media_caption = media_caption(rid)


def _load_fluid(state):
    state.bp_rho, state.bp_mu = _fluid_props(state.bp_fluid, state.bp_T, state.bp_P)


def on_bp_fluid_change(state):
    _load_fluid(state)


def on_bp_sys_change(state):
    if is_known_solvent(state.bp_fluid):
        _load_fluid(state)


# ---------------------------------------------------------------------------
# Test 1
# ---------------------------------------------------------------------------
def _build_t1(state):
    D, Np, rho, mu = state.bp_d_imp, state.bp_np, state.bp_rho, state.bp_mu
    T, H = _blend_geometry(state)
    nu = mu / rho if rho > 0 else 0.0
    V_m3 = state.bp_v_l / 1000.0
    pm_c, info = _resolve_center_pm(state)
    state.bp_t1_pm_eff = pm_c
    state.bp_t1_ctr_info = info
    rows = []
    for label, factor in (("Low (0.1× P/m)", 0.1), ("Centre (1× P/m)", 1.0), ("High (10× P/m)", 10.0)):
        pm = pm_c * factor
        n_rps = _n_for_pm(pm, V_m3, Np, D)
        n_rpm = n_rps * 60.0
        note = ""
        if state.bp_n_max > 0 and n_rpm > state.bp_n_max:
            n_rpm, note = state.bp_n_max, " (clamped to N_max)"
            n_rps = n_rpm / 60.0
        if state.bp_n_min > 0 and n_rpm < state.bp_n_min:
            n_rpm, note = state.bp_n_min, " (clamped to N_min)"
            n_rps = n_rpm / 60.0
        P = impeller_power(Np, rho, n_rps, D)
        eps = power_per_volume(P, V_m3) if V_m3 > 0 else 0.0
        eps_kg = eps / rho if rho > 0 else 0.0
        rows.append({
            "Condition": label + note,
            "N (RPM)": f"{n_rpm:,.1f}",
            "P/m (W/kg)": f"{eps_kg:.4g}",
            "P/V (W/L)": f"{eps / 1000.0:.4g}",
            "Tip speed (m/s)": f"{tip_speed(n_rps, D):.3g}",
            "Re": f"{reynolds_number(n_rps, D, rho, mu):,.0f}",
            "Blend time (s)": f"{blend_time_turbulent(Np, n_rps, D, T, H):.3g}",
            "t_E micro (s)": f"{micromixing_time_engulfment(eps_kg, nu):.3g}",
            "η (µm)": f"{kolmogorov_length(nu, eps_kg) * 1e6:.3g}",
        })
    state.bp_t1_hydro_df = pd.DataFrame(rows)
    if state.bp_t1_adj_mode == "On":
        _build_t1_adj(state)
    _build_t1_plot(state)


def _build_t1_plot(state):
    """Impeller-speed vs fill-volume iso-P/m plot (0.1× / 1× / 10× centre)."""
    v_min, v_max = state.bp_v_min, state.bp_v_max
    if not (v_max > v_min > 0):
        state.bp_t1_show_plot = False
        state.bp_t1_plot = go.Figure()
        return
    state.bp_t1_show_plot = True
    D, Np = state.bp_d_imp, state.bp_np
    pm_c = state.bp_t1_pm_eff
    vols = np.linspace(v_min, v_max, 50)
    targets = [("0.1× P/m", pm_c * 0.1, "#9E9E9E"),
               ("1× P/m (centre)", pm_c, "#E1251B"),
               ("10× P/m", pm_c * 10.0, "#7A1008")]
    fig = go.Figure()
    for label, pm, color in targets:
        rpm = [_n_for_pm(pm, v / 1000.0, Np, D) * 60.0 for v in vols]
        fig.add_trace(go.Scatter(x=vols, y=rpm, mode="lines", name=label,
                                 line=dict(color=color, width=2)))
    # Centre-point marker at the working volume
    rpm_ctr = _n_for_pm(pm_c, state.bp_v_l / 1000.0, Np, D) * 60.0
    fig.add_trace(go.Scatter(
        x=[state.bp_v_l], y=[rpm_ctr], mode="markers",
        name=f"Centre ({state.bp_v_l:g} L)",
        marker=dict(color="black", size=12, symbol="circle")))
    # Fed-batch adjustment set-points, if enabled
    if state.bp_t1_adj_mode == "On":
        adj = [_sf(r.get("Volume (L)")) for _, r in state.bp_t1_adj_vols_df.iterrows()
               if _sf(r.get("Volume (L)")) > 0]
        if adj:
            for i, (label, pm, color) in enumerate(targets):
                yv = [_n_for_pm(pm, v / 1000.0, Np, D) * 60.0 for v in adj]
                fig.add_trace(go.Scatter(
                    x=adj, y=yv, mode="markers",
                    name="Fed-batch set-points" if i == 0 else None,
                    showlegend=(i == 0),
                    marker=dict(color=color, size=11, symbol="diamond",
                                line=dict(color="black", width=1)),
                    hovertemplate="%{x:.3g} L → %{y:.1f} RPM<extra></extra>"))
    # Reactor RPM bounds
    if state.bp_n_min > 0:
        fig.add_hline(y=state.bp_n_min, line_dash="dash", line_color="gray",
                      annotation_text=f"Min RPM ({state.bp_n_min:.0f})",
                      annotation_position="top left")
    if state.bp_n_max > 0:
        fig.add_hline(y=state.bp_n_max, line_dash="dash", line_color="gray",
                      annotation_text=f"Max RPM ({state.bp_n_max:.0f})",
                      annotation_position="bottom left")
    fig.update_layout(
        xaxis_title="Fill volume (L)", yaxis_title="Impeller speed (RPM)",
        # Dark legend text: the box stays white-ish even in Taipy dark mode.
        legend=dict(x=0.01, y=0.99, bgcolor="rgba(255,255,255,0.75)",
                    font=dict(color="#2A2E33")),
        margin=dict(l=10, r=10, t=30, b=10))
    state.bp_t1_plot = fig


def _build_t1_adj(state):
    """Compute the fed-batch discrete-speed setpoints that hold P/m constant."""
    D, Np = state.bp_d_imp, state.bp_np
    pm_c = state.bp_t1_pm_eff
    n_min, n_max = state.bp_n_min, state.bp_n_max
    targets = [("Low (RPM)", pm_c * 0.1), ("Centre (RPM)", pm_c), ("High (RPM)", pm_c * 10.0)]
    steps = [("Initial", state.bp_v_l)]
    for i, (_, r) in enumerate(state.bp_t1_adj_vols_df.iterrows()):
        v = _sf(r.get("Volume (L)"))
        if v > 0:
            steps.append((f"Adj. {i + 1}", v))
    rows, clamped = [], False
    for label, vol in steps:
        v_m3 = vol / 1000.0
        row = {"Step": label, "Volume (L)": f"{vol:.3g}"}
        for col, pm in targets:
            n_rpm = _n_for_pm(pm, v_m3, Np, D) * 60.0
            flag = ""
            if n_max > 0 and n_rpm > n_max:
                n_rpm, flag, clamped = n_max, " ⚠", True
            elif n_min > 0 and 0 < n_rpm < n_min:
                n_rpm, flag, clamped = n_min, " ⚠", True
            row[col] = f"{n_rpm:.1f}{flag}"
        rows.append(row)
    state.bp_t1_adj_result_df = pd.DataFrame(rows)
    cap = ("Speeds hold each condition's P/m constant as the working volume grows — "
           "set as discrete setpoints when the volume reaches each milestone.")
    if clamped:
        cap += (" ⚠ Some values were clamped to the reactor RPM range; the target "
                "P/m cannot be held at those steps.")
    state.bp_t1_adj_caption = cap



def on_bp_start(state):
    state.bp_started = True
    _build_t1(state)
    state.bp_status = "Protocol started. Run Test 1 conditions and enter the responses."
    notify(state, "S", "Protocol started.")


def on_bp_t1_recalc(state):
    _build_t1(state)


# --- Fed-batch discrete speed adjustments ---------------------------------
def _refresh_t1_adj(state):
    _build_t1_adj(state)
    _build_t1_plot(state)


def on_bp_t1_adj_toggle(state):
    if state.bp_t1_adj_mode == "On" and state.bp_t1_adj_vols_df.empty:
        state.bp_t1_adj_vols_df = pd.DataFrame([{"Volume (L)": round(state.bp_v_l * 2.0, 3)}])
    if state.bp_t1_adj_mode == "On":
        _build_t1_adj(state)
    _build_t1_plot(state)


def on_bp_t1_adj_edit(state, var_name, payload):
    state.bp_t1_adj_vols_df = db.apply_edit(state.bp_t1_adj_vols_df.copy(), payload)
    _refresh_t1_adj(state)


def on_bp_t1_adj_add(state, var_name, payload):
    df = state.bp_t1_adj_vols_df.copy()
    vols = [_sf(v) for v in df["Volume (L)"].tolist()] if not df.empty else []
    base = max(vols) if any(v > 0 for v in vols) else state.bp_v_l
    new_vol = round(base + state.bp_v_l, 3)
    df = db.reset(pd.concat([df, pd.DataFrame([{"Volume (L)": new_vol}])], ignore_index=True))
    state.bp_t1_adj_vols_df = df
    _refresh_t1_adj(state)


def on_bp_t1_adj_delete(state, var_name, payload):
    state.bp_t1_adj_vols_df = db.delete_row(state.bp_t1_adj_vols_df.copy(), payload)
    _refresh_t1_adj(state)


# --- KPI table editing -----------------------------------------------------
def on_bp_t1_kpi_edit(state, var_name, payload):
    state.bp_t1_kpi_df = db.apply_edit(state.bp_t1_kpi_df.copy(), payload)


def on_bp_t1_kpi_add(state, var_name, payload):
    state.bp_t1_kpi_df = _append_kpi(state.bp_t1_kpi_df, 1)


def on_bp_t1_kpi_delete(state, var_name, payload):
    state.bp_t1_kpi_df = db.delete_row(state.bp_t1_kpi_df.copy(), payload)


def on_bp_t2_kpi_edit(state, var_name, payload):
    state.bp_t2_kpi_df = db.apply_edit(state.bp_t2_kpi_df.copy(), payload)


def on_bp_t2_kpi_add(state, var_name, payload):
    state.bp_t2_kpi_df = _append_kpi(state.bp_t2_kpi_df, 2)


def on_bp_t2_kpi_delete(state, var_name, payload):
    state.bp_t2_kpi_df = db.delete_row(state.bp_t2_kpi_df.copy(), payload)


def on_bp_t3_kpi_edit(state, var_name, payload):
    state.bp_t3_kpi_df = db.apply_edit(state.bp_t3_kpi_df.copy(), payload)


def on_bp_t3_kpi_add(state, var_name, payload):
    state.bp_t3_kpi_df = _append_kpi(state.bp_t3_kpi_df, 3)


def on_bp_t3_kpi_delete(state, var_name, payload):
    state.bp_t3_kpi_df = db.delete_row(state.bp_t3_kpi_df.copy(), payload)


def _append_kpi(df: pd.DataFrame, test: int) -> pd.DataFrame:
    low, ctr, high = KPI_COLUMNS[test]
    new = {"KPI": "", "Unit": "", low: 0.0, ctr: 0.0, high: 0.0}
    return db.reset(pd.concat([df, pd.DataFrame([new])], ignore_index=True))


def _reset_downstream(state, from_test: int):
    """Invalidate assessments downstream of the test that was (re)assessed."""
    state.bp_pdf_ready = False
    if from_test <= 1:
        state.bp_t2_assessed = False
        state.bp_t2_sensitive = False
        state.bp_t2_result = None
        state.bp_t2_verdict = ""
        state.bp_show_t2 = False
        state.bp_t2_kpi_result_df = _empty_result(2)
    if from_test <= 2:
        state.bp_t3_assessed = False
        state.bp_t3_sensitive = False
        state.bp_t3_result = None
        state.bp_t3_verdict = ""
        state.bp_show_t3 = False
        state.bp_t3_kpi_result_df = _empty_result(3)


def on_bp_t1_assess(state):
    res = _assess_kpis(state.bp_t1_kpi_df, 1)
    if res is None:
        notify(state, "W", "Enter at least one KPI response before assessing.")
        return
    state.bp_t1_kpi_result_df = res["table"]
    state.bp_t1_result = res
    state.bp_t1_assessed = True
    state.bp_t1_sensitive = res["sensitive"]
    _reset_downstream(state, 1)
    prefix = _kpi_prefix(res)
    if res["sensitive"]:
        state.bp_show_t2 = True
        state.bp_t2_kpi_df = _mirror_kpis(state.bp_t1_kpi_df, 2)
        state.bp_t1_verdict = (
            prefix + " Response moved across the 100× P/m range, so **mixing "
            "matters**. Proceed to **Test 2** to distinguish micro- vs meso-mixing.")
    else:
        state.bp_show_t2 = False
        state.bp_t1_verdict = (
            prefix + " The protocol stops here — standard geometric-similarity "
            "scale-up is adequate.")
    _build_summary(state)
    notify(state, "S", "Test 1 assessed.")


# ---------------------------------------------------------------------------
# Test 2
# ---------------------------------------------------------------------------
def _build_t2(state):
    vol = state.bp_t2_feed_vol
    if state.bp_t2_mode == "Feed rate":
        rate_c = max(state.bp_t2_rate, 1e-9)
        t_c = vol / rate_c
    else:
        t_c = max(state.bp_t2_time, 1e-9)
        rate_c = vol / t_c
    rows = []
    for label, tf, note in (
        ("Fast (3× rate)", t_c / 3.0, "Short feed → tests inertial-convective break-up"),
        ("Centre", t_c, "Reference feed rate"),
        ("Slow (1/3× rate)", t_c * 3.0, "Long feed → approaches well-mixed limit"),
    ):
        rows.append({
            "Condition": label,
            "Feed time (min)": f"{tf:.3g}",
            "Flow rate (mL/min)": f"{vol / tf if tf > 0 else 0:.3g}",
            "Note": note,
        })
    state.bp_t2_cond_df = pd.DataFrame(rows)


def on_bp_t2_recalc(state):
    _build_t2(state)


def on_bp_t2_assess(state):
    res = _assess_kpis(state.bp_t2_kpi_df, 2)
    if res is None:
        notify(state, "W", "Enter at least one KPI response before assessing.")
        return
    state.bp_t2_kpi_result_df = res["table"]
    state.bp_t2_result = res
    state.bp_t2_assessed = True
    state.bp_t2_sensitive = res["sensitive"]
    _reset_downstream(state, 2)
    prefix = _kpi_prefix(res)
    if res["sensitive"]:
        state.bp_show_t3 = True
        state.bp_t3_kpi_df = _mirror_kpis(state.bp_t2_kpi_df, 3)
        state.bp_t2_verdict = (
            prefix + " Feed rate matters — **mesomixing** (feed-plume dispersion) "
            "is in play. Proceed to **Test 3** to distinguish meso- vs macro-mixing.")
    else:
        state.bp_show_t3 = False
        state.bp_t2_verdict = (
            prefix + " 🔬 **Micromixing-controlled.** Scale-up rule: **hold the "
            "local energy dissipation ε constant** (match P/V near the feed point).")
    _build_summary(state)
    notify(state, "S", "Test 2 assessed.")


# ---------------------------------------------------------------------------
# Test 3
# ---------------------------------------------------------------------------
def _build_t3(state):
    D, Np, rho, mu = state.bp_d_imp, state.bp_np, state.bp_rho, state.bp_mu
    nu = mu / rho if rho > 0 else 0.0
    V_m3 = state.bp_v_l / 1000.0
    n_rps = _n_for_pm(state.bp_t1_pm_eff, V_m3, Np, D)
    P = impeller_power(Np, rho, n_rps, D)
    eps_avg = (power_per_volume(P, V_m3) / rho) if (V_m3 > 0 and rho > 0) else 0.0
    rows = []
    for loc, ratio in (("Surface", 0.1), ("Sub-surface (mid)", 1.0), ("Impeller zone", 3.0)):
        eps_loc = ratio * eps_avg
        rows.append({
            "Feed location": loc,
            "ε_loc/ε_avg": f"{ratio:.1f}",
            "ε_loc (W/kg)": f"{eps_loc:.4g}",
            "t_E micro (s)": f"{micromixing_time_engulfment(eps_loc, nu):.3g}",
        })
    state.bp_t3_cond_df = pd.DataFrame(rows)


def on_bp_t3_recalc(state):
    _build_t3(state)


def on_bp_t3_assess(state):
    res = _assess_kpis(state.bp_t3_kpi_df, 3)
    if res is None:
        notify(state, "W", "Enter at least one KPI response before assessing.")
        return
    state.bp_t3_kpi_result_df = res["table"]
    state.bp_t3_result = res
    state.bp_t3_assessed = True
    state.bp_t3_sensitive = res["sensitive"]
    state.bp_pdf_ready = False
    prefix = _kpi_prefix(res)
    if res["sensitive"]:
        state.bp_t3_verdict = (
            prefix + " **Mesomixing-controlled.** Scale-up: match P/V, **extend "
            "the feed time** and **add feed points** to keep the feed plume in a "
            "high-dissipation zone.")
    else:
        state.bp_t3_verdict = (
            prefix + " **Macromixing-controlled.** Scale-up: keep **blend/"
            "circulation times short** (bulk homogeneity governs the outcome).")
    _build_summary(state)
    notify(state, "S", "Test 3 assessed.")


# ---------------------------------------------------------------------------
# Summary / decision tree
# ---------------------------------------------------------------------------
def _build_summary(state):
    if not state.bp_t1_assessed:
        state.bp_show_summary = False
        return
    state.bp_show_summary = True
    lines = ["### Decision-tree conclusion", ""]
    if not state.bp_show_t2:
        dominant = "Mixing-insensitive"
        lines += [
            "- **Test 1:** response insensitive to impeller speed.",
            "",
            "**🟢 Dominant regime: mixing is NOT rate-limiting.** Scale up on geometric "
            "similarity; no special mixing constraints.",
        ]
    elif state.bp_t2_assessed and not state.bp_show_t3:
        dominant = "Micromixing"
        lines += [
            "- **Test 1:** sensitive to impeller speed → mixing matters.",
            "- **Test 2:** insensitive to feed rate.",
            "",
            "**🔬 Dominant regime: MICROMIXING.** Scale-up rule: **hold local ε constant** "
            "(match P/V near the feed) — the reaction competes with engulfment-scale mixing.",
        ]
    elif state.bp_t3_assessed and state.bp_t3_sensitive:
        dominant = "Mesomixing"
        lines += [
            "- **Test 1:** sensitive to impeller speed → mixing matters.",
            "- **Test 2:** sensitive to feed rate.",
            "- **Test 3:** sensitive to feed location.",
            "",
            "**Dominant regime: MESOMIXING.** Scale-up rule: **match P/V, extend feed "
            "time, and add feed points** to control feed-plume dispersion.",
        ]
    elif state.bp_t3_assessed:
        dominant = "Macromixing"
        lines += [
            "- **Test 1:** sensitive to impeller speed → mixing matters.",
            "- **Test 2:** sensitive to feed rate.",
            "- **Test 3:** insensitive to feed location.",
            "",
            "**Dominant regime: MACROMIXING.** Scale-up rule: **keep blend/circulation "
            "times short** — bulk homogeneity governs the outcome.",
        ]
    else:
        dominant = "In progress"
        if state.bp_t2_assessed and state.bp_show_t3:
            lines += [
                "- **Test 1:** sensitive to impeller speed → mixing matters.",
                "- **Test 2:** sensitive to feed rate.",
                "",
                "Tests 1 and 2 are both mixing-sensitive — run **Test 3** (feed "
                "location) to distinguish **meso-** from **macro-mixing**.",
            ]
        else:
            lines += [
                "- **Test 1:** sensitive to impeller speed → mixing matters.",
                "",
                "Continue with **Test 2** (feed rate) — and Test 3 if needed.",
            ]
    state.bp_summary = "\n".join(lines)


# ---------------------------------------------------------------------------
# PDF export
# ---------------------------------------------------------------------------
def _kpi_snapshot(res: dict, test: int) -> dict:
    """Convert an ``_assess_kpis`` result into the report_builder response dict."""
    low, ctr, high = KPI_COLUMNS[test]
    kpi_results = [{
        "name": f'{r["name"]} ({r["unit"]})' if r["unit"] else r["name"],
        "qualitative": False,
        "resp": [r["low"], r["ctr"], r["high"]],
        "max_pct": r["max_pct"],
        "sensitive": r["sensitive"],
    } for r in res["results"]]
    return {
        "labels": [low, ctr, high],
        "kpi_results": kpi_results,
        "n_sensitive": res["n_sensitive"],
        "n_total": res["n_total"],
        "status": res["status"],
        "sensitive": res["sensitive"],
    }


def _t1_conditions_snap(state) -> list:
    D, Np, rho = state.bp_d_imp, state.bp_np, state.bp_rho
    V_m3 = state.bp_v_l / 1000.0
    pm_c = state.bp_t1_pm_eff
    out = []
    for label, factor in (("Low (0.1x P/m)", 0.1), ("Centre (1x P/m)", 1.0), ("High (10x P/m)", 10.0)):
        n_rps = _n_for_pm(pm_c * factor, V_m3, Np, D)
        n_rpm = n_rps * 60.0
        if state.bp_n_max > 0 and n_rpm > state.bp_n_max:
            n_rpm, n_rps = state.bp_n_max, state.bp_n_max / 60.0
        if state.bp_n_min > 0 and n_rpm < state.bp_n_min:
            n_rpm, n_rps = state.bp_n_min, state.bp_n_min / 60.0
        P = impeller_power(Np, rho, n_rps, D)
        eps = power_per_volume(P, V_m3) if V_m3 > 0 else 0.0
        out.append({
            "Condition": label,
            "Volume (L)": state.bp_v_l,
            "N (RPM)": n_rpm,
            "P/m (W/kg)": eps / rho if rho > 0 else 0.0,
            "P/V (W/L)": eps / 1000.0,
            "Tip speed (m/s)": tip_speed(n_rps, D),
        })
    return out


def _centerpoint_metrics(state) -> dict:
    D, Np, rho, mu = state.bp_d_imp, state.bp_np, state.bp_rho, state.bp_mu
    T, H = _blend_geometry(state)
    nu = mu / rho if rho > 0 else 0.0
    V_m3 = state.bp_v_l / 1000.0
    n_rps = _n_for_pm(state.bp_t1_pm_eff, V_m3, Np, D)
    P = impeller_power(Np, rho, n_rps, D)
    eps = power_per_volume(P, V_m3) if V_m3 > 0 else 0.0
    eps_kg = eps / rho if rho > 0 else 0.0
    return {
        "N (RPM)": n_rps * 60.0,
        "P/m (W/kg)": eps_kg,
        "Re": reynolds_number(n_rps, D, rho, mu),
        "Tip speed (m/s)": tip_speed(n_rps, D),
        "Blend time (s)": blend_time_turbulent(Np, n_rps, D, T, H),
        "Micromix t_E (s)": micromixing_time_engulfment(eps_kg, nu),
        "Kolmogorov eta (um)": kolmogorov_length(nu, eps_kg) * 1e6,
    }


def _feed_time_centre(state) -> float:
    vol = state.bp_t2_feed_vol
    if state.bp_t2_mode == "Feed rate":
        return vol / max(state.bp_t2_rate, 1e-9)
    return max(state.bp_t2_time, 1e-9)


def _t2_conditions_snap(state) -> dict:
    D, Np = state.bp_d_imp, state.bp_np
    V_m3 = state.bp_v_l / 1000.0
    vol = state.bp_t2_feed_vol
    t_c = _feed_time_centre(state)
    rows = []
    for label, tf in (("Slow (1/3x rate)", t_c * 3.0), ("Centre", t_c), ("Fast (3x rate)", t_c / 3.0)):
        rows.append({"Condition": label, "Feed time (min)": tf,
                     "Flow rate (mL/min)": vol / tf if tf > 0 else 0.0})
    return {
        "N_RPM": _n_for_pm(state.bp_t1_pm_eff, V_m3, Np, D) * 60.0,
        "feed_vol_mL": vol,
        "feed_location": "Held constant (centerpoint)",
        "rows": rows,
    }


def _t3_conditions_snap(state) -> dict:
    D, Np, rho = state.bp_d_imp, state.bp_np, state.bp_rho
    V_m3 = state.bp_v_l / 1000.0
    n_rps = _n_for_pm(state.bp_t1_pm_eff, V_m3, Np, D)
    P = impeller_power(Np, rho, n_rps, D)
    eps_avg = power_per_volume(P, V_m3) if V_m3 > 0 else 0.0  # W/m3
    rows = [
        {"Feed Location": "Surface", "eps_loc/eps_avg": 0.1, "eps_loc (W/m3)": 0.1 * eps_avg},
        {"Feed Location": "Sub-surface (mid-tank)", "eps_loc/eps_avg": 1.0, "eps_loc (W/m3)": 1.0 * eps_avg},
        {"Feed Location": "Impeller zone", "eps_loc/eps_avg": 3.0, "eps_loc (W/m3)": 3.0 * eps_avg},
    ]
    return {"N_RPM": n_rps * 60.0, "feed_time_min": _feed_time_centre(state),
            "eps_avg_W_m3": eps_avg, "rows": rows}


def _dominant_and_conclusions(state):
    """Return (dominant regime, list of (test, verdict, icon) conclusions)."""
    def _verdict(res):
        n, N = res["n_sensitive"], res["n_total"]
        if res["status"] == "sensitive":
            return f"**Sensitive** ({n}/{N} KPIs \u2265 {_SENS_THRESHOLD:.0f}%)"
        if res["status"] == "may_be_sensitive":
            return f"**Possibly sensitive** ({n}/{N} KPIs \u2265 {_SENS_THRESHOLD:.0f}%)"
        return f"**Not sensitive** (0/{N} KPIs)"

    conclusions = []
    if state.bp_t1_result:
        conclusions.append(("Test 1 - Impeller speed", _verdict(state.bp_t1_result), ""))
    if state.bp_t2_result:
        conclusions.append(("Test 2 - Feed rate", _verdict(state.bp_t2_result), ""))
    if state.bp_t3_result:
        conclusions.append(("Test 3 - Feed location", _verdict(state.bp_t3_result), ""))

    if not state.bp_t1_assessed:
        dominant = "Incomplete"
    elif not state.bp_t1_sensitive:
        dominant = "Mixing-insensitive"
    elif state.bp_t2_assessed and not state.bp_t2_sensitive:
        dominant = "Micromixing"
    elif state.bp_t3_assessed and state.bp_t3_sensitive:
        dominant = "Mesomixing"
    elif state.bp_t3_assessed and not state.bp_t3_sensitive:
        dominant = "Macromixing"
    else:
        dominant = "Incomplete"
    return dominant, conclusions


def on_bp_export_pdf(state):
    if not state.bp_t1_assessed or not state.bp_t1_result:
        notify(state, "W", "Assess at least Test 1 before exporting a report.")
        return
    try:
        dominant, conclusions = _dominant_and_conclusions(state)
        snap = {
            "reactor": state.bp_reactor,
            "fluid": state.bp_fluid,
            "V_L": state.bp_v_l,
            "dominant": dominant,
            "conclusions": conclusions,
            "scaleup_notes": [],
            "t1_conditions": _t1_conditions_snap(state),
            "t1_responses": _kpi_snapshot(state.bp_t1_result, 1),
            "centerpoint_metrics": _centerpoint_metrics(state),
        }
        if state.bp_t2_result:
            snap["t2_conditions"] = _t2_conditions_snap(state)
            snap["t2_responses"] = _kpi_snapshot(state.bp_t2_result, 2)
        if state.bp_t3_result:
            snap["t3_conditions"] = _t3_conditions_snap(state)
            snap["t3_responses"] = _kpi_snapshot(state.bp_t3_result, 3)
        state.bp_pdf_bytes = build_bourne_protocol_pdf(snap)
        state.bp_pdf_name = report_filename("Bourne_Protocol", state.bp_reactor)
        state.bp_pdf_ready = True
        notify(state, "S", "PDF report generated \u2014 click Download.")
    except Exception as exc:  # noqa: BLE001 - surface builder errors to the user
        notify(state, "E", f"PDF generation failed: {exc}")


def _sens_test_finding(sensitive: bool, assessed: bool, test: int) -> str:
    """Short per-test finding label for the Sensitivity Protocol CSV export."""
    if not assessed:
        return ""
    if test == 1:
        return "Mixing-sensitive (impeller speed)" if sensitive else "Mixing-insensitive"
    if test == 2:
        return "Sensitive to feed rate (mesomixing)" if sensitive else "Micromixing-controlled"
    return "Sensitive to feed location (mesomixing)" if sensitive else "Macromixing-controlled"


def on_bp_export_sens_csv(state):
    """Export the Bourne outcome as a field/value CSV the Sensitivity page imports."""
    if not state.bp_t1_assessed:
        notify(state, "W", "Assess at least Test 1 before exporting.")
        return
    try:
        dominant, _ = _dominant_and_conclusions(state)
        mechanism = dominant if dominant in ("Micromixing", "Mesomixing", "Macromixing") else ""
        overall = "yes" if state.bp_t1_sensitive else "no"

        def _kpis(res):
            return (res or {}).get("sensitive_names", "") if res else ""

        rows = [
            ("record_type", "bourne_results"),
            ("project_name", ""),
            ("reactor", str(state.bp_reactor)),
            ("fluid", str(state.bp_fluid)),
            ("test1_assessed", "yes" if state.bp_t1_assessed else "no"),
            ("test1_finding", _sens_test_finding(state.bp_t1_sensitive, state.bp_t1_assessed, 1)),
            ("test1_sensitive_kpis", _kpis(state.bp_t1_result)),
            ("test2_assessed", "yes" if state.bp_t2_assessed else "no"),
            ("test2_finding", _sens_test_finding(state.bp_t2_sensitive, state.bp_t2_assessed, 2)),
            ("test2_sensitive_kpis", _kpis(state.bp_t2_result)),
            ("test3_assessed", "yes" if state.bp_t3_assessed else "no"),
            ("test3_finding", _sens_test_finding(state.bp_t3_sensitive, state.bp_t3_assessed, 3)),
            ("test3_sensitive_kpis", _kpis(state.bp_t3_result)),
            ("overall_sensitive", overall),
            ("dominant_mechanism", mechanism),
        ]
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["field", "value"])
        writer.writerows(rows)
        state.bp_sens_csv_bytes = buf.getvalue().encode("utf-8")
        state.bp_sens_csv_name = report_filename(
            "Bourne_for_Sensitivity", state.bp_reactor).replace(".pdf", ".csv")
        state.bp_sens_csv_ready = True
        notify(state, "S", "CSV export ready \u2014 click Download, then import it on the "
               "Reaction Sensitivity Protocol page.")
    except Exception as exc:  # noqa: BLE001 - surface export errors to the user
        notify(state, "E", f"CSV export failed: {exc}")


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------
page = Markdown(
    inject_icons("""
# __ICON:Bourne_Protocol__Bourne Protocol

<|{bp_status}|text|>

A structured mixing-sensitivity screen (Bourne, 2003). Three gated tests reveal
whether mixing matters and, if so, which scale — **micro**, **meso**, or
**macro** — controls the outcome.

<|part|height=18px|>

<|Decision-tree flowsheet|expandable|expanded=False|
<|part|content={bp_decision_tree_html}|height=620px|>
|>

<|part|height=18px|>

<|part|class_name=va-card|
## System Definition
<|layout|columns=3 2|
<|part|
<|{bp_reactor}|selector|lov={reactor_options}|dropdown|label=Vessel|on_change=on_bp_reactor_change|>

<|layout|columns=1 1 1|
<|{bp_fluid}|selector|lov={fluid_options}|dropdown|label=Fluid|on_change=on_bp_fluid_change|>

<|{bp_T}|number|label=Temperature (°C)|on_change=on_bp_sys_change|>

<|{bp_P}|number|label=Pressure (atm)|on_change=on_bp_sys_change|>
|>

<|{bp_v_l}|number|label=Working volume (L)|>

**Reactor limits**
<|{bp_reactor_summary_df}|table|show_all|width=100%|>

<|Start Protocol|button|on_action=on_bp_start|class_name=compute-btn|>
|>

<|part|
<|part|content={bp_viewer_html}|height=360px|>
|>
|>
|>

<|part|render={bp_started}|class_name=va-card|
## Test 1 — Impeller Speed
Vary the specific power **P/m** over a 100× range (0.1× → 10× the centre) at fixed
volume. If the response barely moves, mixing is not rate-limiting.

<|part|height=18px|>

**Centre-point selection**
<|layout|columns=1 1 1|
<|{bp_t1_ctr_mode}|selector|lov={bp_t1_ctr_mode_options}|dropdown|label=Centre-point method|on_change=on_bp_t1_recalc|>

<|{bp_t1_pm_center}|number|label=Centre P/m (W/kg)|on_change=on_bp_t1_recalc|active={bp_t1_ctr_mode == "Custom P/m"}|>

<|{bp_t1_rpm_center}|number|label=Centre RPM|on_change=on_bp_t1_recalc|active={bp_t1_ctr_mode == "Custom RPM"}|>
|>

<|{bp_t1_ctr_info}|text|mode=markdown|>

<|Recalculate conditions|button|on_action=on_bp_t1_recalc|>

<|{bp_t1_hydro_df}|table|width=100%|show_all|>

### Discrete speed adjustments (fed-batch)
Step the impeller speed at volume milestones to hold **P/m constant** as the
working volume grows. Enter one row per milestone volume (L).

<|{bp_t1_adj_mode}|toggle|lov={bp_t1_adj_mode_options}|on_change=on_bp_t1_adj_toggle|class_name=onoff-toggle|>

<|part|render={bp_t1_adj_mode == "On"}|
<|layout|columns=1 2|
<|{bp_t1_adj_vols_df}|table|editable|rebuild|on_edit=on_bp_t1_adj_edit|on_add=on_bp_t1_adj_add|on_delete=on_bp_t1_adj_delete|width=100%|show_all|>

<|{bp_t1_adj_result_df}|table|width=100%|show_all|>
|>

<|{bp_t1_adj_caption}|text|mode=markdown|>
|>

### Impeller speed vs fill volume
<|part|render={bp_t1_show_plot}|
Iso-**P/m** lines show the impeller speed needed to hold each condition's specific
power constant as the fill volume changes. The black dot is the working-volume
centre-point; diamonds mark any fed-batch set-points; dashed lines are the reactor
RPM limits.

<|chart|figure={bp_t1_plot}|height=480px|>
|>
<|part|render={not bp_t1_show_plot}|
*This vessel has a single working volume, so the speed-vs-volume plot is not applicable.*
|>

### Enter measured responses
Track one or more KPIs — add a row per metric. Each is judged sensitive at a
**≥ 5%** change from its centre value; the overall verdict uses a majority vote.

<|part|height=18px|>

<|{bp_t1_kpi_df}|table|editable|rebuild|lov[KPI]={KPI_METRIC_OPTIONS}|lov[Unit]={UNIT_OPTIONS}|on_edit=on_bp_t1_kpi_edit|on_add=on_bp_t1_kpi_add|on_delete=on_bp_t1_kpi_delete|width=100%|show_all|>

<|Assess Test 1|button|on_action=on_bp_t1_assess|class_name=compute-btn|>

<|part|render={bp_t1_assessed}|
<|{bp_t1_kpi_result_df}|table|width=100%|show_all|>
|>

<|{bp_t1_verdict}|text|mode=markdown|>
|>

<|part|render={bp_show_t2}|class_name=va-card|
## Test 2 — Feed Rate / Time
Hold P/m at the centre and vary the **feed rate** over a 9× range. Insensitivity
means the reaction is **micromixing**-controlled; sensitivity points to mesomixing.

<|layout|columns=1 1 1 1|
<|{bp_t2_feed_vol}|number|label=Total feed volume (mL)|>

<|{bp_t2_mode}|toggle|lov={bp_t2_mode_options}|label=Define by|>

<|{bp_t2_rate}|number|label=Feed rate (mL/min)|>

<|{bp_t2_time}|number|label=Feed time (min)|>
|>

<|Recalculate conditions|button|on_action=on_bp_t2_recalc|>

<|{bp_t2_cond_df}|table|width=100%|show_all|>

### Enter measured responses
KPIs carry over from Test 1 — edit the responses (columns: **Slow feed / Centre /
Fast feed**), add or remove rows as needed.

<|{bp_t2_kpi_df}|table|editable|rebuild|lov[KPI]={KPI_METRIC_OPTIONS}|lov[Unit]={UNIT_OPTIONS}|on_edit=on_bp_t2_kpi_edit|on_add=on_bp_t2_kpi_add|on_delete=on_bp_t2_kpi_delete|width=100%|show_all|>

<|Assess Test 2|button|on_action=on_bp_t2_assess|class_name=compute-btn|>

<|part|render={bp_t2_assessed}|
<|{bp_t2_kpi_result_df}|table|width=100%|show_all|>
|>

<|{bp_t2_verdict}|text|mode=markdown|>
|>

<|part|render={bp_show_t3}|class_name=va-card|
## Test 3 — Feed Location
Hold P/m and feed rate; move the feed point between low- and high-dissipation
zones. Insensitivity means **macromixing** controls; sensitivity means mesomixing.

<|Recalculate conditions|button|on_action=on_bp_t3_recalc|>

<|{bp_t3_cond_df}|table|width=100%|show_all|>

### Enter measured responses
KPIs carry over from Test 2 — edit the responses (columns: **Surface / Mid /
Impeller**).

<|{bp_t3_kpi_df}|table|editable|rebuild|lov[KPI]={KPI_METRIC_OPTIONS}|lov[Unit]={UNIT_OPTIONS}|on_edit=on_bp_t3_kpi_edit|on_add=on_bp_t3_kpi_add|on_delete=on_bp_t3_kpi_delete|width=100%|show_all|>

<|Assess Test 3|button|on_action=on_bp_t3_assess|class_name=compute-btn|>

<|part|render={bp_t3_assessed}|
<|{bp_t3_kpi_result_df}|table|width=100%|show_all|>
|>

<|{bp_t3_verdict}|text|mode=markdown|>
|>

<|part|render={bp_show_summary}|class_name=va-card|
## Summary
<|{bp_summary}|text|mode=markdown|>

### Export report
Generate a PDF capturing the system, each completed test's conditions and
responses, and the decision-tree conclusion.

<|Generate PDF report|button|on_action=on_bp_export_pdf|class_name=compute-btn|>

<|part|render={bp_pdf_ready}|
<|Download PDF|file_download|content={bp_pdf_bytes}|name={bp_pdf_name}|label=Download PDF|>
|>

### Export for the Reaction Sensitivity Protocol
Export the outcome as a CSV that can be imported into the **Reaction
Sensitivity Protocol** (Step 0 pre-screen) to feed the experimental result into
the overall sensitivity assessment.

<|Generate Sensitivity CSV|button|on_action=on_bp_export_sens_csv|class_name=compute-btn|>

<|part|render={bp_sens_csv_ready}|
<|Download CSV|file_download|content={bp_sens_csv_bytes}|name={bp_sens_csv_name}|label=Download Sensitivity CSV|>
|>
|>
""")
)
