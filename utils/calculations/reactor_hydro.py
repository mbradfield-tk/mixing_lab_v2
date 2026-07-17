"""Convenience functions: compute full reactor hydrodynamic parameter set.

This module only orchestrates the primitives defined in hydrodynamics.py,
mixing_times.py, gas_liquid.py and damkohler.py - see those modules for the
per-correlation references and unit conventions.

UNIT NOTE
---------
``eps`` (P/V) is computed in W/m^3 and ``eps_kg`` in W/kg.  van 't Riet kLa is
correctly fed ``eps`` (W/m^3) while all turbulence length/time scales are fed
``eps_kg`` (W/kg).  Do not swap these when extending this function.
"""

import numpy as np

from .hydrodynamics import (
    reynolds_number, power_number_correlation, impeller_power,
    power_per_volume, tip_speed, pumping_number_default, pumping_rate,
    circulation_time, torque, torque_per_volume, edcf, froude_number,
)
from .mixing_times import (
    blend_time_turbulent, micromixing_time_engulfment,
    micromixing_time_local, kolmogorov_length, epsilon_max_estimate,
    average_shear_rate, maximum_shear_rate, shear_stress,
)
from .gas_liquid import kla_vant_riet, kla_surface
from .damkohler import (
    damkohler_macro, damkohler_micro, damkohler_gl, damkohler_sl,
    mixing_sensitivity_assessment,
)


def compute_reactor_hydro(
    N: float, D_imp: float, D_tank: float, H: float,
    rho: float, mu: float,
    Np: float = None, Nq: float = None,
    v_s: float = 0.0, coalescing: bool = True,
    D_mol: float = 2.3e-9,
) -> dict:
    """Return a dictionary of all computed hydrodynamic parameters."""
    V = np.pi / 4 * D_tank**2 * H
    nu = mu / rho if rho > 0 else 0.0
    Re = reynolds_number(N, D_imp, rho, mu) if mu > 0 else 0.0
    if Np is None or (isinstance(Np, float) and np.isnan(Np)):
        Np = power_number_correlation(Re)
    if Nq is None or (isinstance(Nq, float) and np.isnan(Nq)):
        Nq = pumping_number_default()
    P = impeller_power(Np, rho, N, D_imp)
    eps = power_per_volume(P, V) if V > 0 else 0.0
    eps_kg = eps / rho if rho > 0 else 0.0
    u_tip = tip_speed(N, D_imp)
    Q = pumping_rate(Nq, N, D_imp)
    t_blend = blend_time_turbulent(Nq, V, D_imp, N)
    t_micro = micromixing_time_engulfment(eps_kg, nu)
    eta = kolmogorov_length(nu, eps_kg)
    eps_max = epsilon_max_estimate(P, rho, D_imp, N)
    t_micro_local = micromixing_time_local(eps_max, nu)
    gamma_avg = average_shear_rate(P, mu, V)
    gamma_max = maximum_shear_rate(eps_max, nu)
    tau_avg = shear_stress(mu, gamma_avg)
    kla = kla_vant_riet(eps, v_s, coalescing=coalescing)
    kla_surf = kla_surface(eps_kg, nu, D_mol, D_tank, V)
    t_c = circulation_time(Nq, V, D_imp, N)
    _torque = torque(P, N)
    _torque_per_vol = torque_per_volume(P, N, V)
    _edcf = edcf(eps_max, t_c)
    Fr = froude_number(N, D_imp)

    return {
        "Volume (L)": V * 1000,
        "Re": Re,
        "Np": Np,
        "Power (W)": P,
        "P/V (W/m³)": eps,
        "P/V (W/kg)": eps_kg,
        "P/V (W/L)": eps / 1000,
        "Tip speed (m/s)": u_tip,
        "Pumping rate (m³/s)": Q,
        "Blend time 95% (s)": t_blend,
        "Circulation time (s)": t_c,
        "Micromix time t_E (s)": t_micro,
        "Micromix time t_E_local (s)": t_micro_local,
        "Kolmogorov η (µm)": eta * 1e6,
        "ε_max (W/kg)": eps_max,
        "EDCF (W/kg/s)": _edcf,
        "Torque (N·m)": _torque,
        "Torque/V (N·m/m³)": _torque_per_vol,
        "Froude number": Fr,
        "Avg shear rate (1/s)": gamma_avg,
        "Max shear rate (1/s)": gamma_max,
        "Avg shear stress (Pa)": tau_avg,
        "kLa (1/s)": kla,
        "kLa_surface (1/s)": kla_surf,
        "ν (m²/s)": nu,
    }


def compute_damkohler_numbers(t_blend, t_micro, t_rxn,
                               kLa=0.0, kLa_surface=0.0,
                               kLa_SL=0.0):
    """Return Damköhler numbers and assessment string."""
    Da_macro = damkohler_macro(t_blend, t_rxn)
    Da_micro = damkohler_micro(t_micro, t_rxn)
    kLa_eff = max(kLa, kLa_surface)
    Da_gl = damkohler_gl(kLa_eff, t_rxn)
    Da_sl = damkohler_sl(kLa_SL, t_rxn)
    assessment = mixing_sensitivity_assessment(Da_macro, Da_micro, Da_gl, Da_sl)
    return {
        "Da_macro": Da_macro,
        "Da_micro": Da_micro,
        "Da_GL": Da_gl,
        "Da_SL": Da_sl,
        "Assessment": assessment,
    }
