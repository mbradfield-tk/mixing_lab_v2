from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from core.records import bottom_dish_height

# Process-side Nusselt correlations for jacketed agitated vessels:
#   Nu = C * Re^a * Pr^b * (mu/mu_wall)^c
# Each entry carries a `ref` so the constants can be audited by hand. Entries
# flagged UNVERIFIED were inherited from the original tool and could not be traced
# to a primary source in the 2026-09 review; confirm before relying on them.
NUSSELT_CORRELATIONS: dict[str, dict[str, float | str]] = {
    "Chilton–Drew–Jebens (paddle)": {
        "C": 0.36, "a": 2.0 / 3.0, "b": 1.0 / 3.0, "c": 0.14,
        "ref": "Chilton, Drew & Jebens (1944), Ind. Eng. Chem. 36(6):510. "
               "Jacketed vessel, paddle impeller, turbulent (Re > 400).",
    },
    "Flat-blade turbine (baffled)": {
        "C": 0.74, "a": 2.0 / 3.0, "b": 1.0 / 3.0, "c": 0.14,
        "ref": "Uhl & Gray, Mixing: Theory and Practice Vol. 1 (1966); Perry's "
               "Chemical Engineers' Handbook 9th ed., Sec. 11. Baffled vessel with "
               "a flat-blade (Rushton) turbine, turbulent regime.",
    },
    "Brooks–Su (retreat blade, glass-lined)": {
        "C": 0.33, "a": 2.0 / 3.0, "b": 1.0 / 3.0, "c": 0.14,
        "ref": "Brooks & Su (1959), Chem. Eng. Prog. 55(10):54. Retreat-curve blade "
               "impeller in a glass-lined vessel.",
    },
    "DIN 28131 (standard)": {
        "C": 0.36, "a": 2.0 / 3.0, "b": 1.0 / 3.0, "c": 0.14,
        "ref": "DIN 28131:1979. UNVERIFIED — constants are identical to "
               "Chilton–Drew–Jebens; confirm against the standard.",
    },
    "Lehrer (anchor/helical)": {
        "C": 0.54, "a": 2.0 / 3.0, "b": 1.0 / 3.0, "c": 0.14,
        "ref": "Lehrer (1970), Chem. Eng. Sci. 25:1397. UNVERIFIED — Lehrer's "
               "published form is not a simple power law; confirm C/a/b/c.",
    },
    "Stein–Schmidt (high Re)": {
        "C": 0.50, "a": 2.0 / 3.0, "b": 1.0 / 3.0, "c": 0.14,
        "ref": "Stein & Schmidt (1993), Chem. Eng. Process. 32:305. UNVERIFIED — "
               "constants not traced to the paper.",
    },
    "Nagata (paddle)": {
        "C": 0.36, "a": 2.0 / 3.0, "b": 1.0 / 3.0, "c": 0.18,
        "ref": "Nagata (1975), Mixing: Principles and Applications. UNVERIFIED — "
               "viscosity exponent 0.18 not traced to the source.",
    },
}

# Thermal conductivity at ~20-25 C. Alloy conductivity varies with grade, temper
# and temperature, so check the cited source or a mill certificate for critical duty.
WALL_CONDUCTIVITY: dict[str, float] = {
    "stainless steel": 15.0,
    "stainless": 15.0,
    "ss316": 13.4,
    "ss304": 14.4,
    "hastelloy": 12.0,
    "hastelloy c-276": 12.0,
    "inconel": 15.0,
    "incoloy": 12.0,
    "monel": 26.0,
    "nickel": 61.0,
    "carbon steel": 50.0,
    "glass": 1.2,
    "glass-lined": 1.2,
    "titanium": 22.0,
    "zirconium": 23.0,
    "tantalum": 57.0,
    "copper": 390.0,
}

WALL_CONDUCTIVITY_REF: dict[str, str] = {
    "stainless steel": "Generic austenitic grade; midpoint of 304/316 (13-16 W/m.K). "
                       "Engineering ToolBox, Thermal Conductivity of Metals and Alloys.",
    "ss316": "316/316L at 20-100 C. ASM Handbook Vol. 1; confirm per mill certificate.",
    "ss304": "Type 304 at 20 C. Engineering ToolBox, Thermal Conductivity of Metals and Alloys.",
    "hastelloy": "Hastelloy C at 0-25 C. Engineering ToolBox. Haynes C-276 datasheets "
                 "quote ~10 W/m.K at 25 C — verify for critical duty.",
    "hastelloy c-276": "See 'hastelloy'.",
    "inconel": "Inconel (600) at 21-100 C. Engineering ToolBox. Inconel 625 is lower (~9.8 W/m.K).",
    "incoloy": "Incoloy at 0-100 C. Engineering ToolBox.",
    "monel": "Monel at 0-100 C. Engineering ToolBox.",
    "nickel": "Wrought nickel at 0-100 C, quoted range 61-90 W/m.K; lower bound used. "
              "Engineering ToolBox.",
    "carbon steel": "Plain carbon steel at 20 C, 43 (1% C) to 54 (0.5% C) W/m.K; 50 W/m.K "
                    "used as a mid-range design value. Engineering ToolBox.",
    "glass": "Borosilicate glass / glass-lining enamel, ~1.1-1.3 W/m.K. Harmonised with "
             "LINING_CONDUCTIVITY['glass'].",
    "glass-lined": "See 'glass'.",
    "titanium": "Titanium at 0 C, 22.4 W/m.K (Grade 2 ~21.9). Engineering ToolBox.",
    "zirconium": "Zirconium at 0 C, 23.2 W/m.K. Engineering ToolBox.",
    "tantalum": "Tantalum at 0 C, 57.4 W/m.K. Engineering ToolBox.",
    "copper": "Electrolytic (ETP) copper at 0-25 C. Engineering ToolBox.",
}

LINING_CONDUCTIVITY: dict[str, float] = {
    "glass": 1.2,
    "glass-lined": 1.2,
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

# Nominal as-applied lining thickness (m). Reactor-grade glass lining is
# typically 1.0-2.0 mm; confirm against the vessel datasheet.
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

LINING_CONDUCTIVITY_REF: dict[str, str] = {
    "glass": "Glass-lining enamel, 1.2 W/m.K (typical 1.1-1.3). De Dietrich / Pfaudler "
             "glass-lining technical data.",
    "glass-lined": "See 'glass'.",
    "ptfe": "PTFE. Engineering ToolBox, Plastics - Thermal Conductivity Coefficients.",
    "teflon": "See 'ptfe'.",
    "pfa": "PFA, quoted 0.19-0.25 W/m.K; upper bound used. Fluoropolymer vendor datasheets.",
    "pvdf": "PVDF. Fluoropolymer vendor datasheets.",
    "rubber": "Soft/natural rubber lining. Engineering ToolBox.",
    "epoxy": "Unfilled epoxy coating. Engineering ToolBox.",
    "titanium": "Metal clad lining — see WALL_CONDUCTIVITY_REF['titanium'].",
    "hastelloy": "Metal clad lining — see WALL_CONDUCTIVITY_REF['hastelloy'].",
    "tantalum": "Metal clad lining — see WALL_CONDUCTIVITY_REF['tantalum'].",
}

# Jacket-side film coefficient used when the medium has no computed value.
# 1500 W/(m2.K) is a conventional simple-jacket water/glycol value
# (Perry's Chemical Engineers' Handbook 9th ed., Sec. 11).
JACKET_HTC_DEFAULT = 1500.0
# Fouling resistance 2e-4 m2.K/W — typical clean process service (TEMA RGP-T-2.4).
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


def _parse_cone_angle_deg(dish_type: str, default: float = 45.0) -> float:
    """Cone wall angle from the horizontal (deg), parsed from a dish label."""
    s = str(dish_type).lower()
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:°|deg)", s)
    if m is None:
        m = re.search(r"(\d+(?:\.\d+)?)", s)
    if m is not None:
        ang = float(m.group(1))
        if 5.0 <= ang <= 85.0:
            return ang
    return default


def _cone_depth(D_tank: float, dish_type: str = "", default_angle_deg: float = 45.0) -> float:
    """Conical bottom depth (m) from the tank ID and its (parsed) cone angle."""
    if D_tank <= 0:
        return 0.0
    return (D_tank / 2.0) * np.tan(np.radians(_parse_cone_angle_deg(dish_type, default_angle_deg)))


def estimate_jacket_area(D_tank: float, H: float, bottom_dish: str = "",
                         bottom_dish_height_m: float | None = None) -> float:
    if D_tank <= 0 or H <= 0:
        return 0.0
    A_flat = np.pi / 4 * D_tank**2
    dish = (bottom_dish or "").lower()
    measured_height = float(bottom_dish_height_m or 0.0)
    if "ellip" in dish:
        h_dish = measured_height if measured_height > 0 else D_tank / 4
        A_dish_full = 1.084 * D_tank**2   # 2:1 semi-ellipsoidal head, exact spheroid area
    elif "torisph" in dish or "din" in dish:
        h_dish = measured_height if measured_height > 0 else 0.1935 * D_tank
        A_dish_full = 0.99 * D_tank**2    # Klöpper head (DIN 28011) surface area
    elif "conic" in dish:
        h_dish = measured_height if measured_height > 0 else _cone_depth(D_tank, dish)
        r = D_tank / 2.0
        A_dish_full = A_flat * np.sqrt(1.0 + (h_dish / r) ** 2) if r > 0 else A_flat
    else:
        h_dish = measured_height
        A_dish_full = A_flat
    if h_dish > 0 and H < h_dish:
        return (H / h_dish) * A_dish_full
    return A_dish_full + np.pi * D_tank * max(H - h_dish, 0.0)


def liquid_height_from_volume(V_L: float, D_tank: float, H_max: float,
                              bottom_dish: str = "",
                              bottom_dish_height_m: float | None = None) -> float:
    """Liquid height (m) from fill volume — delegates to the shared dish-aware
    geometry in :mod:`utils.calculations.geometry` so every page agrees."""
    from utils.calculations.geometry import liquid_height_from_volume as _shared

    return _shared(V_L, D_tank, H_max, bottom_dish, bottom_dish_height_m)


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
