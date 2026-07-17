"""Solid-particle hydrodynamics: settling, suspension, mass transfer.

UNIT CONVENTION
---------------
Particle diameter d_p in m, densities in kg/m^3, mu in Pa.s, nu in m^2/s,
impeller diameter D_imp in m; just-suspended speed N_js returned in rev/s.
NOTE: the Zwietering solids loading X is the percent mass ratio (g solid /
100 g liquid) as in the original correlation; gmb_njs uses volume fraction X_v.

REFERENCES (per function)
-------------------------
    settling_velocity (Schiller-Naumann drag)
        Ref: Schiller & Naumann (1933), VDI Z. 77, 318.  [NOT in context/ - verify]
    particle_reynolds, archimedes_number
        Standard dimensionless groups.  [definition]
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
                   rho_L: float, X: float, D_imp: float,
                   g: float = 9.81) -> float:
    """Zwietering (1958) just-suspended speed."""
    if D_imp <= 0 or rho_L <= 0 or X <= 0 or d_p <= 0:
        return 0.0
    return (S * nu**0.1 * d_p**0.2
            * (g * delta_rho / rho_L)**0.45
            * X**0.13 * D_imp**(-0.85))


def gmb_njs(z: float, Np: float, D_imp: float, d_p: float,
            delta_rho: float, rho_L: float, X_v: float,
            C_D_ratio: float, g: float = 9.81) -> float:
    """Grenville, Mak & Brown (2015) just-suspended speed."""
    if D_imp <= 0 or rho_L <= 0 or X_v <= 0 or d_p <= 0 or Np <= 0:
        return 0.0
    return (z * Np**(-1.0/3.0) * D_imp**(-2.0/3.0)
            * (g * delta_rho / rho_L)**0.45
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


def archimedes_number(d_p: float, rho_L: float, delta_rho: float,
                      mu: float, g: float = 9.81) -> float:
    """Archimedes number  Ar = g · d_p³ · ρ_L · Δρ / μ²."""
    if d_p <= 0 or mu <= 0:
        return 0.0
    return g * d_p**3 * rho_L * abs(delta_rho) / mu**2


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
