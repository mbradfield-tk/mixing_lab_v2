"""Heat generation, heat transfer, and batch temperature simulation.

UNIT CONVENTION
---------------
Reaction: delta_H in kJ/mol, k in 1/s (1st order) or L/(mol.s) (2nd order),
C0 in mol/L, V_L in litres -> reaction_rate_mol_per_s returns mol/s and
heat_generation_rate returns W.  Heat transfer: U in W/(m^2.K), A in m^2,
h in W/(m^2.K), k_fluid in W/(m.K), Cp in J/(kg.K); batch energy balances use
V_L in m^3 (V_L_m3).  N_rps is in rev/s.

REFERENCES (per function / table)
---------------------------------
None of the heat-transfer correlations below appear in the context source
(Myerson 2019); canonical references are given but MUST be verified.

    reaction_rate_mol_per_s, heat_generation_rate (Q = |dH| r)
        First-principles kinetics + energy balance.  [definition]
    estimate_jacket_area (dished-head area factors)
        Ref: DIN 28011 / ASME F&D head geometry.  [NOT in context/ - verify]
    estimate_U (material-based band)
        Heuristic U ranges by wall/lining material.  [SOURCE MISSING - heuristic]
    estimate_U_detailed, process_side_htc, _compute_hi, nusselt_jacket,
    NUSSELT_CORRELATIONS table
        Jacketed-vessel process-side Nu = C Re^(2/3) Pr^(1/3) (mu/mu_w)^0.14.
        Refs (also in the table 'ref' keys): DIN 28131:1979; Chilton, Drew &
        Jebens (1944), Ind. Eng. Chem. 36, 510; Lehrer (1970); Nagata (1975);
        Brooks & Su (1959); Stein & Schmidt (1993).  [NOT in context/ - verify]
    jacket_side_htc (laminar Hausen; turbulent Dittus-Boelter 0.023 Re^0.8 Pr^0.4)
        Ref: Dittus & Boelter (1930); Hausen (1943).  [NOT in context/ - verify]
    estimate_U_from_resistances, heat_removal_capacity, cooling_rate,
    time_to_cool_or_heat (log-mean), batch_temperature_profile[_tdep],
    batch_temp_profile_variable_jacket[_tdep]
        Series-resistance / lumped-capacitance energy balances.
        Ref: standard process heat-transfer texts (e.g. Coulson & Richardson
        vol. 1; Perry's Handbook).  [NOT in context/ - verify]
    WALL_CONDUCTIVITY, LINING_CONDUCTIVITY, *_THICKNESS, JACKET_HTC, FOULING
        Tabulated material/typical values.  [SOURCE MISSING - verify against
        material datasheets / Perry's]
"""

import re as _re
import warnings as _warnings

import numpy as np
import pandas as pd
from scipy.integrate import solve_ivp
import pathlib as _pathlib


# ---------------------------------------------------------------------------
# Reaction heat generation
# ---------------------------------------------------------------------------

def reaction_rate_mol_per_s(order: str, k: float, C0: float,
                            V_L: float) -> float:
    """Instantaneous molar reaction rate (mol/s) at initial concentration."""
    if k <= 0 or C0 <= 0 or V_L <= 0:
        return 0.0
    if order in ("1", "pseudo-1"):
        r = k * C0
    elif order in ("2", "pseudo-2"):
        r = k * C0**2
    else:
        return 0.0
    return r * V_L


def heat_generation_rate(delta_H_kJ_mol: float, r_mol_per_s: float) -> float:
    """Rate of heat generation (W) from reaction.  Q_rxn = |ΔH_rxn| × r"""
    return abs(delta_H_kJ_mol) * 1000.0 * r_mol_per_s


# ---------------------------------------------------------------------------
# Jacket area estimation
# ---------------------------------------------------------------------------

def estimate_jacket_area(D_tank: float, H: float,
                         bottom_dish: str = "") -> float:
    """Estimate jacketed heat-transfer area (m²) wetted by the liquid."""
    if D_tank <= 0 or H <= 0:
        return 0.0

    A_flat = np.pi / 4 * D_tank**2
    dish = str(bottom_dish).lower() if bottom_dish else ""

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
        frac = H / h_dish
        return frac * A_dish_full
    else:
        H_cyl = H - h_dish
        A_cyl = np.pi * D_tank * H_cyl
        return A_dish_full + A_cyl


# ---------------------------------------------------------------------------
# Simple U estimation
# ---------------------------------------------------------------------------

def estimate_U(material: str = "", N_rps: float = 0.0,
               lining_material: str = "") -> float:
    """Estimate overall heat-transfer coefficient U (W/m²·K) from material."""
    mat = str(material).lower() if material else ""
    lining = str(lining_material).lower() if lining_material else ""
    if "glass" in lining or "glass" in mat:
        U_lo, U_hi = 100.0, 250.0
    elif "hastel" in mat:
        U_lo, U_hi = 200.0, 450.0
    elif "carbon" in mat:
        U_lo, U_hi = 150.0, 350.0
    else:
        U_lo, U_hi = 200.0, 500.0
    frac = min(N_rps / 3.0, 1.0) if N_rps > 0 else 0.5
    return U_lo + frac * (U_hi - U_lo)


# ---------------------------------------------------------------------------
# Material property lookup tables
# ---------------------------------------------------------------------------

WALL_CONDUCTIVITY: dict[str, float] = {
    "stainless steel": 16.0, "stainless": 16.0,
    "ss316": 16.0, "ss304": 16.0,
    "hastelloy": 12.0, "hastelloy c-276": 12.0,
    "inconel": 15.0, "carbon steel": 50.0,
    "glass": 1.0, "glass-lined": 1.0,
    "titanium": 22.0, "copper": 385.0,
}

LINING_CONDUCTIVITY: dict[str, float] = {
    "glass": 1.0, "glass-lined": 1.0,
    "ptfe": 0.25, "teflon": 0.25, "pfa": 0.25,
    "pvdf": 0.19, "rubber": 0.16, "epoxy": 0.20,
    "titanium": 22.0, "hastelloy": 12.0, "tantalum": 57.0,
}

LINING_THICKNESS_DEFAULT: dict[str, float] = {
    "glass": 0.0015, "glass-lined": 0.0015,
    "ptfe": 0.002, "teflon": 0.002, "pfa": 0.002,
    "pvdf": 0.003, "rubber": 0.006, "epoxy": 0.003,
    "titanium": 0.002, "hastelloy": 0.002, "tantalum": 0.001,
}

SOLVENT_THERMAL: dict[str, tuple[float, float]] = {
    "water":           (0.607, 4182.0),
    "methanol":        (0.200, 2530.0),
    "ethanol":         (0.167, 2440.0),
    "ipa":             (0.135, 2600.0),
    "isopropanol":     (0.135, 2600.0),
    "thf":             (0.120, 1720.0),
    "tetrahydrofuran": (0.120, 1720.0),
    "dcm":             (0.130, 1190.0),
    "dichloromethane": (0.130, 1190.0),
    "toluene":         (0.131, 1690.0),
    "dmf":             (0.184, 2060.0),
    "dimethylformamide": (0.184, 2060.0),
    "dmso":            (0.200, 1960.0),
    "acetonitrile":    (0.188, 2230.0),
    "heptane":         (0.124, 2240.0),
    "ethyl acetate":   (0.151, 1930.0),
    "mek":             (0.145, 2140.0),
    "acetone":         (0.161, 2160.0),
    "glycerol":        (0.285, 2430.0),
    "corn syrup":      (0.400, 3000.0),
}

JACKET_HTC: dict[str, float] = {
    "simple jacket":   1500.0,
    "half-pipe coil":  2500.0,
    "dimple jacket":   1200.0,
}
JACKET_HTC_DEFAULT = 1500.0
FOULING_DEFAULT = 0.0002


# ---------------------------------------------------------------------------
# Lookup helpers
# ---------------------------------------------------------------------------

def _lookup_wall_k(material: str) -> float | None:
    mat = str(material).lower().strip() if material else ""
    for key, k in WALL_CONDUCTIVITY.items():
        if key in mat or mat in key:
            return k
    return None


def _lookup_lining_k(lining_material: str) -> tuple[float, float] | None:
    mat = str(lining_material).lower().strip() if lining_material else ""
    if not mat:
        return None
    for key in LINING_CONDUCTIVITY:
        if key in mat or mat in key:
            k = LINING_CONDUCTIVITY[key]
            t = LINING_THICKNESS_DEFAULT.get(key, 0.002)
            return k, t
    return None


def _lookup_solvent_thermal(fluid_name: str) -> tuple[float, float] | None:
    """Return (k_fluid, Cp) for a fluid name.

    Tries ``solvent_properties.get_properties()`` first (authoritative,
    temperature-dependent source).  Falls back to the legacy
    ``SOLVENT_THERMAL`` dict for solvents not in the database.
    """
    from utils.solvent_properties import get_properties as _sp_get, list_solvents as _sp_list

    name = str(fluid_name).strip()
    base = _re.sub(r"\s*\(.*?\)\s*$", "", name).strip().lower()

    # Try solvent_properties (canonical source)
    for sname in _sp_list():
        if sname.lower() == base or base in sname.lower():
            try:
                props = _sp_get(sname, T_C=25.0)
                return (props["k_W_per_mK"], props["Cp_J_per_kgK"])
            except Exception:
                break

    # Fallback to legacy dict
    if base in SOLVENT_THERMAL:
        return SOLVENT_THERMAL[base]
    for key in SOLVENT_THERMAL:
        if key in base:
            return SOLVENT_THERMAL[key]
    return None


# ---------------------------------------------------------------------------
# Detailed U estimation
# ---------------------------------------------------------------------------

def estimate_U_detailed(
    *, N_rps: float, D_imp: float, D_tank: float,
    rho: float, mu: float,
    material: str = "", lining_material: str = "",
    wall_thickness_mm: float = 0.0,
    fluid_name: str = "", Cp: float = 0.0, k_fluid: float = 0.0,
    jacket_htc: float = 0.0, fouling: float = FOULING_DEFAULT,
) -> tuple[float, list[str]]:
    """Estimate U via individual resistances with Nusselt correlations."""
    warnings: list[str] = []

    if Cp <= 0 or k_fluid <= 0:
        lookup = _lookup_solvent_thermal(fluid_name)
        if lookup is not None:
            if k_fluid <= 0:
                k_fluid = lookup[0]
            if Cp <= 0:
                Cp = lookup[1]
        else:
            if k_fluid <= 0:
                k_fluid = 0.607
                warnings.append("k_fluid: using water default (0.61 W/m·K)")
            if Cp <= 0:
                Cp = 4182.0
                warnings.append("Cp: using water default (4182 J/kg·K)")

    can_nusselt = (N_rps > 0 and D_imp > 0 and D_tank > 0
                   and rho > 0 and mu > 0 and Cp > 0 and k_fluid > 0)

    if not can_nusselt:
        warnings.append("Insufficient data for Nusselt correlation – "
                        "using simple material-based estimate")
        return estimate_U(material, N_rps, lining_material=lining_material), warnings

    Re = rho * N_rps * D_imp**2 / mu
    Pr = Cp * mu / k_fluid
    C_Nu = 0.36
    Nu = C_Nu * Re**(2.0/3.0) * Pr**(1.0/3.0)
    h_i = Nu * k_fluid / D_tank

    k_wall = _lookup_wall_k(material)
    wall_m = wall_thickness_mm / 1000.0 if wall_thickness_mm > 0 else 0.0

    R_wall = 0.0
    if k_wall is not None and wall_m > 0:
        R_wall = wall_m / k_wall
    elif k_wall is not None and wall_m == 0:
        warnings.append("Wall thickness unknown – wall resistance omitted")
    elif wall_m > 0:
        k_wall = 16.0
        R_wall = wall_m / k_wall
        warnings.append(f"Wall material unknown – assumed SS (k={k_wall} W/m·K)")
    else:
        warnings.append("Wall thickness and material unknown – wall resistance omitted")

    _lining_info = _lookup_lining_k(lining_material)
    if _lining_info is not None:
        _k_lining, _t_lining = _lining_info
        R_lining = _t_lining / _k_lining
        R_wall += R_lining
        _lining_label = str(lining_material).strip()
        warnings.append(
            f"Lining: {_lining_label} "
            f"(k={_k_lining} W/m·K, t={_t_lining*1000:.1f} mm)"
        )
        if wall_m == 0 and k_wall is None:
            R_wall += 0.010 / 16.0
            warnings.append(f"Shell unknown – assumed 10 mm SS behind {_lining_label} lining")

    h_o = jacket_htc if jacket_htc > 0 else JACKET_HTC_DEFAULT
    if jacket_htc <= 0:
        warnings.append(f"Jacket h_o: using typical value ({h_o:.0f} W/m²·K)")

    R_total = 1.0 / h_i + R_wall + 1.0 / h_o + fouling
    U = 1.0 / R_total

    return U, warnings


# ---------------------------------------------------------------------------
# Heat balance functions
# ---------------------------------------------------------------------------

def heat_removal_capacity(U: float, A: float, dT: float) -> float:
    """Q_cool = U × A × ΔT (W)."""
    if U <= 0 or A <= 0 or dT <= 0:
        return 0.0
    return U * A * dT


def heat_balance_assessment(Q_gen: float, Q_cool: float) -> str:
    """Qualitative assessment comparing heat generation to cooling capacity."""
    if Q_gen <= 0:
        return "No heat generation"
    if Q_cool <= 0:
        return "⚠️ No cooling capacity estimated"
    ratio = Q_gen / Q_cool
    if ratio < 0.25:
        return f"Easily manageable (Q_gen/Q_cool = {ratio:.2f})"
    elif ratio < 0.5:
        return f"Comfortable margin (Q_gen/Q_cool = {ratio:.2f})"
    elif ratio < 0.75:
        return f"Moderate – monitor closely (Q_gen/Q_cool = {ratio:.2f})"
    elif ratio < 1.0:
        return f"⚠️ Tight – limited safety margin (Q_gen/Q_cool = {ratio:.2f})"
    else:
        return f"🔴 Insufficient cooling (Q_gen/Q_cool = {ratio:.2f})"


def cooling_rate(Q_cool: float, P_agitator: float,
                 rho: float, V_L: float, Cp: float) -> float:
    """dT/dt = (Q_cool − P_agitator) / (ρ V Cp)."""
    if rho <= 0 or V_L <= 0 or Cp <= 0:
        return 0.0
    return (Q_cool - P_agitator) / (rho * V_L * Cp)


def time_to_cool_or_heat(rho: float, V_L: float, Cp: float,
                         U: float, A: float,
                         T_start: float, T_end: float,
                         T_jacket: float) -> float:
    """Logarithmic batch heating / cooling time."""
    if U <= 0 or A <= 0 or rho <= 0 or V_L <= 0 or Cp <= 0:
        return np.inf
    dT_start = T_start - T_jacket
    dT_end = T_end - T_jacket
    if dT_start == 0 or dT_end == 0:
        return np.inf
    ratio = dT_start / dT_end
    if ratio <= 0 or ratio <= 1:
        return np.inf
    return (rho * V_L * Cp) / (U * A) * np.log(ratio)


# ---------------------------------------------------------------------------
# HTM database
# ---------------------------------------------------------------------------

_HTM_CSV = _pathlib.Path(__file__).resolve().parent.parent.parent / "data" / "HTM.csv"


def load_htm_db(csv_path=_HTM_CSV) -> dict[str, dict]:
    """Load heat-transfer media from CSV.

    Resilient to a missing or malformed file: returns an empty dict if the
    file cannot be read, and skips (with a warning) any individual row that
    fails to parse, so a single bad cell never crashes the whole app.
    """
    db: dict[str, dict] = {}
    try:
        df = pd.read_csv(csv_path)
    except (FileNotFoundError, OSError, pd.errors.ParserError, pd.errors.EmptyDataError) as exc:
        _warnings.warn(f"Could not load HTM database from {csv_path}: {exc}")
        return db

    for _, row in df.iterrows():
        try:
            entry: dict = {
                "T_min_C": float(row["T_min_C"]),
                "T_max_C": float(row["T_max_C"]),
                "rho_kg_m3": float(row["rho_kg_m3"]),
                "Cp_J_kgK": float(row["Cp_J_kgK"]),
                "mu_Pa_s": float(row["mu_Pa_s"]),
                "k_W_mK": float(row["k_W_mK"]),
                "notes": str(row.get("notes", "")),
            }
            if pd.notna(row.get("h_jacket_override")):
                entry["h_jacket_override"] = float(row["h_jacket_override"])
            db[str(row["htm_name"])] = entry
        except (KeyError, ValueError, TypeError) as exc:
            _warnings.warn(
                f"Skipping malformed HTM row '{row.get('htm_name', '?')}': {exc}"
            )
            continue
    return db


HTM_DB: dict[str, dict] = load_htm_db()


# ---------------------------------------------------------------------------
# Nusselt correlations
# ---------------------------------------------------------------------------

NUSSELT_CORRELATIONS: dict[str, dict] = {
    "DIN 28131 (standard)": {
        "C": 0.36, "a": 2.0/3.0, "b": 1.0/3.0, "c": 0.14,
        "description": "DIN 28131 standard: Nu = 0.36 Re^(2/3) Pr^(1/3) (μ/μ_w)^0.14.",
        "ref": "DIN 28131:1979",
    },
    "Chilton–Drew–Jebens": {
        "C": 0.36, "a": 2.0/3.0, "b": 1.0/3.0, "c": 0.14,
        "description": "Classic correlation for jacketed stirred vessels (1944).",
        "ref": "Chilton, Drew, Jebens (1944)",
    },
    "Lehrer (anchor/helical)": {
        "C": 0.54, "a": 2.0/3.0, "b": 1.0/3.0, "c": 0.14,
        "description": "Anchor and helical ribbon impellers.",
        "ref": "Lehrer (1970)",
    },
    "Stein–Schmidt (high Re)": {
        "C": 0.50, "a": 2.0/3.0, "b": 1.0/3.0, "c": 0.14,
        "description": "Higher coefficient for high-Re turbulent regimes.",
        "ref": "Stein & Schmidt (1993)",
    },
    "Brooks–Su (Retreat Blade)": {
        "C": 0.33, "a": 2.0/3.0, "b": 1.0/3.0, "c": 0.14,
        "description": "Retreat-blade impellers in glass-lined vessels.",
        "ref": "Brooks & Su (1959)",
    },
    "Nagata (paddle)": {
        "C": 0.36, "a": 2.0/3.0, "b": 1.0/3.0, "c": 0.18,
        "description": "Paddle impellers with stronger wall viscosity correction.",
        "ref": "Nagata (1975)",
    },
}


def nusselt_jacket(Re: float, Pr: float, mu_ratio: float = 1.0,
                   correlation: str = "DIN 28131 (standard)") -> float:
    """Compute process-side Nusselt number for a jacketed stirred vessel."""
    corr = NUSSELT_CORRELATIONS.get(correlation, NUSSELT_CORRELATIONS["DIN 28131 (standard)"])
    C = corr["C"]
    a = corr["a"]
    b = corr["b"]
    c = corr["c"]
    return C * Re**a * Pr**b * mu_ratio**c


def process_side_htc(N_rps: float, D_imp: float, D_tank: float,
                     rho: float, mu: float, Cp: float, k_fluid: float,
                     mu_wall: float = 0.0,
                     correlation: str = "DIN 28131 (standard)") -> float:
    """Compute process-side heat transfer coefficient h_i (W/m²·K)."""
    if N_rps <= 0 or D_imp <= 0 or D_tank <= 0 or rho <= 0 or mu <= 0 or Cp <= 0 or k_fluid <= 0:
        return 0.0
    Re = rho * N_rps * D_imp**2 / mu
    Pr = Cp * mu / k_fluid
    mu_r = mu / mu_wall if mu_wall > 0 else 1.0
    Nu = nusselt_jacket(Re, Pr, mu_r, correlation)
    return Nu * k_fluid / D_tank


def jacket_side_htc(htm_name: str = "", v_jacket: float = 0.0,
                    D_hyd: float = 0.05) -> float:
    """Estimate jacket-side heat-transfer coefficient h_o (W/m²·K)."""
    if htm_name not in HTM_DB:
        return JACKET_HTC_DEFAULT
    htm = HTM_DB[htm_name]
    if "h_jacket_override" in htm:
        return htm["h_jacket_override"]
    rho_j = htm["rho_kg_m3"]
    mu_j = htm["mu_Pa_s"]
    Cp_j = htm["Cp_J_kgK"]
    k_j = htm["k_W_mK"]
    if v_jacket <= 0:
        v_jacket = 1.0
    if mu_j <= 0 or k_j <= 0 or D_hyd <= 0:
        return JACKET_HTC_DEFAULT
    Re_j = rho_j * v_jacket * D_hyd / mu_j
    Pr_j = Cp_j * mu_j / k_j
    if Re_j < 2300:
        Nu_j = 3.66 + 0.065 * (D_hyd / 1.0) * Re_j * Pr_j / (1.0 + 0.04 * ((D_hyd / 1.0) * Re_j * Pr_j) ** (2.0/3.0))
    else:
        Nu_j = 0.023 * Re_j**0.8 * Pr_j**0.4
    return Nu_j * k_j / D_hyd


def estimate_U_from_resistances(h_i: float, h_o: float,
                                wall_k: float = 16.0,
                                wall_thickness_m: float = 0.0,
                                lining_k: float = 0.0,
                                lining_thickness_m: float = 0.0,
                                fouling: float = FOULING_DEFAULT) -> float:
    """Compute overall U from individual resistances."""
    if h_i <= 0 or h_o <= 0:
        return 0.0
    R = 1.0 / h_i + 1.0 / h_o + fouling
    if wall_k > 0 and wall_thickness_m > 0:
        R += wall_thickness_m / wall_k
    if lining_k > 0 and lining_thickness_m > 0:
        R += lining_thickness_m / lining_k
    return 1.0 / R


# ---------------------------------------------------------------------------
# Batch temperature simulations
# ---------------------------------------------------------------------------

def batch_temperature_profile(
    rho: float, V_L_m3: float, Cp: float,
    U: float, A: float,
    T_start: float, T_target: float, T_jacket: float,
    P_agitator: float = 0.0, Q_rxn: float = 0.0,
    dt: float = 1.0, t_max: float = 36000.0,
) -> tuple[np.ndarray, np.ndarray]:
    """Simulate batch temperature vs time (Euler integration)."""
    if rho <= 0 or V_L_m3 <= 0 or Cp <= 0 or U <= 0 or A <= 0:
        return np.array([0.0]), np.array([T_start])

    m_Cp = rho * V_L_m3 * Cp
    cooling = T_target < T_start
    n_steps = int(t_max / dt) + 1
    t_arr = np.empty(n_steps)
    T_arr = np.empty(n_steps)
    t_arr[0] = 0.0
    T_arr[0] = T_start
    for i in range(1, n_steps):
        T_prev = T_arr[i - 1]
        Q_jacket = U * A * (T_jacket - T_prev)
        dTdt = (Q_jacket + P_agitator + Q_rxn) / m_Cp
        T_new = T_prev + dTdt * dt
        t_arr[i] = i * dt
        T_arr[i] = T_new
        if cooling and T_new <= T_target:
            return t_arr[: i + 1], T_arr[: i + 1]
        if not cooling and T_new >= T_target:
            return t_arr[: i + 1], T_arr[: i + 1]
    return t_arr, T_arr


def batch_temp_profile_variable_jacket(
    rho: float, V_L_m3: float, Cp: float,
    U: float, A: float,
    T_start: float, T_target: float,
    T_jacket_in: float,
    m_dot_jacket: float, Cp_jacket: float,
    P_agitator: float = 0.0, Q_rxn: float = 0.0,
    dt: float = 1.0, t_max: float = 36000.0,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Simulate batch temperature with non-isothermal jacket."""
    if rho <= 0 or V_L_m3 <= 0 or Cp <= 0 or U <= 0 or A <= 0 or m_dot_jacket <= 0 or Cp_jacket <= 0:
        return np.array([0.0]), np.array([T_start]), np.array([T_jacket_in])

    m_Cp = rho * V_L_m3 * Cp
    cooling = T_target < T_start
    NTU = U * A / (m_dot_jacket * Cp_jacket) if m_dot_jacket * Cp_jacket > 0 else 0.0
    n_steps = int(t_max / dt) + 1
    t_arr = np.empty(n_steps)
    T_arr = np.empty(n_steps)
    Tj_out = np.empty(n_steps)
    t_arr[0] = 0.0
    T_arr[0] = T_start
    Tj_out[0] = T_jacket_in
    for i in range(1, n_steps):
        T_prev = T_arr[i - 1]
        if NTU > 0:
            effectiveness = 1.0 - np.exp(-NTU)
            Q_jacket = effectiveness * m_dot_jacket * Cp_jacket * (T_jacket_in - T_prev)
            Tj_out_i = T_jacket_in + Q_jacket / (m_dot_jacket * Cp_jacket)
        else:
            Q_jacket = U * A * (T_jacket_in - T_prev)
            Tj_out_i = T_jacket_in
        dTdt = (Q_jacket + P_agitator + Q_rxn) / m_Cp
        T_new = T_prev + dTdt * dt
        t_arr[i] = i * dt
        T_arr[i] = T_new
        Tj_out[i] = Tj_out_i
        if cooling and T_new <= T_target:
            return t_arr[: i + 1], T_arr[: i + 1], Tj_out[: i + 1]
        if not cooling and T_new >= T_target:
            return t_arr[: i + 1], T_arr[: i + 1], Tj_out[: i + 1]
    return t_arr, T_arr, Tj_out


# ---------------------------------------------------------------------------
# Temperature-dependent simulations (scipy solve_ivp)
# ---------------------------------------------------------------------------

def _compute_hi(rho, mu, Cp, k_fluid, N_rps, D_imp, D_tank, mu_wall, nu_corr):
    """Helper: compute process-side h_i from fluid properties."""
    if rho <= 0 or mu <= 0 or Cp <= 0 or k_fluid <= 0 or N_rps <= 0 or D_imp <= 0 or D_tank <= 0:
        return 0.0
    Re = rho * N_rps * D_imp**2 / mu
    Pr = Cp * mu / k_fluid
    mu_r = mu / mu_wall if mu_wall > 0 else 1.0
    Nu = nusselt_jacket(Re, Pr, mu_r, nu_corr)
    return Nu * k_fluid / D_tank


def batch_temperature_profile_tdep(
    props_fn, V_L_m3: float,
    N_rps: float, D_imp: float, D_tank: float,
    h_o: float,
    wall_k: float, wall_m: float,
    lining_k: float, lining_m: float,
    fouling_R: float, A: float,
    T_start: float, T_target: float, T_jacket: float,
    mu_wall: float = 0.0,
    nu_corr: str = "DIN 28131 (standard)",
    P_agitator_fn=None, Q_rxn: float = 0.0,
    dt: float = 1.0, t_max: float = 36000.0,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Batch temperature profile with temperature-dependent fluid properties."""
    if V_L_m3 <= 0 or A <= 0:
        return np.array([0.0]), np.array([T_start]), np.array([0.0])

    P_agit = P_agitator_fn if isinstance(P_agitator_fn, (int, float)) else 0.0

    def _rhs(_t, y):
        T = y[0]
        rho_i, mu_i, Cp_i, k_i = props_fn(T)
        h_i = _compute_hi(rho_i, mu_i, Cp_i, k_i, N_rps, D_imp, D_tank, mu_wall, nu_corr)
        U_i = estimate_U_from_resistances(h_i, h_o, wall_k, wall_m,
                                           lining_k, lining_m, fouling_R)
        m_Cp = rho_i * V_L_m3 * Cp_i
        if m_Cp <= 0:
            m_Cp = 1.0
        Q_jacket = U_i * A * (T_jacket - T)
        return [(Q_jacket + P_agit + Q_rxn) / m_Cp]

    def _hit_target(_t, y):
        return y[0] - T_target
    _hit_target.terminal = True
    _hit_target.direction = -1.0 if T_target < T_start else 1.0

    t_eval = np.arange(0.0, t_max + dt, dt)
    sol = solve_ivp(
        _rhs, [0.0, t_max], [T_start],
        method="RK45", t_eval=t_eval, events=_hit_target,
        rtol=1e-8, atol=1e-10, max_step=dt,
    )

    t_arr = sol.t
    T_arr = sol.y[0]
    U_arr = np.empty_like(t_arr)
    for i, T in enumerate(T_arr):
        rho_i, mu_i, Cp_i, k_i = props_fn(T)
        h_i = _compute_hi(rho_i, mu_i, Cp_i, k_i, N_rps, D_imp, D_tank, mu_wall, nu_corr)
        U_arr[i] = estimate_U_from_resistances(h_i, h_o, wall_k, wall_m,
                                                lining_k, lining_m, fouling_R)
    return t_arr, T_arr, U_arr


def batch_temp_profile_variable_jacket_tdep(
    props_fn, V_L_m3: float,
    N_rps: float, D_imp: float, D_tank: float,
    h_o: float,
    wall_k: float, wall_m: float,
    lining_k: float, lining_m: float,
    fouling_R: float, A: float,
    T_start: float, T_target: float,
    T_jacket_in: float,
    m_dot_jacket: float, Cp_jacket: float,
    mu_wall: float = 0.0,
    nu_corr: str = "DIN 28131 (standard)",
    P_agitator: float = 0.0, Q_rxn: float = 0.0,
    dt: float = 1.0, t_max: float = 36000.0,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Variable-jacket simulation with temperature-dependent fluid properties."""
    if (V_L_m3 <= 0 or A <= 0 or m_dot_jacket <= 0 or Cp_jacket <= 0):
        return (np.array([0.0]), np.array([T_start]),
                np.array([T_jacket_in]), np.array([0.0]))

    def _rhs(_t, y):
        T = y[0]
        rho_i, mu_i, Cp_i, k_i = props_fn(T)
        h_i = _compute_hi(rho_i, mu_i, Cp_i, k_i, N_rps, D_imp, D_tank, mu_wall, nu_corr)
        U_i = estimate_U_from_resistances(h_i, h_o, wall_k, wall_m,
                                           lining_k, lining_m, fouling_R)
        m_Cp = rho_i * V_L_m3 * Cp_i
        if m_Cp <= 0:
            m_Cp = 1.0
        NTU = U_i * A / (m_dot_jacket * Cp_jacket)
        eff = 1.0 - np.exp(-NTU) if NTU > 0 else 0.0
        Q_jacket = eff * m_dot_jacket * Cp_jacket * (T_jacket_in - T)
        return [(Q_jacket + P_agitator + Q_rxn) / m_Cp]

    def _hit_target(_t, y):
        return y[0] - T_target
    _hit_target.terminal = True
    _hit_target.direction = -1.0 if T_target < T_start else 1.0

    t_eval = np.arange(0.0, t_max + dt, dt)
    sol = solve_ivp(
        _rhs, [0.0, t_max], [T_start],
        method="RK45", t_eval=t_eval, events=_hit_target,
        rtol=1e-8, atol=1e-10, max_step=dt,
    )

    t_arr = sol.t
    T_arr = sol.y[0]
    U_arr = np.empty_like(t_arr)
    Tj_out = np.empty_like(t_arr)
    for i, T in enumerate(T_arr):
        rho_i, mu_i, Cp_i, k_i = props_fn(T)
        h_i = _compute_hi(rho_i, mu_i, Cp_i, k_i, N_rps, D_imp, D_tank, mu_wall, nu_corr)
        U_i = estimate_U_from_resistances(h_i, h_o, wall_k, wall_m,
                                           lining_k, lining_m, fouling_R)
        NTU = U_i * A / (m_dot_jacket * Cp_jacket)
        eff = 1.0 - np.exp(-NTU) if NTU > 0 else 0.0
        Q_jacket = eff * m_dot_jacket * Cp_jacket * (T_jacket_in - T)
        Tj_out[i] = T_jacket_in + Q_jacket / (m_dot_jacket * Cp_jacket)
        U_arr[i] = U_i

    return t_arr, T_arr, Tj_out, U_arr
