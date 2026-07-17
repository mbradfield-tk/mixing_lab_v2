"""Gas-liquid mass transfer: kLa, holdup, bubble diameter, flooding.

UNIT CONVENTION
---------------
P_V is the volumetric specific power P/V in W/m^3 (NOT W/kg); v_s is the
superficial gas velocity in m/s; kLa is returned in 1/s; bubble/holdup
properties in SI (m, dimensionless).  NOTE: these empirical correlations carry
dimensional constants and are only valid with the SI inputs above.

REFERENCES (per function)
-------------------------
None of the gas-liquid correlations below appear in the context source
(Myerson 2019, crystallization handbook); the canonical references are given
but MUST be verified against the original literature.

    kla_vant_riet (kLa = 0.026 (P/V)^0.4 v_s^0.5, coalescing)
        Ref: van 't Riet (1979), Ind. Eng. Chem. Process Des. Dev. 18, 357.
        [NOT in context/ - verify]   <-- requires P/V in W/m^3
    kla_surface (free-surface kL from surface renewal)
        Ref: Lamont & Scott (1970), AIChE J. 16, 513.  [NOT in context/ - verify]
    gas_holdup_hughmark
        Ref: Hughmark (1980), Ind. Eng. Chem. Process Des. Dev. 19, 638.
        [NOT in context/ - verify; coefficient/exponents are a simplified fit]
    sauter_bubble_diameter (d32, Calderbank)
        Ref: Calderbank (1958), Trans. Inst. Chem. Eng. 36, 443.
        [NOT in context/ - verify]
    gas_flooding_speed (flow number Fl_crit = 0.035)
        Ref: Warmoeskerken & Smith; Nienow, in Handbook of Industrial Mixing
        (2004), Ch. 11.  [NOT in context/ - verify]
    gas_flow_rate_from_vs
        Geometric conversion (Q = v_s * pi/4 * D_tank^2).  [definition]
"""

import numpy as np

# Named constants for correlations
HUGHMARK_CONSTANT = 0.505           # Hughmark (1967) gas holdup coefficient
CALDERBANK_D32_CONSTANT = 4.15      # Calderbank (1958) bubble diameter coefficient
CALDERBANK_D32_OFFSET = 0.0009      # Calderbank (1958) bubble diameter offset (m)


def kla_vant_riet(P_V: float, v_s: float, coalescing: bool = True) -> float:
    """Van 't Riet (1979) correlation for kLa in aerated stirred tanks."""
    if v_s <= 0 or P_V <= 0:
        return 0.0
    if coalescing:
        return 0.026 * P_V**0.4 * v_s**0.5
    return 0.002 * P_V**0.7 * v_s**0.2


def kla_surface(epsilon: float, nu: float, D_mol: float,
                D_tank: float, V: float) -> float:
    """Headspace-only (free-surface) kLa – Lamont & Scott (1970)."""
    if epsilon <= 0 or nu <= 0 or D_mol <= 0 or D_tank <= 0 or V <= 0:
        return 0.0
    kL = 0.4 * np.sqrt(D_mol) * (epsilon / nu) ** 0.25
    A_surface = np.pi / 4 * D_tank**2
    a = A_surface / V
    return kL * a


def gas_holdup_hughmark(v_s: float, P_V: float, mu: float,
                        sigma: float, rho: float) -> float:
    """Gas holdup (volume fraction) — simplified Hughmark (1967)."""
    if v_s <= 0 or P_V <= 0 or sigma <= 0:
        return 0.0
    eps_G = HUGHMARK_CONSTANT * v_s**0.47 * P_V**0.4 * (mu / sigma)**0.08
    return min(eps_G, 0.95)


def sauter_bubble_diameter(P_V: float, v_s: float, sigma: float,
                           rho: float) -> float:
    """Sauter mean bubble diameter d₃₂ — Calderbank (1958)."""
    if P_V <= 0 or sigma <= 0 or rho <= 0:
        return 0.0
    d32 = CALDERBANK_D32_CONSTANT * sigma**0.6 / (P_V**0.4 * rho**0.2) + CALDERBANK_D32_OFFSET
    return max(d32, 1e-6)


def gas_flooding_speed(Nq: float, D_imp: float, Q_gas: float) -> float:
    """Minimum impeller speed for complete gas dispersion."""
    if Q_gas <= 0 or D_imp <= 0:
        return 0.0
    Fl_crit = 0.035
    return Q_gas / (Fl_crit * D_imp**3)


def gas_flow_rate_from_vs(v_s: float, D_tank: float) -> float:
    """Convert superficial gas velocity to volumetric flow rate."""
    if v_s <= 0 or D_tank <= 0:
        return 0.0
    return v_s * np.pi / 4 * D_tank**2
