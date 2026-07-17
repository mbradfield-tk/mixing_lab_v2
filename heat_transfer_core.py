from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

NUSSELT_CORRELATIONS: dict[str, dict[str, float | str]] = {
    "DIN 28131 (standard)": {"C": 0.36, "a": 2.0 / 3.0, "b": 1.0 / 3.0, "c": 0.14},
    "Chilton–Drew–Jebens": {"C": 0.36, "a": 2.0 / 3.0, "b": 1.0 / 3.0, "c": 0.14},
    "Lehrer (anchor/helical)": {"C": 0.54, "a": 2.0 / 3.0, "b": 1.0 / 3.0, "c": 0.14},
    "Stein–Schmidt (high Re)": {"C": 0.50, "a": 2.0 / 3.0, "b": 1.0 / 3.0, "c": 0.14},
    "Brooks–Su (Retreat Blade)": {"C": 0.33, "a": 2.0 / 3.0, "b": 1.0 / 3.0, "c": 0.14},
    "Nagata (paddle)": {"C": 0.36, "a": 2.0 / 3.0, "b": 1.0 / 3.0, "c": 0.18},
}

WALL_CONDUCTIVITY: dict[str, float] = {
    "stainless steel": 16.0,
    "stainless": 16.0,
    "ss316": 16.0,
    "ss304": 16.0,
    "hastelloy": 12.0,
    "hastelloy c-276": 12.0,
    "inconel": 15.0,
    "carbon steel": 50.0,
    "glass": 1.0,
    "glass-lined": 1.0,
    "titanium": 22.0,
    "copper": 385.0,
}

LINING_CONDUCTIVITY: dict[str, float] = {
    "glass": 1.0,
    "glass-lined": 1.0,
    "ptfe": 0.25,
    "teflon": 0.25,
    "pfa": 0.25,
    "pvdf": 0.19,
    "rubber": 0.16,
    "epoxy": 0.20,
    "titanium": 22.0,
    "hastelloy": 12.0,
    "tantalum": 57.0,
}

LINING_THICKNESS_DEFAULT: dict[str, float] = {
    "glass": 0.0015,
    "glass-lined": 0.0015,
    "ptfe": 0.002,
    "teflon": 0.002,
    "pfa": 0.002,
    "pvdf": 0.003,
    "rubber": 0.006,
    "epoxy": 0.003,
    "titanium": 0.002,
    "hastelloy": 0.002,
    "tantalum": 0.001,
}

JACKET_HTC_DEFAULT = 1500.0
FOULING_DEFAULT = 0.0002


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


def estimate_jacket_area(D_tank: float, H: float, bottom_dish: str = "") -> float:
    if D_tank <= 0 or H <= 0:
        return 0.0
    A_flat = np.pi / 4 * D_tank**2
    dish = (bottom_dish or "").lower()
    if "ellip" in dish:
        h_dish = D_tank / 4
        A_dish_full = 1.09 * A_flat
    elif "torisph" in dish or "din" in dish:
        h_dish = 0.1935 * D_tank
        A_dish_full = 1.06 * A_flat
    elif "conic" in dish:
        h_dish = D_tank / 2
        A_dish_full = 1.20 * A_flat
    else:
        h_dish = 0.0
        A_dish_full = A_flat
    if h_dish > 0 and H < h_dish:
        return (H / h_dish) * A_dish_full
    return A_dish_full + np.pi * D_tank * max(H - h_dish, 0.0)


def liquid_height_from_volume(V_L: float, D_tank: float, H_max: float) -> float:
    if V_L <= 0 or D_tank <= 0:
        return 0.0
    V_m3 = V_L / 1000.0
    H = V_m3 / (np.pi * (D_tank / 2) ** 2)
    return min(H, H_max) if H_max > 0 else H


def impeller_power(Np: float, rho: float, N_rps: float, D_imp: float) -> float:
    if Np <= 0 or rho <= 0 or N_rps <= 0 or D_imp <= 0:
        return 0.0
    return Np * rho * (N_rps**3) * (D_imp**5)


def nusselt_jacket(Re: float, Pr: float, mu_ratio: float, correlation: str) -> float:
    corr = NUSSELT_CORRELATIONS.get(correlation, NUSSELT_CORRELATIONS["DIN 28131 (standard)"])
    c = float(corr["C"])
    a = float(corr["a"])
    b = float(corr["b"])
    m = float(corr["c"])
    if Re <= 0 or Pr <= 0:
        return 0.0
    return c * Re**a * Pr**b * (mu_ratio if mu_ratio > 0 else 1.0) ** m


def estimate_U_from_resistances(
    h_i: float,
    h_o: float,
    wall_k: float,
    wall_thickness_m: float,
    lining_k: float,
    lining_thickness_m: float,
    fouling: float,
) -> float:
    if h_i <= 0 or h_o <= 0:
        return 0.0
    r_total = (1.0 / h_i) + (1.0 / h_o) + max(fouling, 0.0)
    if wall_k > 0 and wall_thickness_m > 0:
        r_total += wall_thickness_m / wall_k
    if lining_k > 0 and lining_thickness_m > 0:
        r_total += lining_thickness_m / lining_k
    return 1.0 / r_total if r_total > 0 else 0.0


def jacket_side_htc(htm: dict[str, Any], v_jacket: float, d_hyd: float) -> float:
    if "h_jacket_override" in htm:
        return safe_float(htm["h_jacket_override"], JACKET_HTC_DEFAULT)
    rho_j = safe_float(htm.get("rho_kg_m3"))
    mu_j = safe_float(htm.get("mu_Pa_s"))
    cp_j = safe_float(htm.get("Cp_J_kgK"))
    k_j = safe_float(htm.get("k_W_mK"))
    if rho_j <= 0 or mu_j <= 0 or cp_j <= 0 or k_j <= 0 or v_jacket <= 0 or d_hyd <= 0:
        return JACKET_HTC_DEFAULT
    re_j = rho_j * v_jacket * d_hyd / mu_j
    pr_j = cp_j * mu_j / k_j
    if re_j < 2300:
        nu_j = 3.66 + 0.065 * d_hyd * re_j * pr_j / (1.0 + 0.04 * (d_hyd * re_j * pr_j) ** (2.0 / 3.0))
    else:
        nu_j = 0.023 * re_j**0.8 * pr_j**0.4
    return nu_j * k_j / d_hyd


def time_to_cool_or_heat(
    rho: float, V_L_m3: float, cp: float, U: float, area: float, t_start: float, t_end: float, t_jacket: float
) -> float:
    if rho <= 0 or V_L_m3 <= 0 or cp <= 0 or U <= 0 or area <= 0:
        return np.inf
    dt_start = t_start - t_jacket
    dt_end = t_end - t_jacket
    if dt_start == 0 or dt_end == 0:
        return np.inf
    ratio = dt_start / dt_end
    if ratio <= 0 or ratio <= 1:
        return np.inf
    return (rho * V_L_m3 * cp) / (U * area) * np.log(ratio)


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
            Tj_out[i] = t_jacket_in + q_jacket / (m_dot_jacket * cp_jacket)
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
    dt_dt = ((q_max - p_agitator_w) / (rho * v_l_m3 * cp) * 60.0) if rho > 0 and v_l_m3 > 0 and cp > 0 else 0.0
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
