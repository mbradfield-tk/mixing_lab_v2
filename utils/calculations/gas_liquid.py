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
        Ref: Lamont & Scott (1970), AIChE J. 16, 513.  [NOT in context/ - verify]
    gas_flooding_speed (N_flood at FlG = 30 Fr (D/T)^3.5)
        Ref: Smith et al. (1987). [see Equation 11-4]
"""

import numpy as np


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


def gas_flooding_speed(
    QG: float, D: float, T: float, g: float = 9.81
) -> float:
    """
    Minimum impeller speed to avoid gas flooding (Equation 11-4).
    
    When FlG > 30 Fr (D/T)^3.5, the gas swamps the impeller.
    Solves for N when FlG = QG/(N D^3) and Fr = N^2 D/g.
    
    Returns impeller speed in rev/s.
    """
    if QG <= 0 or D <= 0 or T <= 0 or g <= 0:
        return 0.0
    ratio_cubed = (QG * g) / (30 * D**4 * (D / T)**3.5)
    return ratio_cubed ** (1.0 / 3.0)
