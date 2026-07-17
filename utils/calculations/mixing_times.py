"""Mixing time calculations: blend time, micromixing, mesomixing, length scales.

UNIT CONVENTION
---------------
The turbulence dissipation rate ``epsilon`` MUST be supplied in W/kg (= m^2/s^3),
i.e. epsilon = (P/V)/rho, NOT the volumetric P/V in W/m^3.  All length scales
return metres, all times return seconds.

REFERENCES (per function)
-------------------------
The micromixing / mesomixing / turbulence-length-scale relations are due to
Baldyga & Bourne and are summarised in the context source:
    Myerson (ed.), *Handbook of Industrial Crystallization*, 3rd ed. (2019),
    Ch. 8 "Mixing and Crystallization" (J. Baldyga).  [in context/]
Primary source: Baldyga & Bourne, *Turbulent Mixing and Chemical Reactions*,
Wiley (1999).

    micromixing_time_engulfment, micromixing_time_local (t_E = 17.3 (nu/eps)^0.5)
        Ref: Baldyga & Bourne (1999); Myerson (2019) Ch. 8.  [in context/]
    mesomixing_time (t_meso = 1.2 (d_feed^2/eps)^(1/3))
        Ref: Baldyga & Bourne (1999); Myerson (2019) Ch. 8.  [in context/]
    kolmogorov_length (eta = (nu^3/eps)^(1/4)),
    batchelor_length (lambda_B = eta Sc^(-1/2))
        Ref: Myerson (2019) Ch. 8 (Baldyga).  [in context/]
    blend_time_turbulent
        The coefficient 5.2 is the Grenville-Nienow turbulent blend-time
        constant, but the published form is N*theta_95 = 5.2 Po^(-1/3)(T/D)^2;
        the V/Q circulation form used here is an approximation.  Ref:
        Grenville (1992); Handbook of Industrial Mixing (2004), Ch. 9.
        [NOT in context/ - verify; formula form differs from published]
    epsilon_max_estimate (eps_max ~ C P/(rho D^3), C~3)
        Ref: Kresta & Wood (1993), Chem. Eng. Sci. 48, 1761.
        [NOT in context/ - verify]
    average_shear_rate (Camp-Stein G = sqrt(P/(mu V))),
    maximum_shear_rate, shear_stress
        Ref: Camp & Stein (1943), J. Boston Soc. Civ. Eng. 30, 219.
        [NOT in context/ - verify]
"""

import numpy as np

from .hydrodynamics import pumping_rate

# Named constants for literature correlations
GRENVILLE_CONSTANT = 5.2        # Grenville (1992) blend-time coefficient
ENGULFMENT_CONSTANT = 17.3      # Baldyga & Bourne engulfment model constant
MESOMIXING_CONSTANT = 1.2       # Baldyga & Bourne mesomixing (inertial-convective) constant
EPSILON_MAX_COEFF = 3.0         # Kresta & Wood ε_max / (P/ρD³) coefficient


def blend_time_turbulent(Nq: float, V: float, D: float, N: float) -> float:
    """
    Macro-blend (95 %) time using the circulation-model approach.
    θ_95 ≈ 5.2 V / (Nq N D³)   (Grenville correlation for turbulent flow)
    """
    Q = pumping_rate(Nq, N, D)
    if Q == 0:
        return np.inf
    return GRENVILLE_CONSTANT * V / Q


def micromixing_time_engulfment(epsilon: float, nu: float) -> float:
    """
    Engulfment micro-mixing time (Baldyga & Bourne).
    t_E = 17.3 (ν / ε)^0.5

    epsilon must be in W/kg (= m²/s³), NOT W/m³.
    """
    if epsilon <= 0:
        return np.inf
    return ENGULFMENT_CONSTANT * np.sqrt(nu / epsilon)


def micromixing_time_local(epsilon_max: float, nu: float) -> float:
    """
    Engulfment micro-mixing time evaluated at the local maximum
    energy-dissipation rate near the impeller.
    t_E_local = 17.3 · (ν / ε_max)^0.5
    """
    if epsilon_max <= 0:
        return np.inf
    return ENGULFMENT_CONSTANT * np.sqrt(nu / epsilon_max)


def mesomixing_time(epsilon: float, d_feed: float) -> float:
    """Mesomixing (turbulent dispersion) time constant.
    t_meso = 1.2 · (d_feed² / ε)^(1/3)
    """
    if epsilon <= 0 or d_feed <= 0:
        return np.inf
    return MESOMIXING_CONSTANT * (d_feed**2 / epsilon) ** (1.0 / 3.0)


def kolmogorov_length(nu: float, epsilon: float) -> float:
    """η = (ν³ / ε)^(1/4).  epsilon must be in W/kg (= m²/s³)."""
    if epsilon <= 0:
        return np.inf
    return (nu**3 / epsilon)**0.25


def batchelor_length(nu: float, epsilon: float, D_mol: float) -> float:
    """λ_B = η · Sc^{-1/2},  Sc = ν / D_mol.  epsilon must be in W/kg."""
    eta = kolmogorov_length(nu, epsilon)
    Sc = nu / D_mol if D_mol > 0 else 1e12
    return eta / np.sqrt(Sc)


def epsilon_max_estimate(P: float, rho: float, D: float, N: float) -> float:
    """
    Local maximum dissipation rate near the impeller (order-of-magnitude).
    ε_max ≈ C · P / (ρ D³), C~3 (Kresta & Wood)
    """
    if D == 0:
        return 0.0
    return EPSILON_MAX_COEFF * P / (rho * D**3)


def average_shear_rate(P: float, mu: float, V: float) -> float:
    """Root-mean-square (Camp-Stein) average shear rate.  γ̇_avg = √(P / (μ · V))"""
    if mu <= 0 or V <= 0:
        return 0.0
    return np.sqrt(P / (mu * V))


def maximum_shear_rate(epsilon_max: float, nu: float) -> float:
    """Maximum shear rate near the impeller.  γ̇_max = √(ε_max / ν)"""
    if nu <= 0 or epsilon_max <= 0:
        return 0.0
    return np.sqrt(epsilon_max / nu)


def shear_stress(mu: float, gamma_dot: float) -> float:
    """Newtonian shear stress  τ = μ · γ̇  (Pa)."""
    return mu * gamma_dot
