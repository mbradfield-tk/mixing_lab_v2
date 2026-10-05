"""Fundamental impeller and flow parameters for stirred-tank reactors.

UNIT CONVENTION
---------------
All inputs are SI: rotational speed N in rev/s (= 1/s, NOT rpm), lengths in m,
density rho in kg/m^3, viscosity mu in Pa.s, volume V in m^3, power P in W.
Specific power appears in two forms that MUST NOT be interchanged:
    * P/V in W/m^3  (volumetric)  -> used by van 't Riet kLa (gas_liquid.py)
    * epsilon in W/kg (= m^2/s^3) -> used by all turbulence length/time scales
                                     (mixing_times.py).  epsilon = (P/V)/rho.

REFERENCES (per function)
-------------------------
The context/ folder holds only Myerson (ed.), *Handbook of Industrial
Crystallization*, 3rd ed., Cambridge Univ. Press (2019).  The standard
stirred-tank hydrodynamic relations below are textbook results and are NOT
contained in that source; the canonical reference is given but flagged for
verification.

    reynolds_number, impeller_power (P = Np rho N^3 D^5), power_per_volume,
    tip_speed, pumping_rate (Q = Nq N D^3), circulation_time, torque,
    torque_per_volume, froude_number
        Ref: Paul, Atiemo-Obeng & Kresta (eds.), *Handbook of Industrial
        Mixing*, Wiley (2004), Ch. 6.  [NOT in context/ - verify]
    power_number_correlation
        Three-regime model: laminar Np = K_L/Re (Rushton, Costich & Everett
        1950; Bates, Fondy & Corpstein 1963), turbulent plateau (Paul et al.
        2004, Ch. 6), log-log interpolation in between (approximation).
    edcf (Energy Dissipation / Circulation Function)
        Ref: Middleton, Pierce & Lynch (1986); Bourne (2003).
        [NOT in context/ - verify]
"""

import numpy as np


def reynolds_number(N: float, D: float, rho: float, mu: float) -> float:
    """Impeller Reynolds number  Re = ρ N D² / μ"""
    return rho * N * D**2 / mu


def power_number_correlation(Re: float, Np_turb: float = 5.0, K_L: float = 70.0,
                             Re_lam: float = 10.0, Re_turb: float = 1.0e4) -> float:
    """Power number across the laminar, transitional and turbulent regimes.

    Used only when a vessel has no measured ``Np``; the defaults describe a
    six-blade Rushton turbine in a baffled tank.

    * Laminar (Re <= Re_lam):  Np = K_L / Re   (Np*Re = const). K_L ≈ 70 for the
      Rushton turbine — Rushton, Costich & Everett (1950), Chem. Eng. Prog.
      46(8):395 & 46(9):467; Bates, Fondy & Corpstein (1963), Ind. Eng. Chem.
      Process Des. Dev. 2(4):310.
    * Turbulent (Re >= Re_turb): Np = Np_turb (constant plateau; Paul,
      Atiemo-Obeng & Kresta (eds.), Handbook of Industrial Mixing (2004), Ch. 6,
      which also gives the Re ≈ 10 and Re ≈ 1e4 regime boundaries).
    * Transitional: power-law (log-log linear) interpolation between the two
      asymptotes. This is an approximation of the measured curve, which for a
      baffled Rushton turbine passes through a shallow minimum near Re ≈ 1e2-1e3.
    """
    if Re <= 0 or not np.isfinite(Re):
        return Np_turb
    Np_lam_end = K_L / Re_lam
    if Re <= Re_lam:
        return K_L / Re
    if Re >= Re_turb:
        return Np_turb
    frac = np.log(Re / Re_lam) / np.log(Re_turb / Re_lam)
    return float(Np_lam_end * (Np_turb / Np_lam_end) ** frac)


def impeller_power(Np: float, rho: float, N: float, D: float) -> float:
    """P = Np ρ N³ D⁵"""
    return Np * rho * N**3 * D**5


def power_per_volume(P: float, V: float) -> float:
    """ε = P / V  (W m⁻³)"""
    return P / V


def tip_speed(N: float, D: float) -> float:
    """u_tip = π N D"""
    return np.pi * N * D


def pumping_number_default() -> float:
    """Typical Nq for a pitched-blade turbine (down-pumping)."""
    return 0.79


def pumping_rate(Nq: float, N: float, D: float) -> float:
    """Q = Nq N D³"""
    return Nq * N * D**3


def circulation_time(Nq: float, V: float, D: float, N: float) -> float:
    """Circulation time  t_c = V / (Nq · N · D³)."""
    Q = pumping_rate(Nq, N, D)
    if Q <= 0:
        return np.inf
    return V / Q


def torque(P: float, N: float) -> float:
    """Impeller torque  Λ = P / (2π N)  (N·m)."""
    if N <= 0:
        return 0.0
    return P / (2 * np.pi * N)


def torque_per_volume(P: float, N: float, V: float) -> float:
    """Torque per unit volume  Λ/V  (N·m / m³)."""
    if N <= 0 or V <= 0:
        return 0.0
    return torque(P, N) / V


def edcf(epsilon_max: float, t_c: float) -> float:
    """Energy Dissipation Circulation Function  EDCF = ε_max / t_c  (W/kg/s)."""
    if t_c <= 0 or t_c == np.inf:
        return 0.0
    return epsilon_max / t_c


def froude_number(N: float, D: float, g: float = 9.81) -> float:
    """Froude number  Fr = N² D / g."""
    if g <= 0:
        return 0.0
    return N**2 * D / g
