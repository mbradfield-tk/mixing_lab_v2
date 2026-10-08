"""Vortex surface model (core/vortex.py): Rankine profile, volume conservation, baffling."""

import os
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.vessel_capacity import fill_state, fill_summary, geometry
from core.vortex import G, _bottom_height, _volume, surface_profile, vortex_state

BASE = {"D_tank_m": 0.2, "L_tan_tan_m": 0.3, "bottom_dish": "2:1 Elliptical", "D_imp_m": 0.1,
        "impeller_count": 1, "imp1_clearance_m": 0.03, "N_rpm_min": 50, "N_rpm_max": 600}


def _state(rpm, **extra):
    row = pd.Series({**BASE, **extra})
    geom = geometry(row)
    level = fill_state(geom, 5.0)["level"]
    return geom, level, vortex_state(geom, row, level, rpm)


def test_rankine_profile_is_continuous_and_matches_the_closed_form():
    omega, rc = 20.0, 0.05
    r = np.array([0.0, rc, 0.1])
    z = surface_profile(r, omega, rc)
    assert z[0] == 0.0
    assert z[1] == pytest.approx(omega**2 * rc**2 / (2 * G))
    assert z[2] == pytest.approx(omega**2 * rc**2 / (2 * G) * (2 - rc**2 / 0.1**2))
    # Total depth tends to w^2 rc^2 / g far from the axis.
    assert surface_profile(np.array([10.0]), omega, rc)[0] == pytest.approx(omega**2 * rc**2 / G, rel=1e-4)


@pytest.mark.parametrize("dish", ["Flat", "2:1 Elliptical", "Conical 45°"])
def test_liquid_volume_is_conserved(dish):
    geom, level, v = _state(300, bottom_dish=dish)
    r, s = np.array(v["r_m"]), np.array(v["surface_m"])
    bottom = _bottom_height(r, geom)
    assert _volume(s, r, bottom) == pytest.approx(_volume(np.full_like(r, level), r, bottom), rel=1e-6)
    assert v["centre_mm"] < level * 1000 < v["wall_mm"]


def test_depth_grows_with_speed_and_flags_a_dry_centre():
    depths = [_state(rpm)[2]["depth_mm"] for rpm in (100, 200, 400)]
    assert depths[0] < depths[1] < depths[2]
    assert any("bottom" in w for w in _state(1500)[2]["warnings"])


def test_baffles_set_the_regime():
    assert _state(300, baffles=4)[2]["depth_mm"] == pytest.approx(0.0)
    assert _state(300, baffles=0)[2]["regime"] == "none"
    assert _state(300, baffles=1)[2]["regime"] == "partial"
    assert _state(300)[2]["regime"] == "unknown"


def test_fill_summary_includes_vortex_only_with_rpm():
    row = pd.Series(BASE)
    assert fill_summary(row, 5.0)["vortex"] is None
    v = fill_summary(row, 5.0, rpm=300)["vortex"]
    assert v["depth_mm"] > 0 and "surface_m" not in v
