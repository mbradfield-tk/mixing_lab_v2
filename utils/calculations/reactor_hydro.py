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


def _resolve(value, fallback):
    """Return ``value`` unless it is None/NaN, in which case call ``fallback``."""
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return fallback()
    return value


def hydro_basics(N: float, D_imp: float, D_tank: float, H: float,
                 rho: float, mu: float, Np: float = None, Nq: float = None,
                 V_m3: float = None) -> dict:
    """Volume, Reynolds number, resolved Np/Nq, power and specific power.

    ``V_m3`` is the actual liquid volume (including the bottom dish); when None the
    flat-bottom cylinder pi/4 D^2 H is used.  ``eps`` is P/V in W/m^3 and ``eps_kg``
    in W/kg; see the module UNIT NOTE.
    """
    V = V_m3 if V_m3 is not None and V_m3 > 0 else np.pi / 4 * D_tank**2 * H
    nu = mu / rho if rho > 0 else 0.0
    Re = reynolds_number(N, D_imp, rho, mu) if mu > 0 else 0.0
    Np = _resolve(Np, lambda: power_number_correlation(Re))
    Nq = _resolve(Nq, pumping_number_default)
    P = impeller_power(Np, rho, N, D_imp)
    eps = power_per_volume(P, V) if V > 0 else 0.0
    eps_kg = eps / rho if rho > 0 else 0.0
    return {"V": V, "nu": nu, "Re": Re, "Np": Np, "Nq": Nq,
            "P": P, "eps": eps, "eps_kg": eps_kg}


def assemble_hydro(b: dict, *, N: float, D_imp: float, mu: float,
                   t_blend: float, eps_max: float, t_micro: float,
                   kla: float, kla_surf: float) -> dict:
    """Build the full hydro result dict from the basics plus the five values a
    reactor-specific (ROM / experimental) correlation may override.

    This is the ONLY place the result keys are defined; every consumer
    (assessment/comparison pages, recorded results, envelopes) relies on them.
    """
    V, nu, P, eps, eps_kg, Nq = b["V"], b["nu"], b["P"], b["eps"], b["eps_kg"], b["Nq"]
    t_c = circulation_time(Nq, V, D_imp, N)
    gamma_avg = average_shear_rate(P, mu, V)
    return {
        "Volume (L)": V * 1000,
        "Re": b["Re"],
        "Np": b["Np"],
        "Power (W)": P,
        "P/V (W/m³)": eps,
        "P/V (W/kg)": eps_kg,
        "P/V (W/L)": eps / 1000,
        "Tip speed (m/s)": tip_speed(N, D_imp),
        "Pumping rate (m³/s)": pumping_rate(Nq, N, D_imp),
        "Blend time 95% (s)": t_blend,
        "Circulation time (s)": t_c,
        "Micromix time t_E (s)": t_micro,
        "Micromix time t_E_local (s)": micromixing_time_local(eps_max, nu),
        "Kolmogorov η (µm)": kolmogorov_length(nu, eps_kg) * 1e6,
        "ε_max (W/kg)": eps_max,
        "EDCF (W/kg/s)": edcf(eps_max, t_c),
        "Torque (N·m)": torque(P, N),
        "Torque/V (N·m/m³)": torque_per_volume(P, N, V),
        "Froude number": froude_number(N, D_imp),
        "Avg shear rate (1/s)": gamma_avg,
        "Max shear rate (1/s)": maximum_shear_rate(eps_max, nu),
        "Avg shear stress (Pa)": shear_stress(mu, gamma_avg),
        "kLa (1/s)": kla,
        "kLa_surface (1/s)": kla_surf,
        "ν (m²/s)": nu,
    }


def compute_reactor_hydro(
    N: float, D_imp: float, D_tank: float, H: float,
    rho: float, mu: float,
    Np: float = None, Nq: float = None,
    v_s: float = 0.0, coalescing: bool = True,
    D_mol: float = 2.3e-9,
    V_m3: float = None,
) -> dict:
    """Return a dictionary of all computed hydrodynamic parameters (literature
    correlations throughout).  Pass ``V_m3`` (actual fill volume) whenever known."""
    b = hydro_basics(N, D_imp, D_tank, H, rho, mu, Np, Nq, V_m3)
    eps_max = epsilon_max_estimate(b["Np"], N, D_imp)
    return assemble_hydro(
        b, N=N, D_imp=D_imp, mu=mu,
        t_blend=blend_time_turbulent(b["Np"], N, D_imp, D_tank, H),
        eps_max=eps_max,
        t_micro=micromixing_time_engulfment(b["eps_kg"], b["nu"]),
        kla=kla_vant_riet(b["eps"], v_s, coalescing=coalescing),
        kla_surf=kla_surface(b["eps_kg"], b["nu"], D_mol, D_tank, b["V"]),
    )


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
