"""Liquid-liquid dispersion: Weber number, drop size, phase separation, mass transfer.

UNIT CONVENTION
---------------
N in rev/s, lengths in m, densities in kg/m^3, mu in Pa.s, interfacial tension
sigma_LL in N/m, dissipation epsilon_kg in W/kg.  Drop sizes returned in m,
velocities in m/s, times in s.

REFERENCES (per function)
-------------------------
None of these correlations are in the context source (Myerson 2019).

    weber_number (We = rho_c N^2 D^3 / sigma)
        Standard impeller Weber number.  [definition]
    sauter_drop_diameter (d32/D = 0.053 We^-0.6 (1 + 3 phi_d))
        Ref: Hinze (1955), AIChE J. 1, 289; Chen & Middleman (1967),
        AIChE J. 13, 989.  [NOT in context/ - verify]
    phase_separation_check (Stokes drop settling -> separation time)
        Ref: Stokes' law; standard sedimentation.  [textbook - verify H_est=D_tank assumption]
    minimum_dispersion_speed
        Ref: Skelland & Seksaria (1978), Ind. Eng. Chem. Process Des. Dev.
        17, 56.  [NOT in context/ - verify]
    liquid_liquid_mass_transfer (Sh = 2 + 0.6 Re^0.5 Sc^(1/3))
        Ref: Calderbank & Moo-Young (1961), Chem. Eng. Sci. 16, 39;
        Ranz & Marshall (1952).  [NOT in context/ - verify]
"""

import numpy as np

# Named constants for correlations
HINZE_C1 = 0.053    # Hinze-Kolmogorov / Chen & Middleman d32 coefficient
HINZE_C2 = 3.0      # Hinze-Kolmogorov dispersed-phase holdup coefficient


def weber_number(rho_c: float, N: float, D_imp: float,
                 sigma_LL: float) -> float:
    """Impeller Weber number for liquid-liquid systems."""
    if sigma_LL <= 0:
        return 0.0
    return rho_c * N**2 * D_imp**3 / sigma_LL


def sauter_drop_diameter(We: float, D_imp: float,
                         phi_d: float = 0.0) -> float:
    """Sauter mean drop diameter d₃₂ — Hinze-Kolmogorov / Chen & Middleman."""
    if We <= 0 or D_imp <= 0:
        return 0.0
    return HINZE_C1 * D_imp * We**(-0.6) * (1.0 + HINZE_C2 * phi_d)


def phase_separation_check(N: float, D_imp: float, D_tank: float,
                           rho_c: float, rho_d: float, mu_c: float,
                           sigma_LL: float, phi_d: float,
                           g: float = 9.81) -> dict:
    """Evaluate whether a liquid-liquid dispersion will separate at rest."""
    We = weber_number(rho_c, N, D_imp, sigma_LL)
    d32 = sauter_drop_diameter(We, D_imp, phi_d)
    delta_rho = abs(rho_d - rho_c)
    if mu_c > 0 and d32 > 0:
        v_drop = delta_rho * g * d32**2 / (18.0 * mu_c)
    else:
        v_drop = 0.0
    H_est = D_tank
    t_sep = H_est / v_drop if v_drop > 0 else np.inf
    if t_sep < 60:
        assessment = "Rapid separation (< 1 min) — unstable dispersion"
    elif t_sep < 600:
        assessment = "Moderate separation (1–10 min)"
    elif t_sep < 3600:
        assessment = "Slow separation (10–60 min) — reasonably stable"
    else:
        assessment = "Very stable dispersion (> 1 h)"
    return {
        "We": We, "d32 (m)": d32, "d32 (µm)": d32 * 1e6,
        "Drop settling velocity (m/s)": v_drop,
        "Separation time (s)": t_sep, "Assessment": assessment,
    }


def minimum_dispersion_speed(D_imp: float, sigma_LL: float,
                              rho_c: float, phi_d: float) -> float:
    """Minimum impeller speed to maintain a dispersion (Skelland & Seksaria)."""
    if D_imp <= 0 or sigma_LL <= 0 or rho_c <= 0:
        return 0.0
    C = 1.03
    return C * (sigma_LL / (rho_c * D_imp**3))**0.5 * (1.0 + 2.5 * phi_d)


def liquid_liquid_mass_transfer(d32: float, D_mol: float,
                                rho_c: float, mu_c: float,
                                epsilon_kg: float) -> float:
    """Liquid-liquid mass-transfer coefficient — Calderbank & Moo-Young (1961)."""
    if d32 <= 0 or D_mol <= 0 or mu_c <= 0 or rho_c <= 0:
        return 0.0
    v_slip = (max(epsilon_kg, 1e-12) * d32) ** (1.0 / 3.0)
    Re_d = rho_c * v_slip * d32 / mu_c
    Sc = mu_c / (rho_c * D_mol)
    Sh = 2.0 + 0.6 * Re_d**0.5 * Sc**(1.0 / 3.0)
    return Sh * D_mol / d32
