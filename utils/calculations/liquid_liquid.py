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
        Critical impeller Weber number criterion, N_min ~ sqrt(sigma/(rho_c D^3)),
        with a linear holdup correction.  Simplified heuristic — NOT the
        published Skelland & Seksaria (1978) correlation (which includes
        (T/D), viscosity and buoyancy groups).  [heuristic - verify]
    liquid_liquid_mass_transfer (Sh = 2 + 0.6 Re^0.5 Sc^(1/3))
        Ref: Calderbank & Moo-Young (1961), Chem. Eng. Sci. 16, 39;
        Ranz & Marshall (1952).  [NOT in context/ - verify]
"""

import numpy as np

# Named constants for correlations
HINZE_C1 = 0.053    # Hinze-Kolmogorov / Chen & Middleman d32 coefficient
HINZE_C2 = 3.0      # Hinze-Kolmogorov dispersed-phase holdup coefficient
DEFAULT_GRAVITY = 9.81


def _positive_finite(value: float) -> bool:
    """Return True when a correlation input is finite and strictly positive."""
    try:
        return bool(np.isfinite(value) and value > 0)
    except (TypeError, ValueError):
        return False


def weber_number(rho_c: float, N: float, D_imp: float,
                 sigma_LL: float) -> float:
    """Impeller Weber number for liquid-liquid systems."""
    if not all(_positive_finite(v) for v in (rho_c, N, D_imp, sigma_LL)):
        return 0.0
    return rho_c * N**2 * D_imp**3 / sigma_LL


def sauter_drop_diameter(We: float, D_imp: float,
                         phi_d: float = 0.0) -> float:
    """Sauter mean drop diameter d₃₂ — Hinze-Kolmogorov / Chen & Middleman."""
    if not _positive_finite(We) or not _positive_finite(D_imp):
        return 0.0
    holdup = min(max(float(phi_d), 0.0), 0.95)
    return HINZE_C1 * D_imp * We**(-0.6) * (1.0 + HINZE_C2 * holdup)


def droplet_settling_velocity(d32: float, rho_c: float, rho_d: float,
                              mu_c: float, g: float = DEFAULT_GRAVITY) -> float:
    """Estimate terminal droplet velocity with Schiller-Naumann drag correction."""
    if not all(_positive_finite(v) for v in (d32, rho_c, mu_c, g)):
        return 0.0
    delta_rho = abs(rho_d - rho_c)
    if delta_rho == 0:
        return 0.0
    velocity = d32**2 * g * delta_rho / (18.0 * mu_c)
    for _ in range(30):
        reynolds = rho_c * velocity * d32 / mu_c
        if reynolds < 0.1:
            break
        drag = (24.0 / reynolds) * (1.0 + 0.15 * reynolds**0.687)
        updated = np.sqrt(4.0 * g * d32 * delta_rho / (3.0 * drag * rho_c))
        if abs(updated - velocity) / max(velocity, 1e-30) < 1e-6:
            velocity = updated
            break
        velocity = updated
    return float(velocity)


def phase_separation_check(N: float, D_imp: float, D_tank: float,
                           rho_c: float, rho_d: float, mu_c: float,
                           sigma_LL: float, phi_d: float,
                           g: float = 9.81) -> dict:
    """Evaluate whether a liquid-liquid dispersion will separate at rest."""
    We = weber_number(rho_c, N, D_imp, sigma_LL)
    d32 = sauter_drop_diameter(We, D_imp, phi_d)
    v_drop = droplet_settling_velocity(d32, rho_c, rho_d, mu_c, g)
    drop_re = rho_c * v_drop * d32 / mu_c if _positive_finite(mu_c) else 0.0
    t_sep = D_tank / v_drop if _positive_finite(D_tank) and v_drop > 0 else np.inf
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
        "Drop Reynolds number": drop_re,
        "Separation time (s)": t_sep, "Assessment": assessment,
    }


def minimum_dispersion_speed(D_imp: float, sigma_LL: float,
                              rho_c: float, phi_d: float) -> float:
    """Minimum impeller speed to maintain a dispersion.

    Critical-Weber heuristic (We_crit ≈ 1/C²) with linear holdup correction;
    simplified, not the published Skelland & Seksaria correlation.
    """
    if not all(_positive_finite(v) for v in (D_imp, sigma_LL, rho_c)):
        return 0.0
    C = 1.03
    holdup = min(max(float(phi_d), 0.0), 0.95)
    return C * (sigma_LL / (rho_c * D_imp**3))**0.5 * (1.0 + 2.5 * holdup)


def n_min_van_heuven_beek(d_imp: float, phi: float, rho_c: float,
                          rho_d: float, mu_c: float, sigma: float) -> float:
    """Van Heuven & Beek (1971) minimum emulsification speed, rev/s."""
    d_rho = abs(rho_d - rho_c)
    if not all(_positive_finite(v) for v in (d_imp, rho_c, mu_c, sigma)) or d_rho <= 0:
        return np.nan
    holdup = min(max(float(phi), 0.0), 0.95)
    rho_m = holdup * rho_d + (1.0 - holdup) * rho_c
    return (3.28 * (DEFAULT_GRAVITY * d_rho)**0.385 * mu_c**0.0769 * sigma**0.0769
            * (1.0 + 2.5 * holdup)**0.897
            / (d_imp**0.769 * rho_m**0.538))



def liquid_liquid_mass_transfer(d32: float, D_mol: float,
                                rho_c: float, mu_c: float,
                                epsilon_kg: float) -> float:
    """Liquid-liquid mass-transfer coefficient — Calderbank & Moo-Young (1961)."""
    if not all(_positive_finite(v) for v in (d32, D_mol, mu_c, rho_c)):
        return 0.0
    v_slip = (max(float(epsilon_kg), 1e-12) * d32) ** (1.0 / 3.0)
    Re_d = rho_c * v_slip * d32 / mu_c
    Sc = mu_c / (rho_c * D_mol)
    Sh = 2.0 + 0.6 * Re_d**0.5 * Sc**(1.0 / 3.0)
    return Sh * D_mol / d32


def liquid_liquid_capacity_ratio(kLa: float, t_rxn: float) -> float:
    """Return transfer capacity divided by first-order kinetic demand."""
    if not _positive_finite(kLa) or not _positive_finite(t_rxn):
        return 0.0
    return float(kLa * t_rxn)


def dispersion_screen(N: float, D_imp: float, D_tank: float,
                      rho_c: float, rho_d: float, mu_c: float,
                      sigma_LL: float, phi_d: float, D_mol: float,
                      epsilon_kg: float) -> dict:
    """Return a consolidated liquid-liquid dispersion and transfer screen."""
    separation = phase_separation_check(
        N, D_imp, D_tank, rho_c, rho_d, mu_c, sigma_LL, phi_d)
    kLa = liquid_liquid_mass_transfer(
        separation["d32 (m)"], D_mol, rho_c, mu_c, epsilon_kg)
    separation.update({
        "N_min (1/s)": minimum_dispersion_speed(D_imp, sigma_LL, rho_c, phi_d),
        "kLa (1/s)": kLa,
    })
    return separation
