"""Heat generation, jacket heat transfer and overall-U primitives.

This module is the single home of the heat-transfer correlations and material
tables; ``core/heat_transfer.py`` (Heat Transfer tool simulations) imports them.
Sources for every equation and value: docs/EQUATIONS_REGISTRY.md.

UNIT CONVENTION
---------------
Reaction: delta_H in kJ/mol, k in 1/s (1st order) or L/(mol.s) (2nd order),
C0 in mol/L, V_L in litres -> reaction_rate_mol_per_s returns mol/s and
heat_generation_rate returns W.  Heat transfer: U in W/(m^2.K), A in m^2,
h in W/(m^2.K), k_fluid in W/(m.K), Cp in J/(kg.K); batch energy balances use
V in m^3.  N_rps is in rev/s.
"""

import re as _re
from typing import Any

import numpy as np

from .geometry import cone_depth


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
    elif order == "0":
        r = k
    else:
        return 0.0
    return r * V_L


def heat_generation_rate(delta_H_kJ_mol: float, r_mol_per_s: float) -> float:
    """Rate of heat release (W) by the reaction, Q_rxn = −ΔH_rxn × r.

    Positive for an exothermic reaction (ΔH < 0), negative (heat absorbed) for an
    endothermic one.
    """
    return -delta_H_kJ_mol * 1000.0 * r_mol_per_s


# ---------------------------------------------------------------------------
# Jacket area estimation
# ---------------------------------------------------------------------------

def estimate_jacket_area(D_tank: float, H: float,
                         bottom_dish: str = "",
                         bottom_dish_height_m: float | None = None) -> float:
    """Estimate jacketed heat-transfer area (m²) wetted by the liquid."""
    if D_tank <= 0 or H <= 0:
        return 0.0

    A_flat = np.pi / 4 * D_tank**2
    dish = str(bottom_dish).lower() if bottom_dish else ""

    measured_height = float(bottom_dish_height_m or 0.0)
    if "ellip" in dish:
        h_dish = measured_height if measured_height > 0 else D_tank / 4
        A_dish_full = 1.084 * D_tank**2   # 2:1 semi-ellipsoidal head, exact spheroid area
    elif "torisph" in dish or "din" in dish:
        h_dish = measured_height if measured_height > 0 else 0.1935 * D_tank
        A_dish_full = 0.99 * D_tank**2    # Klöpper head (DIN 28011) surface area
    elif "conic" in dish:
        h_dish = measured_height if measured_height > 0 else cone_depth(D_tank, dish)
        R = D_tank / 2.0
        # Wetted cone = lateral surface area = A_flat * sqrt(1 + (h/R)^2).
        A_dish_full = A_flat * np.sqrt(1.0 + (h_dish / R) ** 2) if R > 0 else A_flat
    else:
        h_dish = measured_height
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
# Material property tables (values at ~20-25 C, each with its source)
# ---------------------------------------------------------------------------

WALL_CONDUCTIVITY: dict[str, float] = {
    "stainless steel": 15.0, "stainless": 15.0,
    "ss316": 13.4, "ss304": 14.4,
    "hastelloy": 12.0, "hastelloy c-276": 12.0,
    "inconel": 15.0, "incoloy": 12.0,
    "monel": 26.0, "nickel": 61.0,
    "carbon steel": 50.0,
    "glass": 1.2, "glass-lined": 1.2,
    "titanium": 22.0, "zirconium": 23.0,
    "tantalum": 57.0, "copper": 390.0,
}

WALL_CONDUCTIVITY_REF: dict[str, str] = {
    "stainless steel": "Generic austenitic grade; midpoint of 304/316 (13-16 W/m.K). "
                       "Engineering ToolBox, Thermal Conductivity of Metals and Alloys.",
    "ss316": "316/316L at 20-100 C. ASM Handbook Vol. 1; confirm per mill certificate.",
    "ss304": "Type 304 at 20 C. Engineering ToolBox, Thermal Conductivity of Metals and Alloys.",
    "hastelloy": "Hastelloy C at 0-25 C. Engineering ToolBox. Haynes C-276 datasheets "
                 "quote ~10 W/m.K at 25 C - verify for critical duty.",
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
    "glass": 1.2, "glass-lined": 1.2,
    "ptfe": 0.25, "teflon": 0.25, "pfa": 0.25,
    "pvdf": 0.19, "rubber": 0.16, "epoxy": 0.20,
    "titanium": 22.0, "hastelloy": 12.0, "tantalum": 57.0,
}

# Nominal as-applied lining thickness (m); reactor-grade glass lining is 1.0-2.0 mm.
LINING_THICKNESS_DEFAULT: dict[str, float] = {
    "glass": 0.0015, "glass-lined": 0.0015,
    "ptfe": 0.002, "teflon": 0.002, "pfa": 0.002,
    "pvdf": 0.003, "rubber": 0.006, "epoxy": 0.003,
    "titanium": 0.002, "hastelloy": 0.002, "tantalum": 0.001,
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
    "titanium": "Metal clad lining - see WALL_CONDUCTIVITY_REF['titanium'].",
    "hastelloy": "Metal clad lining - see WALL_CONDUCTIVITY_REF['hastelloy'].",
    "tantalum": "Metal clad lining - see WALL_CONDUCTIVITY_REF['tantalum'].",
}

# Fallback (k, Cp) for fluids missing from the solvent library.
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

# Simple-jacket water/glycol film coefficient (Perry's 9th ed., Sec. 11).
JACKET_HTC_DEFAULT = 1500.0
# Flow-path length in the Hausen laminar Graetz term Gz = (d_hyd/L) Re Pr.
JACKET_PATH_L_M = 1.0
# Clean process service (TEMA RGP-T-2.4).
FOULING_DEFAULT = 0.0002

# Process-side Nu = C Re^a Pr^b (mu/mu_w)^c for jacketed agitated vessels.
NUSSELT_CORRELATIONS: dict[str, dict[str, float | str]] = {
    "Chilton–Drew–Jebens (paddle)": {
        "C": 0.36, "a": 2.0 / 3.0, "b": 1.0 / 3.0, "c": 0.14,
        "ref": "Chilton, Drew & Jebens (1944), Ind. Eng. Chem. 36(6):510, "
               "doi:10.1021/ie50414a006. Jacketed vessel, paddle impeller, turbulent.",
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
}
DEFAULT_NUSSELT = "Chilton–Drew–Jebens (paddle)"


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
    Nu = nusselt_jacket(Re, Pr, 1.0, DEFAULT_NUSSELT)
    h_i = Nu * k_fluid / D_tank

    k_wall = _lookup_wall_k(material)
    wall_m = wall_thickness_mm / 1000.0 if wall_thickness_mm > 0 else 0.0

    R_wall = 0.0
    if k_wall is not None and wall_m > 0:
        R_wall = wall_m / k_wall
    elif k_wall is not None and wall_m == 0:
        warnings.append("Wall thickness unknown – wall resistance omitted")
    elif wall_m > 0:
        k_wall = WALL_CONDUCTIVITY["stainless steel"]
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
            R_wall += 0.010 / WALL_CONDUCTIVITY["stainless steel"]
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


def time_to_cool_or_heat(rho: float, V_m3: float, Cp: float,
                         U: float, A: float,
                         T_start: float, T_end: float,
                         T_jacket: float) -> float:
    """Logarithmic batch heating / cooling time (s), t = (ρVCp/UA)·ln(ΔT_start/ΔT_end)."""
    if U <= 0 or A <= 0 or rho <= 0 or V_m3 <= 0 or Cp <= 0:
        return np.inf
    dT_start = T_start - T_jacket
    dT_end = T_end - T_jacket
    if dT_start == 0 or dT_end == 0:
        return np.inf
    ratio = dT_start / dT_end
    if ratio <= 0 or ratio <= 1:
        return np.inf
    return (rho * V_m3 * Cp) / (U * A) * np.log(ratio)


# ---------------------------------------------------------------------------
# Film coefficients and overall U
# ---------------------------------------------------------------------------

def nusselt_jacket(Re: float, Pr: float, mu_ratio: float = 1.0,
                   correlation: str = DEFAULT_NUSSELT) -> float:
    """Process-side Nu = C Re^a Pr^b (mu/mu_w)^c for a jacketed stirred vessel."""
    corr = NUSSELT_CORRELATIONS.get(correlation, NUSSELT_CORRELATIONS[DEFAULT_NUSSELT])
    if Re <= 0 or Pr <= 0:
        return 0.0
    return (float(corr["C"]) * Re ** float(corr["a"]) * Pr ** float(corr["b"])
            * (mu_ratio if mu_ratio > 0 else 1.0) ** float(corr["c"]))


def _num(value: Any, default: float = 0.0) -> float:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return default
    return default if np.isnan(f) else f


def jacket_side_htc(htm: dict[str, Any], v_jacket: float, d_hyd: float) -> float:
    """Jacket-side h_o (W/m²·K) for a heat-transfer medium (HTM.csv row as a dict):
    Hausen (laminar, Re < 2300) or Dittus–Boelter (turbulent)."""
    if "h_jacket_override" in htm:
        return _num(htm["h_jacket_override"], JACKET_HTC_DEFAULT)
    rho_j, mu_j = _num(htm.get("rho_kg_m3")), _num(htm.get("mu_Pa_s"))
    cp_j, k_j = _num(htm.get("Cp_J_kgK")), _num(htm.get("k_W_mK"))
    if rho_j <= 0 or mu_j <= 0 or cp_j <= 0 or k_j <= 0 or v_jacket <= 0 or d_hyd <= 0:
        return JACKET_HTC_DEFAULT
    re_j = rho_j * v_jacket * d_hyd / mu_j
    pr_j = cp_j * mu_j / k_j
    if re_j < 2300:
        gz = d_hyd / JACKET_PATH_L_M * re_j * pr_j
        nu_j = 3.66 + 0.0668 * gz / (1.0 + 0.04 * gz ** (2.0 / 3.0))
    else:
        nu_j = 0.023 * re_j**0.8 * pr_j**0.4
    return nu_j * k_j / d_hyd


def estimate_U_from_resistances(h_i: float, h_o: float,
                                wall_k: float = 0.0,
                                wall_thickness_m: float = 0.0,
                                lining_k: float = 0.0,
                                lining_thickness_m: float = 0.0,
                                fouling: float = FOULING_DEFAULT) -> float:
    """Overall U from series resistances 1/U = 1/h_i + x_w/k_w + x_l/k_l + 1/h_o + R_f."""
    if h_i <= 0 or h_o <= 0:
        return 0.0
    r_total = 1.0 / h_i + 1.0 / h_o + max(fouling, 0.0)
    if wall_k > 0 and wall_thickness_m > 0:
        r_total += wall_thickness_m / wall_k
    if lining_k > 0 and lining_thickness_m > 0:
        r_total += lining_thickness_m / lining_k
    return 1.0 / r_total
