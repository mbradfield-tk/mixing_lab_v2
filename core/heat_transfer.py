from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from core.records import bottom_dish_height
from utils.calculations.geometry import liquid_height_from_volume
from utils.calculations.heat_transfer import (
    NUSSELT_CORRELATIONS, estimate_jacket_area, estimate_U_from_resistances, jacket_side_htc,
    nusselt_jacket, time_to_cool_or_heat,
)
from utils.calculations.hydrodynamics import impeller_power


@dataclass
class BatchResult:
    re: float
    pr: float
    nu: float
    h_i: float
    h_o: float
    u: float
    area: float
    p_agitator_w: float
    q_max_w: float
    dt_dt_c_per_min: float
    time_analytical_s: float
    time_const_jacket_s: float
    time_variable_jacket_s: float
    t_const: np.ndarray
    T_const: np.ndarray
    t_var: np.ndarray
    T_var: np.ndarray
    Tj_out: np.ndarray
    q_const: np.ndarray
    q_var: np.ndarray
    corr_comparison: pd.DataFrame
    htm_comparison: pd.DataFrame
    summary: pd.DataFrame


@dataclass
class ReactionResult:
    re: float
    pr: float
    nu: float
    h_i: float
    h_o: float
    u: float
    area: float
    p_agitator_w: float
    t: np.ndarray            # time (s)
    T: np.ndarray            # batch temperature (C)
    conversion: np.ndarray   # fractional conversion 0..1
    q_rxn: np.ndarray        # reaction heat rate (W; + exothermic release)
    q_jacket: np.ndarray     # jacket heat rate (W; + into batch)
    t_complete_s: float      # time to 99% conversion (inf if not reached)
    T_peak_c: float
    t_peak_s: float
    T_adiabatic_c: float     # T_start + adiabatic rise (signed)
    q_rxn_max_w: float
    final_conversion: float
    summary: pd.DataFrame


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if pd.isna(value):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def load_csvs(data_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, dict[str, Any]]]:
    reactors = pd.read_csv(data_dir / "reactors.csv")
    fluids = pd.read_csv(data_dir / "fluids.csv")
    htm_df = pd.read_csv(data_dir / "HTM.csv")

    htm_db: dict[str, dict[str, Any]] = {}
    for _, row in htm_df.iterrows():
        entry: dict[str, Any] = {
            "T_min_C": safe_float(row.get("T_min_C")),
            "T_max_C": safe_float(row.get("T_max_C")),
            "rho_kg_m3": safe_float(row.get("rho_kg_m3")),
            "Cp_J_kgK": safe_float(row.get("Cp_J_kgK")),
            "mu_Pa_s": safe_float(row.get("mu_Pa_s")),
            "k_W_mK": safe_float(row.get("k_W_mK")),
            "notes": str(row.get("notes", "")),
        }
        if not pd.isna(row.get("h_jacket_override")):
            entry["h_jacket_override"] = safe_float(row.get("h_jacket_override"))
        htm_db[str(row["htm_name"])] = entry
    return reactors, fluids, htm_db


def profile_const_jacket(
    rho: float,
    V_L_m3: float,
    cp: float,
    U: float,
    area: float,
    t_start: float,
    t_target: float,
    t_jacket: float,
    p_agitator: float,
    q_rxn: float,
    dt: float,
    t_max: float,
) -> tuple[np.ndarray, np.ndarray]:
    if rho <= 0 or V_L_m3 <= 0 or cp <= 0 or U <= 0 or area <= 0:
        return np.array([0.0]), np.array([t_start])
    cooling = t_target < t_start
    m_cp = rho * V_L_m3 * cp
    steps = int(t_max / dt) + 1
    t_arr = np.zeros(steps)
    T_arr = np.zeros(steps)
    T_arr[0] = t_start
    for i in range(1, steps):
        t_prev = T_arr[i - 1]
        q_jacket = U * area * (t_jacket - t_prev)
        dTdt = (q_jacket + p_agitator + q_rxn) / m_cp
        T_arr[i] = t_prev + dTdt * dt
        t_arr[i] = i * dt
        if cooling and T_arr[i] <= t_target:
            return t_arr[: i + 1], T_arr[: i + 1]
        if not cooling and T_arr[i] >= t_target:
            return t_arr[: i + 1], T_arr[: i + 1]
    return t_arr, T_arr


def profile_variable_jacket(
    rho: float,
    V_L_m3: float,
    cp: float,
    U: float,
    area: float,
    t_start: float,
    t_target: float,
    t_jacket_in: float,
    m_dot_jacket: float,
    cp_jacket: float,
    p_agitator: float,
    q_rxn: float,
    dt: float,
    t_max: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    if rho <= 0 or V_L_m3 <= 0 or cp <= 0 or U <= 0 or area <= 0:
        return np.array([0.0]), np.array([t_start]), np.array([t_jacket_in])
    cooling = t_target < t_start
    m_cp = rho * V_L_m3 * cp
    steps = int(t_max / dt) + 1
    t_arr = np.zeros(steps)
    T_arr = np.zeros(steps)
    Tj_out = np.zeros(steps)
    T_arr[0] = t_start
    Tj_out[0] = t_jacket_in

    for i in range(1, steps):
        t_prev = T_arr[i - 1]
        if m_dot_jacket > 0 and cp_jacket > 0:
            ntu = U * area / (m_dot_jacket * cp_jacket)
            eff = 1.0 - np.exp(-ntu)
            q_jacket = eff * m_dot_jacket * cp_jacket * (t_jacket_in - t_prev)
            # Jacket loses the heat it gives the batch: Tj_out = Tj_in - q/(m_dot*cp)
            Tj_out[i] = t_jacket_in - q_jacket / (m_dot_jacket * cp_jacket)
        else:
            q_jacket = U * area * (t_jacket_in - t_prev)
            Tj_out[i] = t_jacket_in
        dTdt = (q_jacket + p_agitator + q_rxn) / m_cp
        T_arr[i] = t_prev + dTdt * dt
        t_arr[i] = i * dt
        if cooling and T_arr[i] <= t_target:
            return t_arr[: i + 1], T_arr[: i + 1], Tj_out[: i + 1]
        if not cooling and T_arr[i] >= t_target:
            return t_arr[: i + 1], T_arr[: i + 1], Tj_out[: i + 1]
    return t_arr, T_arr, Tj_out


def find_best_material_key(name: str, candidates: list[str]) -> str:
    n = (name or "").strip().lower()
    if not n:
        return candidates[0]
    for c in candidates:
        cl = c.lower()
        if n in cl or cl in n:
            return c
    return candidates[0]


def compute_batch(data: dict[str, Any], htm_db: dict[str, dict[str, Any]]) -> BatchResult:
    rho = safe_float(data["rho"])
    mu = safe_float(data["mu"])
    cp = safe_float(data["cp"])
    k_fluid = safe_float(data["k_fluid"])
    d_tank = safe_float(data["d_tank"])
    d_imp = safe_float(data["d_imp"])
    n_rpm = safe_float(data["n_rpm"])
    n_rps = n_rpm / 60.0
    np_in = safe_float(data["np_in"])
    v_l = safe_float(data["v_l"])
    v_l_m3 = v_l / 1000.0
    t_start = safe_float(data["t_start"])
    t_target = safe_float(data["t_target"])
    t_jacket = safe_float(data["t_jacket"])
    mu_wall = safe_float(data["mu_wall"])
    corr = str(data["nusselt_correlation"])
    htm_name = str(data["htm_name"])
    htm = htm_db[htm_name]
    v_jacket = safe_float(data["v_jacket"])
    d_hyd_jacket = safe_float(data["d_hyd_jacket"])
    m_dot_jacket = safe_float(data["m_dot_jacket"])
    cp_jacket = safe_float(data["cp_jacket"])
    q_rxn = safe_float(data["q_rxn"])
    include_agitator = bool(data["include_agitator"])

    wall_k = safe_float(data["wall_k"])
    wall_m = safe_float(data["wall_thickness_mm"]) / 1000.0
    lining_k = safe_float(data["lining_k"])
    lining_m = safe_float(data["lining_thickness_mm"]) / 1000.0
    fouling = safe_float(data["fouling"])
    area = safe_float(data["a_ht"])

    if area <= 0:
        area = 0.001

    re = rho * n_rps * d_imp**2 / mu if mu > 0 else 0.0
    pr = cp * mu / k_fluid if k_fluid > 0 else 0.0
    mu_ratio = mu / mu_wall if mu_wall > 0 else 1.0
    nu = nusselt_jacket(re, pr, mu_ratio, corr)
    h_i = nu * k_fluid / d_tank if d_tank > 0 else 0.0
    h_o = jacket_side_htc(htm, v_jacket, d_hyd_jacket)
    u = estimate_U_from_resistances(h_i, h_o, wall_k, wall_m, lining_k, lining_m, fouling)
    p_agitator_w = impeller_power(np_in, rho, n_rps, d_imp) if include_agitator else 0.0

    q_max = u * area * abs(t_start - t_jacket)
    # Initial rate magnitude: agitator power opposes cooling but adds to heating.
    q_net0 = u * area * (t_jacket - t_start) + p_agitator_w
    dt_dt = (abs(q_net0) / (rho * v_l_m3 * cp) * 60.0) if rho > 0 and v_l_m3 > 0 and cp > 0 else 0.0
    t_analytical = time_to_cool_or_heat(rho, v_l_m3, cp, u, area, t_start, t_target, t_jacket)

    dt = max(0.5, t_analytical / 2000) if np.isfinite(t_analytical) else 1.0
    t_max = min((t_analytical * 2.0) if np.isfinite(t_analytical) else 36000.0, 86400.0)
    t_const, T_const = profile_const_jacket(
        rho, v_l_m3, cp, u, area, t_start, t_target, t_jacket, p_agitator_w, q_rxn, dt, t_max
    )
    t_var, T_var, Tj_out = profile_variable_jacket(
        rho, v_l_m3, cp, u, area, t_start, t_target, t_jacket, m_dot_jacket, cp_jacket, p_agitator_w, q_rxn, dt, t_max
    )
    time_const = float(t_const[-1]) if len(t_const) else np.inf
    time_var = float(t_var[-1]) if len(t_var) else np.inf
    q_const = u * area * (t_jacket - T_const)
    if m_dot_jacket > 0 and cp_jacket > 0:
        ntu = u * area / (m_dot_jacket * cp_jacket)
        eff = 1.0 - np.exp(-ntu)
        q_var = eff * m_dot_jacket * cp_jacket * (t_jacket - T_var)
    else:
        q_var = u * area * (t_jacket - T_var)

    corr_rows: list[dict[str, Any]] = []
    for c_name in NUSSELT_CORRELATIONS:
        nu_c = nusselt_jacket(re, pr, mu_ratio, c_name)
        hi_c = nu_c * k_fluid / d_tank if d_tank > 0 else 0.0
        u_c = estimate_U_from_resistances(hi_c, h_o, wall_k, wall_m, lining_k, lining_m, fouling)
        t_c = time_to_cool_or_heat(rho, v_l_m3, cp, u_c, area, t_start, t_target, t_jacket)
        corr_rows.append(
            {
                "Correlation": c_name,
                "Nu": round(nu_c, 1),
                "h_i (W/m2.K)": round(hi_c, 1),
                "U (W/m2.K)": round(u_c, 1),
                "UA (W/K)": round(u_c * area, 2),
                "Time (min)": np.inf if not np.isfinite(t_c) else round(t_c / 60.0, 1),
            }
        )
    corr_df = pd.DataFrame(corr_rows)

    htm_rows: list[dict[str, Any]] = []
    for h_name, h_data in htm_db.items():
        ho_c = jacket_side_htc(h_data, v_jacket, d_hyd_jacket)
        u_c = estimate_U_from_resistances(h_i, ho_c, wall_k, wall_m, lining_k, lining_m, fouling)
        t_c = time_to_cool_or_heat(rho, v_l_m3, cp, u_c, area, t_start, t_target, t_jacket)
        in_range = safe_float(h_data["T_min_C"]) <= t_jacket <= safe_float(h_data["T_max_C"])
        htm_rows.append(
            {
                "Medium": h_name,
                "h_o (W/m2.K)": round(ho_c, 0),
                "U (W/m2.K)": round(u_c, 1),
                "UA (W/K)": round(u_c * area, 2),
                "Time (min)": np.inf if not np.isfinite(t_c) else round(t_c / 60.0, 1),
                "In range": "Yes" if in_range else "No",
            }
        )
    htm_df = pd.DataFrame(htm_rows).sort_values("Time (min)", na_position="last")

    summary = pd.DataFrame(
        [
            {"Metric": "Re", "Value": round(re, 0)},
            {"Metric": "Pr", "Value": round(pr, 2)},
            {"Metric": "Nu", "Value": round(nu, 2)},
            {"Metric": "h_i (W/m2.K)", "Value": round(h_i, 2)},
            {"Metric": "h_o (W/m2.K)", "Value": round(h_o, 2)},
            {"Metric": "U (W/m2.K)", "Value": round(u, 2)},
            {"Metric": "UA (W/K)", "Value": round(u * area, 2)},
            {"Metric": "A_ht (m2)", "Value": round(area, 4)},
            {"Metric": "P_agitator (W)", "Value": round(p_agitator_w, 2)},
            {"Metric": "Q_max initial (W)", "Value": round(q_max, 2)},
            {"Metric": "Initial dT/dt (C/min)", "Value": round(dt_dt, 4)},
            {"Metric": "Analytical time (min)", "Value": np.inf if not np.isfinite(t_analytical) else round(t_analytical / 60.0, 2)},
            {"Metric": "Simulated time const jacket (min)", "Value": round(time_const / 60.0, 2)},
            {"Metric": "Simulated time variable jacket (min)", "Value": round(time_var / 60.0, 2)},
        ]
    )

    return BatchResult(
        re=re,
        pr=pr,
        nu=nu,
        h_i=h_i,
        h_o=h_o,
        u=u,
        area=area,
        p_agitator_w=p_agitator_w,
        q_max_w=q_max,
        dt_dt_c_per_min=dt_dt,
        time_analytical_s=t_analytical,
        time_const_jacket_s=time_const,
        time_variable_jacket_s=time_var,
        t_const=t_const,
        T_const=T_const,
        t_var=t_var,
        T_var=T_var,
        Tj_out=Tj_out,
        q_const=q_const,
        q_var=q_var,
        corr_comparison=corr_df,
        htm_comparison=htm_df,
        summary=summary,
    )


def _heat_transfer_coeffs(data: dict[str, Any], htm_db: dict[str, dict[str, Any]]) -> dict[str, float]:
    """Process/jacket-side coefficients and overall U (shared by both modes)."""
    rho = safe_float(data["rho"])
    mu = safe_float(data["mu"])
    cp = safe_float(data["cp"])
    k_fluid = safe_float(data["k_fluid"])
    d_tank = safe_float(data["d_tank"])
    d_imp = safe_float(data["d_imp"])
    n_rps = safe_float(data["n_rpm"]) / 60.0
    np_in = safe_float(data["np_in"])
    mu_wall = safe_float(data["mu_wall"])
    corr = str(data["nusselt_correlation"])
    htm = htm_db[str(data["htm_name"])]
    v_jacket = safe_float(data["v_jacket"])
    d_hyd_jacket = safe_float(data["d_hyd_jacket"])
    wall_k = safe_float(data["wall_k"])
    wall_m = safe_float(data["wall_thickness_mm"]) / 1000.0
    lining_k = safe_float(data["lining_k"])
    lining_m = safe_float(data["lining_thickness_mm"]) / 1000.0
    fouling = safe_float(data["fouling"])

    re = rho * n_rps * d_imp**2 / mu if mu > 0 else 0.0
    pr = cp * mu / k_fluid if k_fluid > 0 else 0.0
    mu_ratio = mu / mu_wall if mu_wall > 0 else 1.0
    nu = nusselt_jacket(re, pr, mu_ratio, corr)
    h_i = nu * k_fluid / d_tank if d_tank > 0 else 0.0
    h_o = jacket_side_htc(htm, v_jacket, d_hyd_jacket)
    u = estimate_U_from_resistances(h_i, h_o, wall_k, wall_m, lining_k, lining_m, fouling)
    p_agitator_w = impeller_power(np_in, rho, n_rps, d_imp) if bool(data["include_agitator"]) else 0.0
    return {"re": re, "pr": pr, "nu": nu, "h_i": h_i, "h_o": h_o, "u": u, "p_agitator_w": p_agitator_w}


def compute_reaction_profile(data: dict[str, Any], htm_db: dict[str, dict[str, Any]]) -> ReactionResult:
    """Batch temperature vs time driven by an exo/endothermic reaction.

    The reaction is integrated with the supplied rate constant held fixed
    (isothermal-kinetics approximation — activation energy is not modelled), so
    conversion vs time is temperature-independent while the released/absorbed
    heat drives the batch energy balance against a constant-temperature jacket.
    The run stops at 99% conversion (or a time cap).
    """
    htc = _heat_transfer_coeffs(data, htm_db)
    re, pr, nu = htc["re"], htc["pr"], htc["nu"]
    h_i, h_o, u, p_agit = htc["h_i"], htc["h_o"], htc["u"], htc["p_agitator_w"]

    rho = safe_float(data["rho"])
    cp = safe_float(data["cp"])
    v_l = safe_float(data["v_l"])
    v_l_m3 = v_l / 1000.0
    area = safe_float(data["a_ht"]) or 0.001
    t_start = safe_float(data["t_start"])
    t_jacket = safe_float(data["t_jacket"])

    order = str(data["rxn_order"]).strip()
    k = safe_float(data["rxn_k"])
    c0 = safe_float(data["rxn_c0"])          # mol/L
    dh_kj = safe_float(data["rxn_dH"])       # kJ/mol (negative = exothermic)

    first = order in ("1", "pseudo-1")
    second = order in ("2", "pseudo-2")
    m_cp = rho * v_l_m3 * cp                  # J/K

    n0 = c0 * v_l                            # mol
    # Adiabatic rise (signed): exothermic (dH<0) raises T.
    adiabatic_rise = (-dh_kj * 1000.0 * n0) / m_cp if m_cp > 0 else 0.0
    t_adiabatic = t_start + adiabatic_rise

    if first:
        t_char = 1.0 / k if k > 0 else np.inf
    elif second:
        t_char = 1.0 / (k * c0) if (k > 0 and c0 > 0) else np.inf
    else:
        t_char = np.inf

    def _summary(peak_t, t_peak, t_complete, q_rxn_max, final_x) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {"Metric": "U (W/m2.K)", "Value": round(u, 2)},
                {"Metric": "UA (W/K)", "Value": round(u * area, 2)},
                {"Metric": "h_i (W/m2.K)", "Value": round(h_i, 2)},
                {"Metric": "h_o (W/m2.K)", "Value": round(h_o, 2)},
                {"Metric": "A_ht (m2)", "Value": round(area, 4)},
                {"Metric": "P_agitator (W)", "Value": round(p_agit, 2)},
                {"Metric": "Adiabatic dT (C)", "Value": round(adiabatic_rise, 2)},
                {"Metric": "Adiabatic T (C)", "Value": round(t_adiabatic, 2)},
                {"Metric": "Peak T (C)", "Value": round(peak_t, 2)},
                {"Metric": "Time to peak T (min)", "Value": round(t_peak / 60.0, 2)},
                {"Metric": "Max Q_rxn (W)", "Value": round(q_rxn_max, 1)},
                {"Metric": "Time to 99% conversion (min)",
                 "Value": np.inf if not np.isfinite(t_complete) else round(t_complete / 60.0, 2)},
                {"Metric": "Final conversion (%)", "Value": round(final_x * 100.0, 1)},
            ]
        )

    if not np.isfinite(t_char) or t_char <= 0 or m_cp <= 0 or c0 <= 0:
        empty_t = np.array([0.0])
        return ReactionResult(
            re, pr, nu, h_i, h_o, u, area, p_agit,
            empty_t, np.array([t_start]), np.array([0.0]), np.array([0.0]), np.array([0.0]),
            np.inf, t_start, 0.0, t_adiabatic, 0.0, 0.0,
            _summary(t_start, 0.0, np.inf, 0.0, 0.0),
        )

    # Integrate to ~99.5% conversion so the 99% completion check fires with
    # margin (first order needs ~5.3/k; second order ~199/(k*C0)).
    if first:
        t_span = -np.log(1.0 - 0.995) / k
    else:
        t_span = 0.995 / (0.005 * k * c0)
    t_max = min(max(t_span, 60.0), 86400.0)
    steps = 5000
    dt = t_max / steps
    t_arr = np.zeros(steps + 1)
    T = np.zeros(steps + 1)
    C = np.zeros(steps + 1)
    q_rxn = np.zeros(steps + 1)
    q_jac = np.zeros(steps + 1)
    T[0] = t_start
    C[0] = c0
    q_rxn[0] = -dh_kj * 1000.0 * ((k * c0 if first else k * c0 * c0) * v_l)
    q_jac[0] = u * area * (t_jacket - t_start)

    c_complete = 0.01 * c0  # 99% conversion
    end = steps
    for i in range(1, steps + 1):
        c_prev = max(C[i - 1], 0.0)
        t_prev = T[i - 1]
        rc = k * c_prev if first else k * c_prev * c_prev       # mol/(L.s)
        r_mol_s = rc * v_l                                       # mol/s
        qr = -dh_kj * 1000.0 * r_mol_s                          # W (+ exothermic)
        qj = u * area * (t_jacket - t_prev)                     # W
        C[i] = max(c_prev - rc * dt, 0.0)
        T[i] = t_prev + (qr + qj + p_agit) / m_cp * dt
        q_rxn[i] = qr
        q_jac[i] = qj
        t_arr[i] = i * dt
        if C[i] <= c_complete:
            end = i
            break

    sl = slice(0, end + 1)
    t_arr, T, C, q_rxn, q_jac = t_arr[sl], T[sl], C[sl], q_rxn[sl], q_jac[sl]
    conversion = 1.0 - C / c0
    final_x = float(conversion[-1])
    t_complete = float(t_arr[-1]) if final_x >= 0.99 else np.inf
    peak_idx = int(np.argmax(T))
    t_peak_c = float(T[peak_idx])
    t_peak_s = float(t_arr[peak_idx])
    q_rxn_max = float(np.max(np.abs(q_rxn)))

    return ReactionResult(
        re, pr, nu, h_i, h_o, u, area, p_agit,
        t_arr, T, conversion, q_rxn, q_jac,
        t_complete, t_peak_c, t_peak_s, t_adiabatic, q_rxn_max, final_x,
        _summary(t_peak_c, t_peak_s, t_complete, q_rxn_max, final_x),
    )


def adiabatic_rise(rho: float, cp: float, c0_mol_L: float, dH_kJ: float) -> float:
    """Signed adiabatic temperature rise (K); exothermic (dH < 0) is positive. Volume cancels."""
    if rho <= 0 or cp <= 0:
        return 0.0
    return (-dH_kJ * 1000.0 * c0_mol_L * 1000.0) / (rho * cp)


def heat_cool_setup_error(t_start: float, t_target: float, t_jacket: float) -> str | None:
    """Reason a heat/cool run cannot reach its target, or None when the setup is valid."""
    if t_target < t_start and t_jacket >= t_start:
        return "Invalid cooling setup: jacket temperature must be below start temperature."
    if t_target > t_start and t_jacket <= t_start:
        return "Invalid heating setup: jacket temperature must be above start temperature."
    if t_target < t_start and t_target < t_jacket:
        return "Cooling target is below jacket temperature and is unreachable."
    if t_target > t_start and t_target > t_jacket:
        return "Heating target is above jacket temperature and is unreachable."
    return None


# Display label -> compute_batch input key of each sweepable U/UA input.
SWEEP_PARAMETERS = {
    "Stir speed (rpm)": "n_rpm",
    "Liquid volume (L)": "v_l",
    "Impeller diameter (m)": "d_imp",
    "Tank diameter (m)": "d_tank",
    "Fluid density (kg/m3)": "rho",
    "Fluid viscosity (Pa.s)": "mu",
    "Fluid Cp (J/kg.K)": "cp",
    "Fluid conductivity (W/m.K)": "k_fluid",
    "Jacket velocity (m/s)": "v_jacket",
    "Jacket hydraulic diameter (m)": "d_hyd_jacket",
    "Wall conductivity (W/m.K)": "wall_k",
    "Wall thickness (mm)": "wall_thickness_mm",
    "Lining conductivity (W/m.K)": "lining_k",
    "Lining thickness (mm)": "lining_thickness_mm",
    "Fouling resistance (m2.K/W)": "fouling",
    "Wall-side viscosity (Pa.s)": "mu_wall",
}

# Upper sweep bound per input when neither a DB range nor a current value exists.
SWEEP_ZERO_VALUE_MAX = {
    "d_imp": 1.0, "d_tank": 2.0, "rho": 2000.0, "mu": 0.1,
    "cp": 10000.0, "k_fluid": 2.0, "v_jacket": 2.0,
    "d_hyd_jacket": 0.1, "wall_k": 100.0, "wall_thickness_mm": 10.0,
    "lining_k": 2.0, "lining_thickness_mm": 3.0, "fouling": 0.001,
    "mu_wall": 0.01,
}


def sweep_range_defaults(row: pd.Series, key: str, current_value: float) -> tuple[float, float]:
    """Reactor operating bounds for speed/volume, else ±50% around the current value."""
    bounds = {"n_rpm": ("N_rpm_min", "N_rpm_max"), "v_l": ("V_L_min", "V_L_max")}.get(key)
    if bounds:
        lower = safe_float(row.get(bounds[0]), 0.0)
        upper = safe_float(row.get(bounds[1]), 0.0)
        if upper > lower >= 0:
            return lower, upper
    current = safe_float(current_value, 0.0)
    if current > 0:
        return current * 0.5, current * 1.5
    return 0.0, SWEEP_ZERO_VALUE_MAX.get(key, 1.0)


def resistance_items(h_i: float, h_o: float, wall_k: float, wall_thickness_mm: float,
                     lining_k: float, lining_thickness_mm: float,
                     fouling: float) -> list[tuple[str, float]]:
    """Series thermal resistances (name, R in m²·K/W) between batch and jacket."""
    items: list[tuple[str, float]] = []
    if h_i > 0:
        items.append(("Inside film (process)", 1.0 / h_i))
    if wall_k > 0 and wall_thickness_mm > 0:
        items.append(("Wall", (wall_thickness_mm / 1000.0) / wall_k))
    if lining_k > 0 and lining_thickness_mm > 0:
        items.append(("Lining", (lining_thickness_mm / 1000.0) / lining_k))
    if fouling > 0:
        items.append(("Fouling", fouling))
    if h_o > 0:
        items.append(("Outside film (jacket)", 1.0 / h_o))
    return items


def resistance_breakdown(items: list[tuple[str, float]]) -> list[tuple[str, float, float]]:
    """(name, R, % of the total series resistance) for each resistance."""
    r_total = sum(r for _, r in items) or 1.0
    return [(name, r, r / r_total * 100.0) for name, r in items]


def time_factor(unit: str) -> float:
    """Seconds per display time unit ("Seconds" | "Minutes" | "Hours")."""
    return {"Seconds": 1.0, "Minutes": 60.0, "Hours": 3600.0}.get(unit, 60.0)


def round_sig(value: float, digits: int = 4) -> float:
    if value == 0 or not np.isfinite(value):
        return value
    return round(value, -int(np.floor(np.log10(abs(value)))) + digits - 1)


def reactor_jacket_area(row: pd.Series, d_tank: float, v_l: float) -> float:
    """Wetted jacket area (m², 4 significant figures) of a reactor at a fill volume (L)."""
    h_max = safe_float(row.get("H_max_m"), safe_float(row.get("H_m"), 0.2))
    dish = str(row.get("bottom_dish", ""))
    dish_height = bottom_dish_height(row)
    h = liquid_height_from_volume(v_l, d_tank, h_max, dish, dish_height)
    return round_sig(estimate_jacket_area(d_tank, h, dish, dish_height))


def ua_sweep_series(base: dict[str, Any], htm_db: dict[str, dict[str, Any]], row: pd.Series,
                    a_ht: float, n_pts: int = 40) -> dict[str, np.ndarray | list[float]]:
    """UA vs stir speed (area fixed) and UA vs fill volume (U fixed) around the
    operating point in ``base``; ranges come from the reactor row when recorded."""
    cur_rpm = max(base["n_rpm"], 1.0)
    rmin, rmax = safe_float(row.get("N_rpm_min"), 0.0), safe_float(row.get("N_rpm_max"), 0.0)
    if not (rmax > rmin > 0):
        rmin, rmax = max(1.0, 0.1 * cur_rpm), 2.0 * cur_rpm
    rpm = np.linspace(rmin, rmax, n_pts)

    cur_vol = max(base["v_l"], 1e-6)
    vmin, vmax = safe_float(row.get("V_L_min"), 0.0), safe_float(row.get("V_L_max"), 0.0)
    if not (vmax > vmin > 0):
        vmin, vmax = 0.1 * cur_vol, 2.0 * cur_vol
    vol = np.linspace(max(vmin, 1e-6), vmax, n_pts)
    h_max = safe_float(row.get("H_max_m"), safe_float(row.get("L_tan_tan_m"), 0.2))
    return {
        "rpm": rpm, "ua_rpm": ua_vs_rpm(base, htm_db, a_ht, rpm),
        "volume": vol, "ua_volume": ua_vs_volume(base, htm_db, h_max, str(row.get("bottom_dish", "")),
                                                 bottom_dish_height(row), vol),
    }


def jacket_area_at(v_l: float, d_tank: float, h_max: float, bottom_dish: str,
                   dish_height: float) -> float:
    """Wetted jacket area (m²) at a fill volume (L)."""
    h_liq = liquid_height_from_volume(v_l, d_tank, h_max, bottom_dish, dish_height)
    return estimate_jacket_area(d_tank, h_liq, bottom_dish, dish_height)


def ua_vs_rpm(base: dict[str, Any], htm_db: dict[str, dict[str, Any]], a_ht: float,
              rpm_values) -> list[float]:
    """UA (W/K) across stir speeds with the heat-transfer area held fixed."""
    return [_heat_transfer_coeffs({**base, "n_rpm": rpm}, htm_db)["u"] * a_ht
            for rpm in rpm_values]


def ua_vs_volume(base: dict[str, Any], htm_db: dict[str, dict[str, Any]], h_max: float,
                 bottom_dish: str, dish_height: float, vol_values) -> list[float]:
    """UA (W/K) across fill volumes at fixed stir speed (U is volume-independent)."""
    u_fixed = _heat_transfer_coeffs(base, htm_db)["u"]
    d_tank = safe_float(base["d_tank"])
    return [u_fixed * jacket_area_at(vol, d_tank, h_max, bottom_dish, dish_height)
            for vol in vol_values]


def u_ua_surface(base: dict[str, Any], htm_db: dict[str, dict[str, Any]],
                 x_key: str, x_values, y_key: str, y_values, a_ht: float,
                 h_max: float, bottom_dish: str, dish_height: float) -> tuple[np.ndarray, np.ndarray]:
    """U and UA grids over two swept inputs; rows follow ``y_values``, columns ``x_values``.

    The jacket area is recomputed only when volume or tank diameter is swept.
    """
    u_values = np.empty((len(y_values), len(x_values)))
    ua_values = np.empty_like(u_values)
    area_varies = "v_l" in (x_key, y_key) or "d_tank" in (x_key, y_key)
    for iy, y_value in enumerate(y_values):
        for ix, x_value in enumerate(x_values):
            point = {**base, x_key: float(x_value), y_key: float(y_value)}
            u_value = _heat_transfer_coeffs(point, htm_db)["u"]
            area = (jacket_area_at(point["v_l"], point["d_tank"], h_max, bottom_dish, dish_height)
                    if area_varies else a_ht)
            u_values[iy, ix] = u_value
            ua_values[iy, ix] = u_value * area
    return u_values, ua_values


def surface_color_limits(values: np.ndarray) -> tuple[float, float]:
    """(min, max) of a surface, padded when flat so a colour scale stays valid."""
    lower = float(np.nanmin(values))
    upper = float(np.nanmax(values))
    if np.isclose(lower, upper):
        padding = max(abs(lower) * 0.01, 1e-6)
        lower -= padding
        upper += padding
    return lower, upper
