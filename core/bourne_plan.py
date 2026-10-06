"""Bourne Protocol experiment planning: impeller speeds for target specific power,
fed-batch speed setpoints, feed-rate and feed-location test conditions."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from core.options import CenterMode
from utils.calculations import (
    average_shear_rate,
    blend_time_turbulent,
    impeller_power,
    kla_surface,
    kolmogorov_length,
    micromixing_time_engulfment,
    power_per_volume,
    reynolds_number,
    tip_speed,
)

DEFAULT_CENTER_PM = 0.2  # W/kg (Sarafinas 2018)
T1_CONDITIONS = (("Low (0.1× P/m)", 0.1), ("Centre (1× P/m)", 1.0), ("High (10× P/m)", 10.0))
T2_CONDITIONS = (
    ("Slow (1/3× rate)", 3.0, "Long feed → approaches well-mixed limit"),
    ("Centre", 1.0, "Reference feed rate"),
    ("Fast (3× rate)", 1.0 / 3.0, "Short feed → tests inertial-convective break-up"),
)


@dataclass(frozen=True)
class BourneSystem:
    D_imp: float
    Np: float
    rho: float
    mu: float
    D_mol: float
    V_L: float
    n_min: float = 0.0
    n_max: float = 0.0
    D_tank: float = 0.0
    H_liquid: float = 0.0

    @property
    def V_m3(self) -> float:
        return self.V_L / 1000.0

    @property
    def nu(self) -> float:
        return self.mu / self.rho if self.rho > 0 else 0.0


def n_for_pm(pm_wkg: float, V_m3: float, Np: float, D: float) -> float:
    """Impeller speed (rev/s) that delivers a given specific power P/m (W/kg)."""
    if Np <= 0 or D <= 0 or V_m3 <= 0 or pm_wkg <= 0:
        return 0.0
    return (pm_wkg * V_m3 / (Np * D**5)) ** (1.0 / 3.0)


def specific_power(sys: BourneSystem, n_rps: float) -> float:
    """P/m (W/kg) at a given speed."""
    P = impeller_power(sys.Np, sys.rho, n_rps, sys.D_imp)
    return power_per_volume(P, sys.V_m3) / sys.rho if (sys.V_m3 > 0 and sys.rho > 0) else 0.0


def center_point(sys: BourneSystem, mode: CenterMode, pm_custom: float,
                 rpm_custom: float) -> dict:
    """Test 1 centre point: {source (CenterMode), pm (W/kg), n_rpm, P_V_W_L, n_min, n_max,
    in_range}. ``in_range`` is None when no range is checked (custom P/m).
    """
    n_min, n_max = sys.n_min, sys.n_max
    if mode == CenterMode.CUSTOM_RPM:
        n_rpm = max(rpm_custom, 1e-9)
        pm = specific_power(sys, n_rpm / 60.0)
        P = impeller_power(sys.Np, sys.rho, n_rpm / 60.0, sys.D_imp)
        source, p_v = CenterMode.CUSTOM_RPM, power_per_volume(P, sys.V_m3) / 1000
    elif mode == CenterMode.CUSTOM_PM:
        pm = max(pm_custom, 0.0)
        source, p_v = CenterMode.CUSTOM_PM, None
        n_rpm = n_for_pm(pm, sys.V_m3, sys.Np, sys.D_imp) * 60.0
    else:
        pm = DEFAULT_CENTER_PM
        source, p_v = CenterMode.DEFAULT, None
        n_rpm = n_for_pm(pm, sys.V_m3, sys.Np, sys.D_imp) * 60.0
    in_range = (n_min <= n_rpm <= n_max) if (n_max > 0 and source != CenterMode.CUSTOM_PM) else None
    return {"source": source, "pm": pm, "n_rpm": n_rpm, "P_V_W_L": p_v,
            "n_min": n_min, "n_max": n_max, "in_range": in_range}


def center_info_md(c: dict) -> str:
    rng = f"({c['n_min']:.0f}–{c['n_max']:.0f} RPM)"
    if c["source"] == CenterMode.CUSTOM_RPM:
        info = (f"Custom centre: **N = {c['n_rpm']:.1f} RPM** → **P/m = {c['pm']:.4g} W/kg** "
                f"({c['P_V_W_L']:.4g} W/L).")
        if c["in_range"] is False:
            info += f" ⚠ Outside reactor range {rng}."
        return info
    if c["source"] == CenterMode.CUSTOM_PM:
        return f"Custom centre: **P/m = {c['pm']:.4g} W/kg** at **N = {c['n_rpm']:.0f} RPM**."
    info = f"Default centre (Sarafinas 2018): **P/m = 0.2 W/kg** at **N = {c['n_rpm']:.0f} RPM**."
    if c["in_range"] is False:
        info += f" ⚠ Requires {c['n_rpm']:.0f} RPM — outside reactor range {rng}."
    elif c["in_range"]:
        info += f" Within reactor range {rng}."
    return info


def resolve_center_pm(sys: BourneSystem, mode: CenterMode, pm_custom: float,
                      rpm_custom: float) -> tuple[float, str]:
    """Test 1 centre-point P/m (W/kg) and its Markdown info caption."""
    c = center_point(sys, mode, pm_custom, rpm_custom)
    return c["pm"], center_info_md(c)


def test1_conditions(sys: BourneSystem, pm_center: float) -> list[dict]:
    """Raw Test 1 conditions (0.1× / 1× / 10× centre P/m) after clamping to the RPM range."""
    rows = []
    for label, factor in T1_CONDITIONS:
        n_rpm = n_for_pm(pm_center * factor, sys.V_m3, sys.Np, sys.D_imp) * 60.0
        note = ""
        if sys.n_max > 0 and n_rpm > sys.n_max:
            n_rpm, note = sys.n_max, " (clamped to N_max)"
        if sys.n_min > 0 and n_rpm < sys.n_min:
            n_rpm, note = sys.n_min, " (clamped to N_min)"
        n_rps = n_rpm / 60.0
        P = impeller_power(sys.Np, sys.rho, n_rps, sys.D_imp)
        eps = power_per_volume(P, sys.V_m3) if sys.V_m3 > 0 else 0.0
        eps_kg = eps / sys.rho if sys.rho > 0 else 0.0
        rows.append({
            "Condition": label, "note": note, "Volume (L)": sys.V_L,
            "N (RPM)": n_rpm, "P/V (W/L)": eps / 1000.0, "P/m (W/kg)": eps_kg,
            "Blend time (s)": blend_time_turbulent(sys.Np, n_rps, sys.D_imp, sys.D_tank, sys.H_liquid),
            "Avg shear rate (1/s)": average_shear_rate(P, sys.mu, sys.V_m3),
            "Tip speed (m/s)": tip_speed(n_rps, sys.D_imp),
            "Re": reynolds_number(n_rps, sys.D_imp, sys.rho, sys.mu),
            "kLa_surface (1/s)": kla_surface(eps_kg, sys.nu, sys.D_mol, sys.D_tank, sys.V_m3),
            "t_E micro (s)": micromixing_time_engulfment(eps_kg, sys.nu),
            "η (µm)": kolmogorov_length(sys.nu, eps_kg) * 1e6,
        })
    return rows


def centerpoint_metrics(sys: BourneSystem, pm_center: float) -> dict:
    """Hydrodynamics at the (unclamped) Test 1 centre point, for the report."""
    n_rps = n_for_pm(pm_center, sys.V_m3, sys.Np, sys.D_imp)
    eps_kg = specific_power(sys, n_rps)
    return {
        "N (RPM)": n_rps * 60.0,
        "P/m (W/kg)": eps_kg,
        "Re": reynolds_number(n_rps, sys.D_imp, sys.rho, sys.mu),
        "Tip speed (m/s)": tip_speed(n_rps, sys.D_imp),
        "Blend time (s)": blend_time_turbulent(sys.Np, n_rps, sys.D_imp, sys.D_tank, sys.H_liquid),
        "Micromix t_E (s)": micromixing_time_engulfment(eps_kg, sys.nu),
        "Kolmogorov eta (um)": kolmogorov_length(sys.nu, eps_kg) * 1e6,
    }


def pm_range_ratio(pm_values) -> float:
    """High/low P/m ratio actually achieved (0 when fewer than two positive values)."""
    values = [v for v in pm_values if v > 0]
    if len(values) < 2:
        return 0.0
    return max(values) / min(values)


def speed_setpoints(sys: BourneSystem, pm_center: float,
                    steps: list[tuple[str, float]]) -> tuple[list[dict], bool]:
    """Low/centre/high RPM per fill-volume step holding each condition's P/m constant.

    Returns (rows with numeric RPM and a ``clamped`` flag per column, any clamped?).
    """
    targets = (("Low (RPM)", pm_center * 0.1), ("Centre (RPM)", pm_center),
               ("High (RPM)", pm_center * 10.0))
    rows, any_clamped = [], False
    for label, vol in steps:
        row = {"Step": label, "Volume (L)": vol}
        for col, pm in targets:
            n_rpm = n_for_pm(pm, vol / 1000.0, sys.Np, sys.D_imp) * 60.0
            clamped = False
            if sys.n_max > 0 and n_rpm > sys.n_max:
                n_rpm, clamped = sys.n_max, True
            elif sys.n_min > 0 and 0 < n_rpm < sys.n_min:
                n_rpm, clamped = sys.n_min, True
            row[col] = (n_rpm, clamped)
            any_clamped |= clamped
        rows.append(row)
    return rows, any_clamped


def test2_conditions(feed_volume_mL: float, by_rate: bool, rate_mL_min: float,
                     time_min: float) -> list[dict]:
    """Slow / centre / fast feed conditions (3× span either side of the centre)."""
    if by_rate:
        t_c = feed_volume_mL / max(rate_mL_min, 1e-9)
    else:
        t_c = max(time_min, 1e-9)
    rows = []
    for label, factor, note in T2_CONDITIONS:
        tf = t_c * factor
        rows.append({"Condition": label, "Feed time (min)": tf,
                     "Flow rate (mL/min)": feed_volume_mL / tf if tf > 0 else 0.0, "Note": note})
    return rows


def test3_conditions(sys: BourneSystem, pm_center: float,
                     ratios: list[tuple[str, float]]) -> list[dict]:
    """Local dissipation and micromixing time at each feed location (ε_loc = ratio·ε_avg)."""
    eps_avg = specific_power(sys, n_for_pm(pm_center, sys.V_m3, sys.Np, sys.D_imp))
    rows = []
    for loc, ratio in ratios:
        ratio = max(ratio, 1e-9)
        eps_loc = ratio * eps_avg
        rows.append({"Feed location": loc, "ε_loc/ε_avg": ratio, "ε_loc (W/kg)": eps_loc,
                     "t_E micro (s)": micromixing_time_engulfment(eps_loc, sys.nu)})
    return rows


T1_PLAN_LINES = (("0.1× P/m", 0.1), ("1× P/m (centre)", 1.0), ("10× P/m", 10.0))


def t1_speed_plan(sys: BourneSystem, pm_center: float, v_min: float, v_max: float,
                  adj_volumes=(), n_pts: int = 50) -> dict | None:
    """Iso-P/m impeller-speed lines (0.1x / 1x / 10x centre) across the fill range,
    the centre point at V_L and the fed-batch set-points; None without a fill range."""
    if not (v_max > v_min > 0):
        return None
    vols = np.linspace(v_min, v_max, n_pts)

    def rpm_at(pm, v_l):
        return n_for_pm(pm, v_l / 1000.0, sys.Np, sys.D_imp) * 60.0

    adj = [v for v in adj_volumes if v > 0]
    return {
        "volumes": vols,
        "lines": [{"label": label, "pm": pm_center * m,
                   "rpm": [rpm_at(pm_center * m, v) for v in vols],
                   "adj_rpm": [rpm_at(pm_center * m, v) for v in adj]}
                  for label, m in T1_PLAN_LINES],
        "centre": (sys.V_L, rpm_at(pm_center, sys.V_L)),
        "adj_volumes": adj, "n_min": sys.n_min, "n_max": sys.n_max,
    }


def t2_report_conditions(sys: BourneSystem, pm_center: float, feed_volume_mL: float,
                         feed_time_min: float) -> dict:
    """Test 2 feed-time conditions (centre / 3x slower / 3x faster) for the PDF report."""
    rows = []
    for label, tf in (("Slow (1/3x rate)", feed_time_min * 3.0), ("Centre", feed_time_min),
                      ("Fast (3x rate)", feed_time_min / 3.0)):
        rows.append({"Condition": label, "Feed time (min)": tf,
                     "Flow rate (mL/min)": feed_volume_mL / tf if tf > 0 else 0.0})
    return {"N_RPM": n_for_pm(pm_center, sys.V_m3, sys.Np, sys.D_imp) * 60.0,
            "feed_vol_mL": feed_volume_mL, "feed_location": "Held constant (centerpoint)",
            "rows": rows}


T3_LOCATIONS = ("Surface", "Sub-surface (mid-tank)", "Impeller zone")


def t3_location_ratios(surface: float, mid: float, impeller: float) -> list[tuple[str, float]]:
    """(feed location, ε_loc/ε_avg) pairs for the Test 3 report conditions."""
    return list(zip(T3_LOCATIONS, (surface, mid, impeller)))


def t3_report_conditions(sys: BourneSystem, pm_center: float,
                         ratios: list[tuple[str, float]], feed_time_min: float) -> dict:
    """Test 3 local dissipation per feed location (ε_loc = ratio·ε_avg) for the PDF report."""
    n_rps = n_for_pm(pm_center, sys.V_m3, sys.Np, sys.D_imp)
    eps_avg = specific_power(sys, n_rps)
    rows = []
    for loc, ratio in ratios:
        ratio = max(ratio, 1e-9)
        rows.append({"Feed Location": loc, "eps_loc/eps_avg": ratio,
                     "eps_loc (W/kg)": ratio * eps_avg})
    return {"N_RPM": n_rps * 60.0, "feed_time_min": feed_time_min,
            "eps_avg_W_kg": eps_avg, "rows": rows}
