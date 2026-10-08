"""Pure builders for the ``snap`` dicts consumed by ``reports.pdf.build_*_pdf``.

Every function takes plain values (results, tables, figures, labels) — never GUI
state — so a page and an HTTP endpoint produce the same report.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from core.options import Phase
from core.heat_transfer import (
    compute_batch,
    compute_reaction_profile,
    resistance_breakdown,
    resistance_items,
    time_factor,
    ua_sweep_series,
)
from reports import pdf as rb
from utils.bourne_kpi import KPI_COLUMNS
from viz import heat_transfer as viz_ht


def project_meta(project_name: str = "", step_number: str = "", unit_operation: str = "",
                 process_version: str = "") -> dict:
    """Report header fields (blank unit operation when the placeholder is selected)."""
    return {"project_name": project_name, "step_number": step_number,
            "unit_operation": unit_operation, "process_version": process_version}


def _png(fig) -> bytes | None:
    """PNG bytes for a chart, or None when the image export backend is unavailable."""
    try:
        return rb.fig_to_png_bytes(fig)
    except Exception:  # noqa: BLE001
        return None


# ---------------------------------------------------------------------------
# Vessel Assessment / Comparison
# ---------------------------------------------------------------------------
def assessment_snapshot(*, reactor: str, fluid: str, T_C: float, P_atm: float, N_rpm: float,
                        V_L: float, corr_label: str, reaction: str, t_rxn: float, dH: float,
                        tables: dict, env_fig, env_caption: str, env_params: list[str]) -> dict:
    """``tables`` as returned by :func:`reports.tables.assessment_tables`."""
    return {
        "reactor": reactor, "fluid": fluid, "T": T_C, "P": P_atm, "N_rpm": N_rpm,
        "V_L": V_L, "corr_mode": corr_label, "reaction": reaction, "t_rxn": t_rxn, "dH": dH,
        "hydro_df": tables["hydro"], "assessment": tables["assessment"],
        "dam_df": tables["damkohler"], "sl_df": tables["solids"], "heat_df": tables["heat"],
        "env_fig": env_fig, "env_caption": env_caption, "env_params": env_params,
    }


COMPARISON_CHART_PARAMS = ["Da_micro", "Da_macro", "Da_GL", "P/V (W/L)",
                           "Blend time 95% (s)", "Tip speed (m/s)"]


def comparison_snapshot(result: dict, *, scale_param: str = "",
                        scale_basis_reactor: str = "") -> dict:
    """``result`` is the comparison cache: env_df, agg_df, reactor_info, curve_data,
    present, fluid_name, fluid_T_C, rxn_name, t_rxn, incl_heat, incl_particles."""
    return {
        "selected_names": result["env_df"]["Reactor"].drop_duplicates().tolist(),
        "fluid": result["fluid_name"], "fluid_T_C": result["fluid_T_C"],
        "reaction": result["rxn_name"], "t_rxn": result["t_rxn"],
        "env_df": result["env_df"], "agg_df": result["agg_df"],
        "reactor_info": result["reactor_info"], "include_heat": result["incl_heat"],
        "include_particles": result["incl_particles"],
        "scaling_results": [], "scaling_all_params": [],
        "scale_param": scale_param, "scale_basis_reactor": scale_basis_reactor,
        "curve_data": result["curve_data"],
        "report_chart_params": [p for p in COMPARISON_CHART_PARAMS if p in result["present"]],
    }


# ---------------------------------------------------------------------------
# Reaction Sensitivity Protocol
# ---------------------------------------------------------------------------
def protocol_snapshot(res: dict, md: dict, *, reaction: str, competing_label: str,
                      bourne_meta: dict | None = None) -> dict:
    """From ``assess_protocol`` (``res``) and ``protocol_md`` (``md``); ``competing_label``
    is the UI wording of the competing-reactions answer."""
    from core.sensitivity_rules import strip_md

    bourne_txt = {True: "Mixing sensitivity confirmed", False: "No sensitivity observed",
                  None: "Not performed / undetermined"}[res["b_sensitive"]]
    return {
        "reaction": reaction, "t_rxn": res["t_rxn"], "rxn_delta_H": res["dH_eff"],
        "dT_ad": res["dt_ad"], "phases": [Phase(p).label for p in res["phases"]],
        "findings": md["findings"], "next_steps": md["next_steps"],
        "bourne_result": bourne_txt, "bourne_tests": res["bourne_rows"],
        "bourne_mechanism": res["b_mechs"][0] if res["b_mechs"] else "",
        "bourne_meta": dict(bourne_meta or {}),
        "competing": competing_label if res["competing_set"] else "Not assessed",
        "overall_verdict": strip_md(md["verdict"]), "verdict_kind": res["verdict"].kind,
        "using_approximate": res["using_approx"],
        "dh_estimated": res["dh_estimated"], "is_semi_batch": res["is_semi_batch"],
        "damkohler": dict(res["da"]) if res["da"] else {},
    }


# ---------------------------------------------------------------------------
# Bourne Protocol
# ---------------------------------------------------------------------------
T1_REPORT_KEYS = ("Condition", "Volume (L)", "N (RPM)", "P/m (W/kg)", "P/V (W/L)",
                  "Tip speed (m/s)", "Avg shear rate (1/s)", "kLa_surface (1/s)")


def kpi_responses(res: dict, test: int) -> dict:
    """A ``utils.bourne_kpi.assess_kpis`` result in the report's response layout."""
    low, ctr, high = KPI_COLUMNS[test]
    return {
        "labels": [low, ctr, high],
        "kpi_results": [{
            "name": f'{r["name"]} ({r["unit"]})' if r["unit"] else r["name"],
            "qualitative": False,
            "resp": [r["low"], r["ctr"], r["high"]],
            "max_pct": r["max_pct"],
            "sensitive": r["sensitive"],
        } for r in res["results"]],
        "n_sensitive": res["n_sensitive"],
        "n_total": res["n_total"],
        "status": res["status"],
        "sensitive": res["sensitive"],
    }


def t1_report_conditions(rows: list[dict]) -> list[dict]:
    """``core.bourne_plan.test1_conditions`` rows trimmed to the report columns."""
    out = []
    for r in rows:
        snap = {k: r[k] for k in T1_REPORT_KEYS}
        snap["Condition"] = r["Condition"].replace("×", "x") + r["note"]
        out.append(snap)
    return out


def bourne_snapshot(*, reactor: str, fluid: str, V_L: float, dominant: str,
                    conclusions: list, t1_rows: list[dict], t1_result: dict,
                    centerpoint: dict, t2: tuple[dict, dict] | None = None,
                    t3: tuple[dict, dict] | None = None, project: dict | None = None) -> dict:
    """``t2`` / ``t3`` are (report conditions, KPI assessment) for the tests that were run."""
    snap = {
        "reactor": reactor, "fluid": fluid, "V_L": V_L, "dominant": dominant,
        "conclusions": conclusions, "scaleup_notes": [],
        "t1_conditions": t1_report_conditions(t1_rows),
        "t1_responses": kpi_responses(t1_result, 1),
        "centerpoint_metrics": centerpoint,
    }
    if t2:
        snap["t2_conditions"], snap["t2_responses"] = t2[0], kpi_responses(t2[1], 2)
    if t3:
        snap["t3_conditions"], snap["t3_responses"] = t3[0], kpi_responses(t3[1], 3)
    snap.update(project or project_meta())
    return snap


# ---------------------------------------------------------------------------
# Heat Transfer
# ---------------------------------------------------------------------------
def _nu_records(df: pd.DataFrame) -> list[dict]:
    if df is None or df.empty:
        return []
    return [{
        "Correlation": r.get("Correlation", ""),
        "Nu": r.get("Nu", 0),
        "h_i (W/(m2.K))": r.get("h_i (W/m2.K)", 0),
        "U (W/(m2.K))": r.get("U (W/m2.K)", 0),
        "Time (min)": r.get("Time (min)", 0),
    } for _, r in df.iterrows()]


def _htm_records(df: pd.DataFrame) -> list[dict]:
    if df is None or df.empty:
        return []
    return [{
        "Medium": r.get("Medium", ""),
        "h_o (W/(m2.K))": r.get("h_o (W/m2.K)", 0),
        "U (W/(m2.K))": r.get("U (W/m2.K)", 0),
        "Time (min)": r.get("Time (min)", 0),
        "In range?": r.get("In range", ""),
    } for _, r in df.iterrows()]


def heat_cool_snapshot(data: dict[str, Any], htm_db: dict, reactor_row: pd.Series, *,
                       reactor: str, fluid: str, wall_material: str, lining_material: str,
                       time_unit: str = "Minutes", project: dict | None = None) -> dict:
    """Heat/cool-to-target report: ``data`` is the ``compute_batch`` input dict."""
    result = compute_batch(data, htm_db)
    breakdown = resistance_breakdown(resistance_items(
        result.h_i, result.h_o, data["wall_k"], data["wall_thickness_mm"],
        data["lining_k"], data["lining_thickness_mm"], data["fouling"]))
    t_factor, t_label = time_factor(time_unit), time_unit.lower()
    ua = ua_sweep_series(data, htm_db, reactor_row, data["a_ht"])
    figs = {
        "fig_T_png": viz_ht.batch_temperature(
            result.t_const / t_factor, result.T_const, result.t_var / t_factor, result.T_var,
            result.Tj_out, t_label, data["t_target"], data["t_jacket"]),
        "fig_Q_png": viz_ht.jacket_duty(result.t_const / t_factor, result.q_const,
                                        result.t_var / t_factor, result.q_var, t_label),
        "fig_resistance_png": viz_ht.resistance_bars(breakdown),
        "fig_rpm_U_png": viz_ht.ua_vs_speed(ua["rpm"], ua["ua_rpm"], data["n_rpm"], data["v_l"]),
        "fig_rpm_time_png": viz_ht.ua_vs_volume(ua["volume"], ua["ua_volume"], data["v_l"],
                                                data["n_rpm"]),
    }
    analytical_min = (result.time_analytical_s / 60.0
                      if np.isfinite(result.time_analytical_s) else float("inf"))
    snap = {
        "mode": "heat_cool",
        "reactor": reactor, "fluid": fluid,
        "fluid_T_C": data["t_start"], "N_rpm": data["n_rpm"], "V_L": data["v_l"],
        "htm_name": data["htm_name"], "nu_corr": data["nusselt_correlation"],
        "T_start": data["t_start"], "T_target": data["t_target"],
        "T_jacket_in": data["t_jacket"],
        "wall_material": wall_material, "wall_mm": data["wall_thickness_mm"],
        "lining_material": lining_material, "fouling_R": data["fouling"],
        "coefficients": {
            "h_i": result.h_i, "h_o": result.h_o, "U": result.u, "Nu": result.nu,
            "Re": result.re, "Pr": result.pr, "A_ht": data["a_ht"],
            "P_agitator": result.p_agitator_w,
        },
        "resistances": breakdown,
        "time_estimates": {
            "Q_max": result.q_max_w, "dT_dt_init": result.dt_dt_c_per_min,
            "t_analytical_min": analytical_min,
            "t_sim_const_min": result.time_const_jacket_s / 60.0,
            "t_sim_var_min": result.time_variable_jacket_s / 60.0,
        },
        "controlling_resistance": max(breakdown, key=lambda t: t[2])[0] if breakdown else "",
        "nusselt_comparison": _nu_records(result.corr_comparison),
        "htm_comparison": _htm_records(result.htm_comparison),
        **{key: _png(fig) for key, fig in figs.items()},
    }
    snap.update(project or project_meta())
    return snap


def reaction_snapshot(data: dict[str, Any], htm_db: dict, *, reactor: str, fluid: str,
                      time_unit: str = "Minutes", project: dict | None = None) -> dict:
    """Reaction temperature-profile report: ``data`` is the ``compute_reaction_profile`` input."""
    result = compute_reaction_profile(data, htm_db)
    fig = viz_ht.reaction_profile(result.t / time_factor(time_unit), result.T,
                                  result.conversion * 100.0, time_unit.lower(),
                                  data["t_jacket"], result.T_adiabatic_c)
    snap = {
        "mode": "reaction",
        "reactor": reactor, "fluid": fluid,
        "fluid_T_C": data["t_start"], "N_rpm": data["n_rpm"], "V_L": data["v_l"],
        "T_start": data["t_start"], "T_jacket_in": data["t_jacket"],
        "rxn_order": data["rxn_order"], "rxn_k": data["rxn_k"], "rxn_c0": data["rxn_c0"],
        "rxn_dH": data["rxn_dH"],
        "adiabatic_rise": result.T_adiabatic_c - data["t_start"],
        "T_adiabatic": result.T_adiabatic_c, "T_peak": result.T_peak_c,
        "t_complete_min": (result.t_complete_s / 60.0
                           if np.isfinite(result.t_complete_s) else float("inf")),
        "rxn_summary": [(str(r.get("Metric", "")), str(r.get("Value", "")))
                        for _, r in result.summary.iterrows()],
        "fig_profile_png": _png(fig),
    }
    snap.update(project or project_meta())
    return snap
