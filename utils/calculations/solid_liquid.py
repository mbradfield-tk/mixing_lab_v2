"""Solid-particle hydrodynamics: settling, suspension, mass transfer.

UNIT CONVENTION
---------------
Particle diameter d_p in m, densities in kg/m^3, mu in Pa.s, nu in m^2/s,
impeller diameter D_imp in m; just-suspended speed N_js returned in rev/s.
NOTE: the Zwietering solids loading X is the percent mass ratio (g solid /
100 g liquid) as in the original correlation; gmb_njs uses the volume
percentage X_v (volume of particles / volume of slurry, %).

REFERENCES (per function)
-------------------------
    settling_velocity (Schiller-Naumann drag)
        Ref: Schiller & Naumann (1935), VDI-Zeitschrift 77, 318-320.  [NOT in context/]
    particle_reynolds
        Standard dimensionless group.  [definition]
    zwietering_njs (N_js = S nu^0.1 d_p^0.2 (g dRho/rho)^0.45 X^0.13 D^-0.85)
        Ref: Zwietering (1958), Chem. Eng. Sci. 8, 244-253.
        Cited in context: Myerson (2019) Ch. 10 (Crystallizer Mixing /
        Suspension Criterion).  [in context/]
    gmb_njs (Grenville, Mak & Brown)
        Ref: Grenville, Mak & Brown (2015), Chem. Eng. Res. Des. 100, 282.
        [NOT in context/ - verify]
    solid_liquid_mass_transfer (Sh = 2 + 0.6 Re_p^0.5 Sc^(1/3))
        Ref: Ranz & Marshall (1952), Chem. Eng. Prog. 48, 141.
        [NOT in context/ - verify]
    solid_liquid_kla (a_s = 6 phi_s / d_p)
        Specific-area definition for monodisperse spheres.  [definition]
    particle_suspension_criterion
        Qualitative N/N_js bands are heuristic.  [SOURCE MISSING - heuristic]
    settling_class / suspension_state
        Settling-velocity classes: Gates, Morton & Fondy (1976), Chem. Eng. 83(11), 144.
"""

import numpy as np


def settling_velocity(d_p: float, rho_p: float, rho_L: float,
                      mu: float, phi: float = 1.0) -> float:
    """Terminal settling velocity with Schiller-Naumann drag correction."""
    if d_p <= 0 or mu <= 0 or rho_L <= 0 or phi <= 0:
        return 0.0
    g = 9.81
    delta_rho = abs(rho_p - rho_L)
    v_stokes = (d_p**2 * g * delta_rho) / (18 * mu)
    v_stokes *= phi
    v_t = v_stokes
    for _ in range(20):
        Re_p = rho_L * v_t * d_p / mu
        if Re_p < 0.1:
            break
        Cd_corr = (24 / Re_p) * (1 + 0.15 * Re_p**0.687)
        v_t_new = np.sqrt(4 * g * d_p * delta_rho / (3 * Cd_corr * rho_L))
        v_t_new *= phi
        if abs(v_t_new - v_t) / max(v_t, 1e-30) < 1e-6:
            v_t = v_t_new
            break
        v_t = v_t_new
    return v_t


def particle_reynolds(d_p: float, v_t: float, rho_L: float,
                      mu: float) -> float:
    """Particle Reynolds number  Re_p = ρ_L · v_t · d_p / μ."""
    if mu <= 0:
        return 0.0
    return rho_L * v_t * d_p / mu


def zwietering_njs(S: float, nu: float, d_p: float, delta_rho: float,
                   rho_L: float, X_wt_pct: float, D_imp: float,
                   g: float = 9.81) -> float:
    """Zwietering (1958) just-suspended speed N_js (rev/s).

    N_js = S ν^0.1 d_p^0.2 (g Δρ/ρ_L)^0.45 X^0.13 D^-0.85 with ``nu`` in m²/s,
    ``d_p`` in m, densities in kg/m³, ``D_imp`` in m and ``X_wt_pct`` the solids
    loading in **wt-% (0–100, g solid per 100 g liquid)** — the form used by
    Zwietering; passing a mass fraction (0–1) under-predicts N_js by ~1.8×.
    """
    if D_imp <= 0 or rho_L <= 0 or X_wt_pct <= 0 or d_p <= 0:
        return 0.0
    return (S * nu**0.1 * d_p**0.2
            * (g * delta_rho / rho_L)**0.45
            * X_wt_pct**0.13 * D_imp**(-0.85))


def gmb_njs(z: float, Np: float, D_imp: float, d_p: float,
            delta_rho: float, rho_L: float, X_v: float,
            C_D_ratio: float, g: float = 9.81) -> float:
    """Grenville, Mak & Brown (2015) just-suspended speed N_js (rev/s).

    ``X_v`` is the solids volume fraction expressed in **percent** (volume of
    particles / volume of slurry × 100), as defined in the paper.
    """
    if D_imp <= 0 or rho_L <= 0 or X_v <= 0 or d_p <= 0 or Np <= 0:
        return 0.0
    return (z * Np**(-1.0/3.0) * D_imp**(-2.0/3.0)
            * (g * delta_rho / rho_L)**0.5
            * X_v**0.154 * d_p**0.167
            * C_D_ratio**0.1)


def solid_liquid_mass_transfer(d_p: float, v_slip: float, rho_L: float,
                               mu: float, D_mol: float) -> float:
    """Solid-liquid mass transfer coefficient via Ranz-Marshall."""
    if d_p <= 0 or mu <= 0 or D_mol <= 0:
        return 0.0
    Re_p = rho_L * v_slip * d_p / mu
    nu_val = mu / rho_L
    Sc = nu_val / D_mol if D_mol > 0 else 1e12
    Sh = 2.0 + 0.6 * np.sqrt(max(Re_p, 0)) * Sc**(1.0/3.0)
    return Sh * D_mol / d_p


def solid_liquid_kla(k_SL: float, d_p: float, phi_s: float) -> float:
    """Solid-liquid volumetric mass-transfer coefficient kLa_SL."""
    if d_p <= 0 or phi_s <= 0 or k_SL <= 0:
        return 0.0
    a_s = 6.0 * phi_s / d_p
    return k_SL * a_s


def particle_suspension_criterion(N: float, N_js: float) -> str:
    """Qualitative suspension assessment based on N / N_js ratio."""
    if N_js <= 0:
        return "N/A"
    ratio = N / N_js
    if ratio < 0.7:
        return f"Poorly suspended (N/Njs={ratio:.2f})"
    elif ratio < 1.0:
        return f"Partially suspended (N/Njs={ratio:.2f})"
    elif ratio < 1.3:
        return f"Just suspended (N/Njs={ratio:.2f})"
    else:
        return f"Fully suspended (N/Njs={ratio:.2f})"


# Settling-velocity classes (m/s) after Gates, Morton & Fondy (1976), Chem. Eng. 83(11), 144:
# slow-settling solids are 0.1-0.6 ft/min (0.0005-0.003 m/s), moderate 4-8 ft/min, fast 16-60 ft/min.
SETTLING_VERY_SLOW = 0.0005
SETTLING_SLOW = 0.003
SETTLING_MODERATE = 0.02


def settling_class(v_t: float) -> tuple[str, str]:
    """(kind, label) of a terminal settling velocity."""
    if v_t <= 0:
        return "unknown", "Unknown"
    if v_t < SETTLING_VERY_SLOW:
        return "ok", "Very slow settling (< 0.5 mm/s)"
    if v_t < SETTLING_SLOW:
        return "ok", "Slow settling (0.5–3 mm/s)"
    if v_t < SETTLING_MODERATE:
        return "warning", "Moderate settling (3–20 mm/s)"
    return "critical", "Fast settling (> 20 mm/s)"


def suspension_state(N: float, N_js: float, v_t: float) -> str:
    """"<status> - <reason>": N ≥ N_js decides first; below N_js, slow settling makes poor
    suspension unlikely (the N_js correlations are fitted to faster-settling particles), but a
    settled bed still needs a minimum speed to lift off, so it is not ruled out."""
    ratio = N / N_js if N_js > 0 else 0.0
    if ratio >= 1.3:
        return "Fully suspended - N > 1.3·N_js"
    if ratio >= 1.0:
        return "Just suspended - N > N_js with little margin; aim for N ≥ 1.3·N_js"
    if 0 < v_t < SETTLING_VERY_SLOW:
        return ("Unlikely limiting - very slow settling (v_t < 0.5 mm/s), although N < N_js; "
                "confirm the solids lift off the base at start-up")
    if 0 < v_t < SETTLING_SLOW:
        return ("Likely suspended - slow settling (v_t < 3 mm/s), although N < N_js; the N_js "
                "correlations are conservative here")
    if N_js <= 0:
        return "N/A"
    if ratio < 0.7:
        return "Poorly suspended - N < 0.7·N_js"
    return "Partially suspended - N < N_js"
