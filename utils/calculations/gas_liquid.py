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
    gas_holdup_calderbank (vessel-averaged gas holdup, Eq. 17)
        Ref: Calderbank (1958), Trans. Inst. Chem. Eng. 36, 443.
        [NOT in context/ - verify]   <-- requires P/V in W/m^3
"""

import numpy as np

def gas_holdup_calderbank(
    P_V: float,
    U_s: float,
    rho_C: float,
    sigma: float,
    U_t: float = 0.265,
) -> float:
    """Vessel-averaged gas holdup from the Calderbank correlation."""
    if P_V < 0 or U_s <= 0 or rho_C <= 0 or sigma <= 0 or U_t <= 0:
        return 0.0

    a = np.sqrt(U_s / U_t)
    B = 0.000216 * (P_V**0.4 * rho_C**0.2 / sigma**0.6) * a
    x = 0.5 * (a + np.sqrt(a * a + 4.0 * B))
    return float(x * x)


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


def gas_flooding_flow_rate(
    N: float | np.ndarray, D: float, T: float, g: float = 9.81
) -> float | np.ndarray:
    """Gas flow rate at the flooding limit (m^3/s).

    From Fl_G = 30 Fr (D/T)^3.5 with:
        Fl_G = Q_G / (N D^3)
        Fr = N^2 D / g
    """
    if D <= 0 or T <= 0 or g <= 0:
        return np.zeros_like(N, dtype=float) if isinstance(N, np.ndarray) else 0.0
    return 30.0 * np.asarray(N) ** 3 * D**4 * (D / T) ** 3.5 / g


def complete_dispersion_speed(
    QG: float, D: float, T: float, g: float = 9.81
) -> float:
    """Minimum impeller speed for complete gas dispersion (rev/s).

    Uses:
        (Fl_G)_CD = 0.2 (D/T)^0.5 Fr_CD^0.5
    with Fl_G = Q_G / (N D^3) and Fr = N^2 D / g.
    """
    if QG <= 0 or D <= 0 or T <= 0 or g <= 0:
        return 0.0
    denominator = 0.2 * D**3 * (D / T) ** 0.5 * np.sqrt(D / g)
    return np.sqrt(QG / denominator)


def complete_dispersion_flow_rate(
    N: float | np.ndarray, D: float, T: float, g: float = 9.81
) -> float | np.ndarray:
    """Gas flow rate at the complete-dispersion limit (m^3/s)."""
    if D <= 0 or T <= 0 or g <= 0:
        return np.zeros_like(N, dtype=float) if isinstance(N, np.ndarray) else 0.0
    return 0.2 * np.asarray(N) ** 2 * D**3 * (D / T) ** 0.5 * np.sqrt(D / g)

def gas_holdup_calderbank_numeric(
    P_V: float,
    U_s: float,
    rho_C: float,
    sigma: float,
    U_t: float = 0.265,
) -> float:
    """Vessel-averaged gas holdup from the Calderbank correlation (numpy root solver).

    Solves x*(x - a) - B = 0 for x = sqrt(holdup) via numpy.roots and
    returns the square of the positive root.
    """
    if P_V < 0 or U_s <= 0 or rho_C <= 0 or sigma <= 0 or U_t <= 0:
        return 0.0

    a = np.sqrt(U_s / U_t)
    B = 0.000216 * (P_V**0.4 * rho_C**0.2 / sigma**0.6) * a
    roots = np.roots([1.0, -a, -B])  # x^2 - a*x - B = 0
    positive = [r.real for r in roots if abs(r.imag) < 1e-12 and r.real > 0]
    return float(max(positive) ** 2) if positive else 0.0