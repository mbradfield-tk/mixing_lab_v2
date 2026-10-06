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
P/m, or custom RPM), tracking of multiple KPIs with KPI-specific thresholds and
an optional measurement-noise floor (rules in ``utils/bourne_kpi.py``), discrete
impeller-speed setpoints that hold P/m constant as a fed-batch volume grows, a
speed-vs-fill-volume iso-P/m plot, PDF export and a CSV hand-off to the Reaction
Sensitivity Protocol. The decision tree (``_protocol_outcome``) treats mixed KPI
signals and an inadequate (< 100x) P/m span as *inconclusive* rather than as a
negative result.

Not yet ported from the Streamlit page: qualitative KPI capture and confirmatory
experiments.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
from taipy.gui import Markdown, download, notify

from utils.menu_icons import inject_icons
from utils.report_builder import build_bourne_protocol_pdf, report_filename, report_header_label
from utils import bourne_kpi as kpi
from core import catalog
from core import records
from core import bourne_io
from core import bourne_plan as plan
from core import sensitivity_rules as rules
from core.catalog import is_known_solvent
from core.options import CenterMode, FeedBasis, Toggle, is_on
from viz import bourne as viz_bourne
from reports import snapshots
from core.records import (
    VesselGeometry,
    range_midpoint as _avg_range,
    reactor_id as _reactor_id,
    reactor_row as _reactor_row,
    sf as _sf,
)
from pages import _db_common as db
from pages._vessel_media import build_image_html, build_vessel_viewer_html, media_caption

IMAGES_DIR = Path(__file__).resolve().parent.parent / "images" / "general"
bp_decision_tree_html = build_image_html(
    IMAGES_DIR / "bourne_protocol_decision_tree.png", alt="Bourne Protocol decision tree")

VIEWER_H = 360
UNIT_OPERATION_OPTIONS = ["- select -", "Reaction", "Quench", "Crystallization",
                          "Liquid-Liquid Extraction", "Distillation", "Filtration",
                          "Drying", "Other"]
RESPONSE_METRICS = ["Yield", "Purity", "Conversion", "Selectivity",
                    "Impurity level", "Particle size (D50)", "Other"]
# Per-column dropdown options for the editable KPI tables. A trailing ``None``
# keeps the cell "free" (a custom value can still be typed in).
KPI_METRIC_OPTIONS = RESPONSE_METRICS + [None]
UNIT_OPTIONS = ["%", "ppm", "area%", "wt%", "mol%", "µm", "g/L", "AU", None]
_SENS_THRESHOLD = kpi.SENS_THRESHOLD


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _blend_geometry(state) -> tuple[float, float]:
    """Return tank diameter and current liquid height in metres."""
    geo = VesselGeometry.from_row(_reactor_row(state.bp_reactor))
    return geo.D_tank, geo.liquid_height(state.bp_v_l)


def _fluid_props(name: str, T_C: float, P_atm: float = 1.0) -> tuple[float, float]:
    """Return (rho, mu) for a solvent (at T, P) or a custom fluid."""
    p = records.fluid_props(name, T_C, P_atm)
    return p["rho"], p["mu"]


def _fluid_diffusivity(name: str, T_C: float, P_atm: float = 1.0) -> float:
    """Return molecular diffusivity for the selected fluid in m²/s."""
    return records.fluid_props(name, T_C, P_atm)["D_mol"]


# KPI assessment rules live in utils/bourne_kpi.py (shared with the Reaction
# Sensitivity Protocol import); the local names are kept for callers/tests.
_assess_with_threshold = kpi.assess_with_threshold
_kpi_threshold = kpi.kpi_threshold
_kpi_criticality = kpi.kpi_criticality


def _assess(low: float, center: float, high: float) -> tuple[float, bool]:
    """Return (max % change from centre, sensitive?) using the default threshold."""
    return kpi.assess_with_threshold(low, center, high, _SENS_THRESHOLD)


def _system(state) -> plan.BourneSystem:
    """Bourne planning inputs (vessel, fluid, working volume) from the page state."""
    tank_d, h_liq = _blend_geometry(state)
    return plan.BourneSystem(
        D_imp=state.bp_d_imp, Np=state.bp_np, rho=state.bp_rho, mu=state.bp_mu,
        D_mol=_fluid_diffusivity(state.bp_fluid, state.bp_T, state.bp_P), V_L=state.bp_v_l,
        n_min=state.bp_n_min, n_max=state.bp_n_max, D_tank=tank_d, H_liquid=h_liq)


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
KPI_COLUMNS = kpi.KPI_COLUMNS
_new_kpi_df = kpi.new_kpi_df
_mirror_kpis = kpi.mirror_kpis
_empty_result = kpi.empty_result
_assess_kpis = kpi.assess_kpis
_kpi_prefix = kpi.kpi_prefix


def _assess_or_warn(state, df: pd.DataFrame, test: int):
    """Assess a KPI table, warning about incomplete rows; None if nothing usable."""
    res = kpi.assess_kpis(df, test)
    incomplete = kpi.incomplete_rows(df, test)
    if res is None:
        msg = "Enter the low, centre and high responses for at least one KPI before assessing."
        if incomplete:
            msg += " Incomplete: " + "; ".join(incomplete) + "."
        notify(state, "W", msg)
        return None
    if incomplete:
        notify(state, "W", "Skipped incomplete KPI row(s): " + "; ".join(incomplete) + ".")
    return res


def _status_of(state, test: int) -> str:
    """'sensitive' / 'not_sensitive' / 'inconclusive' / '' (not assessed)."""
    res = getattr(state, f"bp_t{test}_result", None)
    if not getattr(state, f"bp_t{test}_assessed", False) or not res:
        return ""
    return str(res.get("status", "") or "")


def _test1_range_ratio(state) -> float:
    """Actual low/high P/m ratio achieved in Test 1 after any RPM clamping."""
    df = getattr(state, "bp_t1_hydro_df", pd.DataFrame())
    if df.empty:
        return 0.0
    return plan.pm_range_ratio([_sf(row.get("P/m (W/kg)")) for _, row in df.iterrows()])


def _resolve_center_pm(state) -> tuple[float, str]:
    """Resolve the Test 1 centre-point P/m (W/kg) and an info caption."""
    return plan.resolve_center_pm(_system(state),
                                  CenterMode.from_label(state.bp_t1_ctr_mode, CenterMode.DEFAULT),
                                  _sf(state.bp_t1_pm_center), _sf(state.bp_t1_rpm_center))


# ---------------------------------------------------------------------------
# Option lists
# ---------------------------------------------------------------------------
reactor_options = catalog.reactor_names()
fluid_options = catalog.fluid_names()

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
bp_tab = "Protocol"
bp_tab_options = ["Protocol", "Plan"]

# ---------------------------------------------------------------------------
# State — Project Information
# ---------------------------------------------------------------------------
bp_project_name = ""
bp_step_text = ""
bp_unit_operation = UNIT_OPERATION_OPTIONS[0]
bp_process_version = ""

# ---------------------------------------------------------------------------
# State — Test 1 (impeller speed)
# ---------------------------------------------------------------------------
bp_t1_ctr_mode = CenterMode.DEFAULT.label
bp_t1_ctr_mode_options = CenterMode.labels()
# Labels referenced by the page's `active=` expressions.
bp_lbl_custom_pm = CenterMode.CUSTOM_PM.label
bp_lbl_custom_rpm = CenterMode.CUSTOM_RPM.label
bp_lbl_feed_rate = FeedBasis.RATE.label
bp_lbl_feed_time = FeedBasis.TIME.label
bp_t1_pm_center = 0.2    # W/kg (Custom P/m mode)
bp_t1_rpm_center = _avg_range(_r0, "N_rpm_min", "N_rpm_max", 300.0)  # RPM (Custom RPM mode)
bp_t1_pm_eff = 0.2       # resolved centre P/m (W/kg), used by Tests 1 & 3
bp_t1_ctr_info = ""
bp_t1_hydro_df = pd.DataFrame(columns=["Condition", "N (RPM)", "P/V (W/L)", "P/m (W/kg)",
                                       "Blend time (s)", "Avg shear rate (1/s)",
                                       "Tip speed (m/s)", "Re", "kLa_surface (1/s)",
                                       "t_E micro (s)", "η (µm)"])
bp_t1_kpi_df = _new_kpi_df(1)
bp_t1_kpi_result_df = _empty_result(1)
bp_t1_result = None
bp_t1_assessed = False
bp_t1_sensitive = False
bp_t1_verdict = ""
bp_show_t2 = False

# Discrete speed adjustments (fed-batch: hold P/m as volume grows)
bp_t1_adj_mode = Toggle.OFF.label
bp_t1_adj_mode_options = Toggle.labels()
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
bp_t2_mode = FeedBasis.RATE.label
bp_t2_mode_options = FeedBasis.labels()
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
bp_t3_surface_ratio = 0.1
bp_t3_mid_ratio = 1.0
bp_t3_impeller_ratio = 3.0

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

# Table CSV downloads (separate from the structured Sensitivity handoff CSV).
bp_t1_conditions_csv = b""
bp_t1_adjustments_csv = b""
bp_t1_results_csv = b""
bp_t2_conditions_csv = b""
bp_t2_results_csv = b""
bp_t3_conditions_csv = b""
bp_t3_results_csv = b""


def _refresh_table_csv_exports(state):
    """Refresh downloadable CSV content for the current protocol tables."""
    empty = pd.DataFrame()
    state.bp_t1_conditions_csv = db.csv_bytes(getattr(state, "bp_t1_hydro_df", empty))
    state.bp_t1_adjustments_csv = db.csv_bytes(getattr(state, "bp_t1_adj_result_df", empty))
    state.bp_t1_results_csv = db.csv_bytes(getattr(state, "bp_t1_kpi_result_df", empty))
    state.bp_t2_conditions_csv = db.csv_bytes(getattr(state, "bp_t2_cond_df", empty))
    state.bp_t2_results_csv = db.csv_bytes(getattr(state, "bp_t2_kpi_result_df", empty))
    state.bp_t3_conditions_csv = db.csv_bytes(getattr(state, "bp_t3_cond_df", empty))
    state.bp_t3_results_csv = db.csv_bytes(getattr(state, "bp_t3_kpi_result_df", empty))


def _invalidate_assessments(state):
    """Clear all prior protocol verdicts when the inputs change."""
    state.bp_t1_assessed = False
    state.bp_t1_sensitive = False
    state.bp_t1_result = None
    state.bp_t1_verdict = ""
    state.bp_t1_kpi_result_df = _empty_result(1)
    state.bp_show_t2 = False

    state.bp_t2_assessed = False
    state.bp_t2_sensitive = False
    state.bp_t2_result = None
    state.bp_t2_verdict = ""
    state.bp_t2_kpi_result_df = _empty_result(2)
    state.bp_show_t3 = False

    state.bp_t3_assessed = False
    state.bp_t3_sensitive = False
    state.bp_t3_result = None
    state.bp_t3_verdict = ""
    state.bp_t3_kpi_result_df = _empty_result(3)

    state.bp_pdf_ready = False
    state.bp_sens_csv_ready = False
    state.bp_show_summary = False
    state.bp_summary = ""

    if getattr(state, "bp_started", True):
        state.bp_status = (
            "System or response inputs changed — previous Bourne assessments are invalid. "
            "Reassessment required: please redo the protocol from Test 1."
        )
    else:
        state.bp_status = "Define the system, then click Start Protocol."


def _invalidate_current_test(state, test: int):
    """Clear only the edited test and its downstream state.

    This is for inline KPI-table edits; it should not recreate the initial
    "Start Protocol" state or hide Test 1 after it has already been assessed.
    """
    state.bp_pdf_ready = False
    state.bp_sens_csv_ready = False
    if test == 1:
        state.bp_t1_assessed = False
        state.bp_t1_sensitive = False
        state.bp_t1_result = None
        state.bp_t1_verdict = ""
        state.bp_t1_kpi_result_df = _empty_result(1)
        state.bp_show_t2 = False
        _reset_downstream(state, 1)
    elif test == 2:
        state.bp_t2_assessed = False
        state.bp_t2_sensitive = False
        state.bp_t2_result = None
        state.bp_t2_verdict = ""
        state.bp_t2_kpi_result_df = _empty_result(2)
        state.bp_show_t3 = False
        _reset_downstream(state, 2)
    else:
        state.bp_t3_assessed = False
        state.bp_t3_sensitive = False
        state.bp_t3_result = None
        state.bp_t3_verdict = ""
        state.bp_t3_kpi_result_df = _empty_result(3)
    _build_summary(state)


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
    _invalidate_assessments(state)
    _build_t1(state)
    _build_t2(state)
    _build_t3(state)


def _load_fluid(state):
    state.bp_rho, state.bp_mu = _fluid_props(state.bp_fluid, state.bp_T, state.bp_P)
    _invalidate_assessments(state)


def on_bp_fluid_change(state):
    _load_fluid(state)


def on_bp_sys_change(state):
    if is_known_solvent(state.bp_fluid):
        _load_fluid(state)


def _build_plan(state):
    _build_t1(state)
    _build_t2(state)
    _build_t3(state)


def on_bp_tab_change(state):
    if state.bp_tab == "Plan":
        _build_plan(state)


def on_bp_plan_recalc(state):
    _invalidate_assessments(state)
    _build_plan(state)


def on_bp_plan_fluid_change(state):
    _load_fluid(state)
    _build_plan(state)


def on_bp_plan_sys_change(state):
    if is_known_solvent(state.bp_fluid):
        _load_fluid(state)
    _build_plan(state)


# ---------------------------------------------------------------------------
# Test 1
# ---------------------------------------------------------------------------
def _t1_condition_rows(state) -> list[dict]:
    """Raw (unformatted) Test 1 conditions after RPM clamping — the single source
    for the on-page table, the P/m range check and the PDF snapshot."""
    return plan.test1_conditions(_system(state), state.bp_t1_pm_eff)


def _build_t1(state):
    pm_c, info = _resolve_center_pm(state)
    state.bp_t1_pm_eff = pm_c
    state.bp_t1_ctr_info = info
    rows = []
    for r in _t1_condition_rows(state):
        rows.append({
            "Condition": r["Condition"] + r["note"],
            "N (RPM)": f"{r['N (RPM)']:,.1f}",
            "P/V (W/L)": f"{r['P/V (W/L)']:.4g}",
            "P/m (W/kg)": f"{r['P/m (W/kg)']:.4g}",
            "Blend time (s)": f"{r['Blend time (s)']:.3g}",
            "Avg shear rate (1/s)": f"{r['Avg shear rate (1/s)']:.3g}",
            "Tip speed (m/s)": f"{r['Tip speed (m/s)']:.3g}",
            "Re": f"{r['Re']:,.0f}",
            "kLa_surface (1/s)": f"{r['kLa_surface (1/s)']:.3g}",
            "t_E micro (s)": f"{r['t_E micro (s)']:.3g}",
            "η (µm)": f"{r['η (µm)']:.3g}",
        })
    state.bp_t1_hydro_df = pd.DataFrame(rows)
    if is_on(state.bp_t1_adj_mode):
        _build_t1_adj(state)
    _build_t1_plot(state)
    _refresh_table_csv_exports(state)


def _build_t1_plot(state):
    """Impeller-speed vs fill-volume iso-P/m plot (0.1× / 1× / 10× centre)."""
    adj = ([_sf(r.get("Volume (L)")) for _, r in state.bp_t1_adj_vols_df.iterrows()]
           if is_on(state.bp_t1_adj_mode) else [])
    data = plan.t1_speed_plan(_system(state), state.bp_t1_pm_eff, state.bp_v_min,
                              state.bp_v_max, adj)
    state.bp_t1_show_plot = data is not None
    state.bp_t1_plot = viz_bourne.t1_speed_plan(data) if data else go.Figure()


def _build_t1_adj(state):
    """Compute the fed-batch discrete-speed setpoints that hold P/m constant."""
    steps = [("Initial", state.bp_v_l)]
    for i, (_, r) in enumerate(state.bp_t1_adj_vols_df.iterrows()):
        v = _sf(r.get("Volume (L)"))
        if v > 0:
            steps.append((f"Adj. {i + 1}", v))
    setpoints, clamped = plan.speed_setpoints(_system(state), state.bp_t1_pm_eff, steps)
    rows = []
    for sp in setpoints:
        row = {"Step": sp["Step"], "Volume (L)": f"{sp['Volume (L)']:.3g}"}
        for col in ("Low (RPM)", "Centre (RPM)", "High (RPM)"):
            n_rpm, was_clamped = sp[col]
            row[col] = f"{n_rpm:.1f}{' ⚠' if was_clamped else ''}"
        rows.append(row)
    state.bp_t1_adj_result_df = pd.DataFrame(rows)
    cap = ("Speeds hold each condition's P/m constant as the working volume grows — "
           "set as discrete setpoints when the volume reaches each milestone.")
    if clamped:
        cap += (" ⚠ Some values were clamped to the reactor RPM range; the target "
                "P/m cannot be held at those steps.")
    state.bp_t1_adj_caption = cap
    _refresh_table_csv_exports(state)



def on_bp_start(state):
    state.bp_started = True
    _build_t1(state)
    state.bp_status = "Protocol started. Run Test 1 conditions and enter the responses."
    notify(state, "S", "Protocol started.")


def on_bp_t1_recalc(state):
    _invalidate_assessments(state)
    _build_t1(state)


def on_bp_volume_change(state):
    """Working volume feeds every test's conditions — invalidate and rebuild all."""
    _invalidate_assessments(state)
    _build_plan(state)


def on_bp_t2_input_change(state):
    """Feed-volume/rate/time edits change the Test 2 conditions only."""
    _invalidate_current_test(state, 2)
    _build_t2(state)


# --- Fed-batch discrete speed adjustments ---------------------------------
def _refresh_t1_adj(state):
    _build_t1_adj(state)
    _build_t1_plot(state)


def on_bp_t1_adj_toggle(state):
    if is_on(state.bp_t1_adj_mode) and state.bp_t1_adj_vols_df.empty:
        state.bp_t1_adj_vols_df = pd.DataFrame([{"Volume (L)": round(state.bp_v_l * 2.0, 3)}])
    if is_on(state.bp_t1_adj_mode):
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
    _invalidate_current_test(state, 1)


def on_bp_t1_kpi_add(state, var_name, payload):
    state.bp_t1_kpi_df = _append_kpi(state.bp_t1_kpi_df, 1)
    _invalidate_current_test(state, 1)


def on_bp_t1_kpi_delete(state, var_name, payload):
    state.bp_t1_kpi_df = db.delete_row(state.bp_t1_kpi_df.copy(), payload)
    _invalidate_current_test(state, 1)


def on_bp_t2_kpi_edit(state, var_name, payload):
    state.bp_t2_kpi_df = db.apply_edit(state.bp_t2_kpi_df.copy(), payload)
    _invalidate_current_test(state, 2)


def on_bp_t2_kpi_add(state, var_name, payload):
    state.bp_t2_kpi_df = _append_kpi(state.bp_t2_kpi_df, 2)
    _invalidate_current_test(state, 2)


def on_bp_t2_kpi_delete(state, var_name, payload):
    state.bp_t2_kpi_df = db.delete_row(state.bp_t2_kpi_df.copy(), payload)
    _invalidate_current_test(state, 2)


def on_bp_t3_kpi_edit(state, var_name, payload):
    state.bp_t3_kpi_df = db.apply_edit(state.bp_t3_kpi_df.copy(), payload)
    _invalidate_current_test(state, 3)


def on_bp_t3_kpi_add(state, var_name, payload):
    state.bp_t3_kpi_df = _append_kpi(state.bp_t3_kpi_df, 3)
    _invalidate_current_test(state, 3)


def on_bp_t3_kpi_delete(state, var_name, payload):
    state.bp_t3_kpi_df = db.delete_row(state.bp_t3_kpi_df.copy(), payload)
    _invalidate_current_test(state, 3)


def _append_kpi(df: pd.DataFrame, test: int) -> pd.DataFrame:
    return db.reset(pd.concat([df, pd.DataFrame([kpi.blank_kpi_row(test)])], ignore_index=True))


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
    res = _assess_or_warn(state, state.bp_t1_kpi_df, 1)
    if res is None:
        return
    state.bp_t1_kpi_result_df = res["table"]
    state.bp_t1_result = res
    state.bp_t1_assessed = True
    state.bp_t1_sensitive = res["sensitive"]
    _refresh_table_csv_exports(state)
    _reset_downstream(state, 1)
    state.bp_t1_verdict, state.bp_show_t2 = rules.bourne_test_verdict(
        1, res, _test1_range_ratio(state))
    if state.bp_show_t2:
        state.bp_t2_kpi_df = _mirror_kpis(state.bp_t1_kpi_df, 2,
                                          getattr(state, "bp_t2_kpi_df", None))
    _build_summary(state)
    notify(state, "S", "Test 1 assessed.")


# ---------------------------------------------------------------------------
# Test 2
# ---------------------------------------------------------------------------
def _build_t2(state):
    rows = plan.test2_conditions(_sf(state.bp_t2_feed_vol),
                                 FeedBasis.from_label(state.bp_t2_mode) is FeedBasis.RATE,
                                 _sf(state.bp_t2_rate), _sf(state.bp_t2_time))
    state.bp_t2_cond_df = pd.DataFrame([
        {"Condition": r["Condition"], "Feed time (min)": f"{r['Feed time (min)']:.3g}",
         "Flow rate (mL/min)": f"{r['Flow rate (mL/min)']:.3g}", "Note": r["Note"]}
        for r in rows])
    _refresh_table_csv_exports(state)


def on_bp_t2_recalc(state):
    _invalidate_assessments(state)
    _build_t2(state)


def on_bp_t2_assess(state):
    res = _assess_or_warn(state, state.bp_t2_kpi_df, 2)
    if res is None:
        return
    state.bp_t2_kpi_result_df = res["table"]
    state.bp_t2_result = res
    state.bp_t2_assessed = True
    state.bp_t2_sensitive = res["sensitive"]
    _refresh_table_csv_exports(state)
    _reset_downstream(state, 2)
    state.bp_t2_verdict, state.bp_show_t3 = rules.bourne_test_verdict(2, res)
    if state.bp_show_t3:
        state.bp_t3_kpi_df = _mirror_kpis(state.bp_t2_kpi_df, 3,
                                          getattr(state, "bp_t3_kpi_df", None))
    _build_summary(state)
    notify(state, "S", "Test 2 assessed.")


# ---------------------------------------------------------------------------
# Test 3
# ---------------------------------------------------------------------------
def _build_t3(state):
    ratios = [
        ("Surface", _sf(state.bp_t3_surface_ratio, 0.1)),
        ("Sub-surface (mid)", _sf(state.bp_t3_mid_ratio, 1.0)),
        ("Impeller zone", _sf(state.bp_t3_impeller_ratio, 3.0)),
    ]
    rows = plan.test3_conditions(_system(state), state.bp_t1_pm_eff, ratios)
    state.bp_t3_cond_df = pd.DataFrame([
        {"Feed location": r["Feed location"], "ε_loc/ε_avg": f"{r['ε_loc/ε_avg']:.1f}",
         "ε_loc (W/kg)": f"{r['ε_loc (W/kg)']:.4g}",
         "t_E micro (s)": f"{r['t_E micro (s)']:.3g}"}
        for r in rows])
    _refresh_table_csv_exports(state)


def on_bp_t3_recalc(state):
    _invalidate_current_test(state, 3)
    _build_t3(state)


def on_bp_t3_assess(state):
    res = _assess_or_warn(state, state.bp_t3_kpi_df, 3)
    if res is None:
        return
    state.bp_t3_kpi_result_df = res["table"]
    state.bp_t3_result = res
    state.bp_t3_assessed = True
    state.bp_t3_sensitive = res["sensitive"]
    _refresh_table_csv_exports(state)
    state.bp_pdf_ready = False
    state.bp_t3_verdict, _ = rules.bourne_test_verdict(3, res)
    _build_summary(state)
    notify(state, "S", "Test 3 assessed.")


# ---------------------------------------------------------------------------
# Summary / decision tree
# ---------------------------------------------------------------------------
def _protocol_outcome(state) -> dict:
    """Single source of truth for the decision tree, used by the on-page
    summary, the PDF and the Sensitivity-Protocol CSV (rules in core)."""
    s1, s2, s3 = (_status_of(state, n) for n in (1, 2, 3))
    return rules.bourne_outcome(s1, s2, s3, _test1_range_ratio(state))


_test_lines = rules.bourne_test_lines
_MECH_CONCLUSION = rules.MECH_CONCLUSION


def _build_summary(state):
    if not getattr(state, "bp_t1_assessed", False):
        state.bp_show_summary = False
        return
    state.bp_show_summary = True
    state.bp_summary = rules.bourne_summary_md(_protocol_outcome(state))


# ---------------------------------------------------------------------------
# PDF export
# ---------------------------------------------------------------------------
def _centerpoint_metrics(state) -> dict:
    return plan.centerpoint_metrics(_system(state), state.bp_t1_pm_eff)


def _feed_time_centre(state) -> float:
    vol = state.bp_t2_feed_vol
    if FeedBasis.from_label(state.bp_t2_mode) is FeedBasis.RATE:
        return vol / max(state.bp_t2_rate, 1e-9)
    return max(state.bp_t2_time, 1e-9)


def _t2_conditions_snap(state) -> dict:
    return plan.t2_report_conditions(_report_system(state), state.bp_t1_pm_eff,
                                     state.bp_t2_feed_vol, _feed_time_centre(state))


def _t3_conditions_snap(state) -> dict:
    ratios = plan.t3_location_ratios(_sf(state.bp_t3_surface_ratio, 0.1),
                                     _sf(state.bp_t3_mid_ratio, 1.0),
                                     _sf(state.bp_t3_impeller_ratio, 3.0))
    return plan.t3_report_conditions(_report_system(state), state.bp_t1_pm_eff, ratios,
                                     _feed_time_centre(state))


def _report_system(state) -> plan.BourneSystem:
    """Power-draw inputs only (no fluid lookup) for the report conditions."""
    return plan.BourneSystem(D_imp=state.bp_d_imp, Np=state.bp_np, rho=state.bp_rho,
                             mu=0.0, D_mol=0.0, V_L=state.bp_v_l)


def _dominant_and_conclusions(state):
    """Return (dominant regime, list of (test, verdict, icon) conclusions)."""
    o = _protocol_outcome(state)
    return o["dominant"], rules.bourne_conclusions(
        o, {1: state.bp_t1_result, 2: state.bp_t2_result, 3: state.bp_t3_result})


def on_bp_export_pdf(state):
    if not state.bp_t1_assessed or not state.bp_t1_result:
        notify(state, "W", "Assess at least Test 1 before exporting a report.")
        return
    try:
        dominant, conclusions = _dominant_and_conclusions(state)
        unit_op = state.bp_unit_operation if state.bp_unit_operation != UNIT_OPERATION_OPTIONS[0] else ""
        snap = snapshots.bourne_snapshot(
            reactor=state.bp_reactor, fluid=state.bp_fluid, V_L=state.bp_v_l,
            dominant=dominant, conclusions=conclusions,
            t1_rows=_t1_condition_rows(state), t1_result=state.bp_t1_result,
            centerpoint=_centerpoint_metrics(state),
            t2=(_t2_conditions_snap(state), state.bp_t2_result) if state.bp_t2_result else None,
            t3=(_t3_conditions_snap(state), state.bp_t3_result) if state.bp_t3_result else None,
            project=snapshots.project_meta(state.bp_project_name, state.bp_step_text, unit_op,
                                           state.bp_process_version))
        state.bp_pdf_bytes = build_bourne_protocol_pdf(snap)
        state.bp_pdf_name = report_filename("Bourne", report_header_label(snap) or state.bp_reactor)
        state.bp_pdf_ready = True
        notify(state, "S", "PDF report generated \u2014 click Download.")
    except Exception as exc:  # noqa: BLE001 - surface builder errors to the user
        notify(state, "E", f"PDF generation failed: {exc}")


def on_bp_pdf_download(state):
    # file_download's `name` property is static, so the filename must be set
    # via the imperative download() call rather than the control's binding.
    if not state.bp_pdf_ready:
        return
    download(state, content=state.bp_pdf_bytes, name=state.bp_pdf_name)


_SENS_FINDING = bourne_io.TEST_FINDINGS
_sens_test_finding = bourne_io.test_finding


def on_bp_export_sens_csv(state):
    """Export the Bourne outcome as a field/value CSV the Sensitivity page imports."""
    if not state.bp_t1_assessed:
        notify(state, "W", "Assess at least Test 1 before exporting.")
        return
    try:
        unit_op = state.bp_unit_operation if state.bp_unit_operation != UNIT_OPERATION_OPTIONS[0] else ""
        meta = {
            "project_name": state.bp_project_name,
            "step_number": state.bp_step_text,
            "unit_operation": unit_op,
            "process_version": state.bp_process_version,
        }
        kpis = {n: ((getattr(state, f"bp_t{n}_result", None) or {}).get("sensitive_names", ""))
                for n in (1, 2, 3)}
        rows = bourne_io.export_rows(
            _protocol_outcome(state),
            {**meta, "reactor": state.bp_reactor, "fluid": state.bp_fluid,
             "working_volume_L": _sf(state.bp_v_l)},
            kpis)
        state.bp_sens_csv_bytes = bourne_io.write_csv(rows)
        state.bp_sens_csv_name = report_filename(
            report_header_label(meta) or state.bp_reactor).replace(".pdf", ".csv")
        state.bp_sens_csv_ready = True
        notify(state, "S", "CSV export ready \u2014 click Download, then import it on the "
               "Reaction Sensitivity Protocol page.")
    except Exception as exc:  # noqa: BLE001 - surface export errors to the user
        notify(state, "E", f"CSV export failed: {exc}")


def on_bp_sens_csv_download(state):
    # file_download's `name` property is static, so the filename must be set
    # via the imperative download() call rather than the control's binding.
    if not state.bp_sens_csv_ready:
        return
    download(state, content=state.bp_sens_csv_bytes, name=state.bp_sens_csv_name)


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------
page = Markdown(
    inject_icons("""
# __ICON:Bourne_Protocol__Bourne Protocol

<|{bp_tab}|toggle|lov={bp_tab_options}|on_change=on_bp_tab_change|>

<|part|render={bp_tab == "Protocol"}|
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
## Project Information
<|layout|columns=1 1 1 1|class_name=form-grid|
<|{bp_project_name}|input|label=Project name|>

<|{bp_step_text}|input|label=Step|>

<|{bp_unit_operation}|selector|lov={UNIT_OPERATION_OPTIONS}|dropdown|label=Unit operation|>

<|{bp_process_version}|input|label=Process version|>
|>
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

<|{bp_v_l}|number|label=Working volume (L)|on_change=on_bp_volume_change|>

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

<|{bp_t1_pm_center}|number|label=Centre P/m (W/kg)|on_change=on_bp_t1_recalc|active={bp_t1_ctr_mode == bp_lbl_custom_pm}|>

<|{bp_t1_rpm_center}|number|label=Centre RPM|on_change=on_bp_t1_recalc|active={bp_t1_ctr_mode == bp_lbl_custom_rpm}|>
|>

<|{bp_t1_ctr_info}|text|mode=markdown|>

<|Recalculate conditions|button|on_action=on_bp_t1_recalc|>

<|{bp_t1_hydro_df}|table|width=100%|show_all|>

<|Download Test 1 conditions CSV|file_download|content={bp_t1_conditions_csv}|name=bourne_test_1_conditions.csv|label=Download Test 1 conditions CSV|>

### Discrete speed adjustments (fed-batch)
Step the impeller speed at volume milestones to hold **P/m constant** as the
working volume grows. Enter one row per milestone volume (L).

<|{bp_t1_adj_mode}|toggle|lov={bp_t1_adj_mode_options}|on_change=on_bp_t1_adj_toggle|class_name=onoff-toggle|>

<|part|render={bp_t1_adj_mode == "On"}|
<|layout|columns=1 2|
<|{bp_t1_adj_vols_df}|table|editable|rebuild|on_edit=on_bp_t1_adj_edit|on_add=on_bp_t1_adj_add|on_delete=on_bp_t1_adj_delete|width=100%|show_all|>

<|{bp_t1_adj_result_df}|table|width=100%|show_all|>

<|Download speed adjustments CSV|file_download|content={bp_t1_adjustments_csv}|name=bourne_test_1_speed_adjustments.csv|label=Download speed adjustments CSV|>
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
Track one or more KPIs — add a row per metric. A KPI counts as sensitive when it
changes by more than its threshold from the centre value (**5%** for yield /
conversion / purity / selectivity, **10%** for impurity levels and particle size)
and the change exceeds twice the measurement noise (optional **Std dev** and
**Replicates** columns). The overall verdict is *sensitive* if any critical KPI
(impurity, selectivity) or every KPI is sensitive, *not sensitive* if none is, and
*inconclusive* for a mixed signal.

<|part|height=18px|>

<|{bp_t1_kpi_df}|table|editable|rebuild|lov[KPI]={KPI_METRIC_OPTIONS}|lov[Unit]={UNIT_OPTIONS}|on_edit=on_bp_t1_kpi_edit|on_add=on_bp_t1_kpi_add|on_delete=on_bp_t1_kpi_delete|width=100%|show_all|class_name=bp-kpi-table|>

<|Assess Test 1|button|on_action=on_bp_t1_assess|class_name=compute-btn|>

<|part|render={bp_t1_assessed}|
<|{bp_t1_kpi_result_df}|table|width=100%|show_all|>

<|Download Test 1 KPI results CSV|file_download|content={bp_t1_results_csv}|name=bourne_test_1_kpi_results.csv|label=Download Test 1 KPI results CSV|>
|>

<|{bp_t1_verdict}|text|mode=markdown|>
|>

<|part|render={bp_show_t2}|class_name=va-card|
## Test 2 — Feed Rate / Time
Hold P/m at the centre and vary the **feed rate** over a 9× range. Insensitivity
means the reaction is **micromixing**-controlled; sensitivity points to mesomixing.

<|layout|columns=1 1 1 1|
<|{bp_t2_feed_vol}|number|label=Total feed volume (mL)|on_change=on_bp_t2_input_change|>

<|{bp_t2_mode}|toggle|lov={bp_t2_mode_options}|label=Define by|on_change=on_bp_t2_input_change|>

<|{bp_t2_rate}|number|label=Feed rate (mL/min)|active={bp_t2_mode == bp_lbl_feed_rate}|on_change=on_bp_t2_input_change|>

<|{bp_t2_time}|number|label=Feed time (min)|active={bp_t2_mode == bp_lbl_feed_time}|on_change=on_bp_t2_input_change|>
|>

<|Recalculate conditions|button|on_action=on_bp_t2_recalc|>

<|{bp_t2_cond_df}|table|width=100%|show_all|>

<|Download Test 2 conditions CSV|file_download|content={bp_t2_conditions_csv}|name=bourne_test_2_conditions.csv|label=Download Test 2 conditions CSV|>

### Enter measured responses
KPIs carry over from Test 1 — edit the responses (columns: **Slow feed / Centre /
Fast feed**), add or remove rows as needed.

<|{bp_t2_kpi_df}|table|editable|rebuild|lov[KPI]={KPI_METRIC_OPTIONS}|lov[Unit]={UNIT_OPTIONS}|on_edit=on_bp_t2_kpi_edit|on_add=on_bp_t2_kpi_add|on_delete=on_bp_t2_kpi_delete|width=100%|show_all|class_name=bp-kpi-table|>

<|Assess Test 2|button|on_action=on_bp_t2_assess|class_name=compute-btn|>

<|part|render={bp_t2_assessed}|
<|{bp_t2_kpi_result_df}|table|width=100%|show_all|>

<|Download Test 2 KPI results CSV|file_download|content={bp_t2_results_csv}|name=bourne_test_2_kpi_results.csv|label=Download Test 2 KPI results CSV|>
|>

<|{bp_t2_verdict}|text|mode=markdown|>
|>

<|part|render={bp_show_t3}|class_name=va-card|
## Test 3 — Feed Location
Hold P/m and feed rate; move the feed point between low- and high-dissipation
zones. Insensitivity means **macromixing** controls; sensitivity means mesomixing.

The local dissipation ratios below are illustrative defaults. Replace them with
measured or CFD-derived values when available.

<|layout|columns=1 1 1|class_name=form-grid|
<|{bp_t3_surface_ratio}|number|label=Surface ε_loc/ε_avg|on_change=on_bp_t3_recalc|>
<|{bp_t3_mid_ratio}|number|label=Mid ε_loc/ε_avg|on_change=on_bp_t3_recalc|>
<|{bp_t3_impeller_ratio}|number|label=Impeller ε_loc/ε_avg|on_change=on_bp_t3_recalc|>
|>

<|Recalculate conditions|button|on_action=on_bp_t3_recalc|>

<|{bp_t3_cond_df}|table|width=100%|show_all|>

<|Download Test 3 conditions CSV|file_download|content={bp_t3_conditions_csv}|name=bourne_test_3_conditions.csv|label=Download Test 3 conditions CSV|>

### Enter measured responses
KPIs carry over from Test 2 — edit the responses (columns: **Surface / Mid /
Impeller**).

<|{bp_t3_kpi_df}|table|editable|rebuild|lov[KPI]={KPI_METRIC_OPTIONS}|lov[Unit]={UNIT_OPTIONS}|on_edit=on_bp_t3_kpi_edit|on_add=on_bp_t3_kpi_add|on_delete=on_bp_t3_kpi_delete|width=100%|show_all|class_name=bp-kpi-table|>

<|Assess Test 3|button|on_action=on_bp_t3_assess|class_name=compute-btn|>

<|part|render={bp_t3_assessed}|
<|{bp_t3_kpi_result_df}|table|width=100%|show_all|>

<|Download Test 3 KPI results CSV|file_download|content={bp_t3_results_csv}|name=bourne_test_3_kpi_results.csv|label=Download Test 3 KPI results CSV|>
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
<|{None}|file_download|on_action=on_bp_pdf_download|label=Download PDF|>
|>

### Export for the Reaction Sensitivity Protocol
Export the outcome as a CSV that can be imported into the **Reaction
Sensitivity Protocol** (Step 0 pre-screen) to feed the experimental result into
the overall sensitivity assessment.

<|Generate Sensitivity CSV|button|on_action=on_bp_export_sens_csv|class_name=compute-btn|>

<|part|render={bp_sens_csv_ready}|
<|{None}|file_download|on_action=on_bp_sens_csv_download|label=Download Sensitivity CSV|>
|>
|>
|>

<|part|render={bp_tab == "Plan"}|
## Experimental plan
Set the vessel, fluid and test inputs to calculate all three experimental condition sets. Planning does not require starting or assessing the protocol. These inputs are shared with the Protocol tab; changing them invalidates previous assessments.

<|part|class_name=va-card|
### System
<|layout|columns=1 1 1|
<|{bp_reactor}|selector|lov={reactor_options}|dropdown|label=Vessel|on_change=on_bp_reactor_change|>
<|{bp_fluid}|selector|lov={fluid_options}|dropdown|label=Fluid|on_change=on_bp_plan_fluid_change|>
<|{bp_v_l}|number|label=Working volume (L)|on_change=on_bp_plan_recalc|>
<|{bp_T}|number|label=Temperature (°C)|on_change=on_bp_plan_sys_change|>
<|{bp_P}|number|label=Pressure (atm)|on_change=on_bp_plan_sys_change|>
|>
<|{bp_reactor_summary_df}|table|show_all|width=100%|>
|>

<|part|class_name=va-card|
### Test 1: impeller speed
<|layout|columns=1 1 1|
<|{bp_t1_ctr_mode}|selector|lov={bp_t1_ctr_mode_options}|dropdown|label=Centre-point method|on_change=on_bp_plan_recalc|>
<|{bp_t1_pm_center}|number|label=Centre P/m (W/kg)|active={bp_t1_ctr_mode == bp_lbl_custom_pm}|on_change=on_bp_plan_recalc|>
<|{bp_t1_rpm_center}|number|label=Centre RPM|active={bp_t1_ctr_mode == bp_lbl_custom_rpm}|on_change=on_bp_plan_recalc|>
|>
<|{bp_t1_ctr_info}|text|mode=markdown|>
<|{bp_t1_hydro_df}|table|width=100%|show_all|>
<|Download Test 1 conditions CSV|file_download|content={bp_t1_conditions_csv}|name=bourne_test_1_conditions.csv|label=Download Test 1 conditions CSV|>
|>

<|part|class_name=va-card|
### Test 2: feed rate / time
<|layout|columns=1 1 1 1|
<|{bp_t2_feed_vol}|number|label=Total feed volume (mL)|on_change=on_bp_plan_recalc|>
<|{bp_t2_mode}|toggle|lov={bp_t2_mode_options}|label=Define by|on_change=on_bp_plan_recalc|>
<|{bp_t2_rate}|number|label=Feed rate (mL/min)|active={bp_t2_mode == bp_lbl_feed_rate}|on_change=on_bp_plan_recalc|>
<|{bp_t2_time}|number|label=Feed time (min)|active={bp_t2_mode == bp_lbl_feed_time}|on_change=on_bp_plan_recalc|>
|>
<|{bp_t2_cond_df}|table|width=100%|show_all|>
<|Download Test 2 conditions CSV|file_download|content={bp_t2_conditions_csv}|name=bourne_test_2_conditions.csv|label=Download Test 2 conditions CSV|>
|>

<|part|class_name=va-card|
### Test 3: feed location
Keep the centre-point speed and feed rate fixed. Local dissipation ratios are illustrative; use measured or CFD-derived values when available.
<|layout|columns=1 1 1|
<|{bp_t3_surface_ratio}|number|label=Surface ε_loc/ε_avg|on_change=on_bp_plan_recalc|>
<|{bp_t3_mid_ratio}|number|label=Mid ε_loc/ε_avg|on_change=on_bp_plan_recalc|>
<|{bp_t3_impeller_ratio}|number|label=Impeller ε_loc/ε_avg|on_change=on_bp_plan_recalc|>
|>
<|{bp_t3_cond_df}|table|width=100%|show_all|>
<|Download Test 3 conditions CSV|file_download|content={bp_t3_conditions_csv}|name=bourne_test_3_conditions.csv|label=Download Test 3 conditions CSV|>
|>
|>
""")
)
