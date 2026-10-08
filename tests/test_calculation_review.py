"""Regression tests for the corrections made in the 2026 calculation review
(see docs/EQUATIONS_REGISTRY.md)."""

import math
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import units
from utils.calculations import heat_transfer as uht
from utils.calculations.geometry import dish_geometry
from utils.calculations.reactor_hydro import compute_reactor_hydro, hydro_basics


def _klopper_profile_volume(D: float = 1.0, n: int = 20000) -> tuple[float, float]:
    """(depth, volume) of a Klöpper head (crown R = D, knuckle r = 0.1 D) by integration."""
    R, r, a = D, 0.1 * D, D / 2
    # Knuckle/crown tangent point.
    sin_t = (a - r) / (R - r)
    cos_t = math.sqrt(1 - sin_t**2)
    z_t = R * (1 - cos_t)                               # crown depth from apex to tangent
    xc = a - r                                          # knuckle centre radius
    zc = R - (R - r) * cos_t                            # knuckle centre height (from apex)
    depth = zc
    z = np.linspace(0.0, depth, n)
    rad = np.where(z <= z_t, np.sqrt(np.clip(R**2 - (R - z) ** 2, 0, None)),
                   xc + np.sqrt(np.clip(r**2 - (zc - z) ** 2, 0, None)))
    return depth, float(np.trapezoid(np.pi * rad**2, z))


def test_torispherical_head_volume_matches_profile_integration():
    depth, vol = _klopper_profile_volume()
    v_dish, h_dish = dish_geometry(1.0, "Torispherical")
    assert h_dish == pytest.approx(depth, rel=0.01)
    assert v_dish == pytest.approx(vol, rel=0.01)


def test_us_gallons_per_hour_factor():
    assert units._FLOW_RATE["US gal/h"] == pytest.approx(3.785411784e-3 / 3600.0, rel=1e-4)
    assert units._FLOW_RATE["US gal/min (GPM)"] == pytest.approx(3.785411784e-3 / 60.0, rel=1e-4)


def test_heat_generation_is_signed_and_zero_order_counts():
    r = uht.reaction_rate_mol_per_s("1", 0.01, 1.0, 2.0)
    assert uht.heat_generation_rate(-100.0, r) == pytest.approx(2000.0)    # exothermic
    assert uht.heat_generation_rate(50.0, r) == pytest.approx(-1000.0)     # endothermic
    assert uht.reaction_rate_mol_per_s("0", 0.002, 1.0, 3.0) == pytest.approx(0.006)


def test_hausen_laminar_constant():
    htm = {"rho_kg_m3": 1000.0, "mu_Pa_s": 0.05, "Cp_J_kgK": 2000.0, "k_W_mK": 0.1}
    v, d = 0.5, 0.05
    re, pr = 1000.0 * v * d / 0.05, 2000.0 * 0.05 / 0.1
    gz = d / uht.JACKET_PATH_L_M * re * pr
    nu = 3.66 + 0.0668 * gz / (1 + 0.04 * gz ** (2 / 3))
    assert re < 2300
    assert uht.jacket_side_htc(htm, v, d) == pytest.approx(nu * 0.1 / d)


def test_hydro_uses_actual_fill_volume_when_given():
    kw = dict(N=5.0, D_imp=0.05, D_tank=0.1, H=0.08, rho=1000.0, mu=1e-3, Np=1.0)
    cyl = hydro_basics(**kw)["V"]
    assert cyl == pytest.approx(math.pi / 4 * 0.1**2 * 0.08)
    h = compute_reactor_hydro(**kw, V_m3=0.5e-3)
    assert h["Volume (L)"] == pytest.approx(0.5)
    assert h["P/V (W/m³)"] == pytest.approx(h["Power (W)"] / 0.5e-3)
