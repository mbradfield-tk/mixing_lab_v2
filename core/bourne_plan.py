"""Bourne Protocol experiment planning: impeller speeds for target specific power,
fed-batch speed setpoints, feed-rate and feed-location test conditions."""
from __future__ import annotations

from dataclasses import dataclass

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


def resolve_center_pm(sys: BourneSystem, mode: str, pm_custom: float,
                      rpm_custom: float) -> tuple[float, str]:
    """Test 1 centre-point P/m (W/kg) and an info caption.

    Modes: "Custom RPM" (converted via the power draw), "Custom P/m", or the
    default 0.2 W/kg.
    """
    n_min, n_max = sys.n_min, sys.n_max
    if mode == "Custom RPM":
        rpm = max(rpm_custom, 1e-9)
        pm = specific_power(sys, rpm / 60.0)
        P = impeller_power(sys.Np, sys.rho, rpm / 60.0, sys.D_imp)
        info = (f"Custom centre: **N = {rpm:.1f} RPM** → **P/m = {pm:.4g} W/kg** "
                f"({power_per_volume(P, sys.V_m3) / 1000:.4g} W/L).")
        if n_max > 0 and (rpm > n_max or rpm < n_min):
            info += f" ⚠ Outside reactor range ({n_min:.0f}–{n_max:.0f} RPM)."
        return pm, info

    if mode == "Custom P/m":
        pm = max(pm_custom, 0.0)
        n_rpm = n_for_pm(pm, sys.V_m3, sys.Np, sys.D_imp) * 60.0
        return pm, f"Custom centre: **P/m = {pm:.4g} W/kg** at **N = {n_rpm:.0f} RPM**."

    pm = DEFAULT_CENTER_PM
    n_rpm = n_for_pm(pm, sys.V_m3, sys.Np, sys.D_imp) * 60.0
    info = f"Default centre (Sarafinas 2018): **P/m = 0.2 W/kg** at **N = {n_rpm:.0f} RPM**."
    if n_max > 0:
        if n_rpm < n_min or n_rpm > n_max:
            info += (f" ⚠ Requires {n_rpm:.0f} RPM — outside reactor range "
                     f"({n_min:.0f}–{n_max:.0f} RPM).")
        else:
            info += f" Within reactor range ({n_min:.0f}–{n_max:.0f} RPM)."
    return pm, info


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
