"""Gas-liquid mass transfer: kLa correlations.

UNIT CONVENTION
---------------
P_V is the volumetric specific power P/V in W/m^3 (NOT W/kg); v_s is the
superficial gas velocity in m/s; kLa is returned in 1/s.  NOTE: these
empirical correlations carry dimensional constants and are only valid with
the SI inputs above.

REFERENCES (per function)
-------------------------
    kla_vant_riet (kLa = 0.026 (P/V)^0.4 v_s^0.5, coalescing)
        Ref: van 't Riet (1979), Ind. Eng. Chem. Process Des. Dev. 18, 357.
        [NOT in context/ - verify]   <-- requires P/V in W/m^3
    kla_surface (free-surface kL from surface renewal)
        Ref: Lamont & Scott (1970), AIChE J. 16, 513.
"""

import numpy as np


def kla_vant_riet(P_V_W_m3: float, v_s: float, coalescing: bool = True) -> float:
    """Van 't Riet (1979) kLa (1/s) for aerated stirred tanks.

    ``P_V_W_m3`` is the gassed power per unit liquid volume in **W/m³** (not
    W/kg — passing ε in W/kg under-predicts kLa by ~ρ^0.4 ≈ 16× for water);
    ``v_s`` is the superficial gas velocity in m/s. Coalescing (water-like):
    kLa = 0.026 (P/V)^0.4 v_s^0.5; non-coalescing (electrolyte):
    kLa = 0.002 (P/V)^0.7 v_s^0.2. Fitted for 500 < P/V < 10 000 W/m³.
    """
    if v_s <= 0 or P_V_W_m3 <= 0:
        return 0.0
    if coalescing:
        return 0.026 * P_V_W_m3**0.4 * v_s**0.5
    return 0.002 * P_V_W_m3**0.7 * v_s**0.2


def kla_surface(epsilon: float, nu: float, D_mol: float,
                D_tank: float, V: float) -> float:
    """Headspace-only (free-surface) kLa – Lamont & Scott (1970)."""
    if epsilon <= 0 or nu <= 0 or D_mol <= 0 or D_tank <= 0 or V <= 0:
        return 0.0
    kL = 0.4 * np.sqrt(D_mol) * (epsilon / nu) ** 0.25
    A_surface = np.pi / 4 * D_tank**2
    a = A_surface / V
    return kL * a
