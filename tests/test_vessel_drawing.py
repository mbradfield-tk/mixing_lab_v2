"""Interactive schematic data (core.vessel_capacity): head profiles and drawing payload."""

import os
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.vessel_capacity import Head, dish_kind, drawing_data, impeller_style


@pytest.mark.parametrize("kind, natural", [("torispherical", 0.169), ("klopper", 0.194), ("korbbogen", 0.255)])
def test_torispherical_heads_have_their_standard_depth_and_invert(kind, natural):
    head = Head(kind, R=0.5, depth=0.17)
    assert head.h_nat == pytest.approx(natural, abs=2e-3)  # depth / D for D = 1 m
    assert head.drop(0.0) == pytest.approx(0.17) and head.drop(0.5) == pytest.approx(0.0, abs=1e-6)
    for r in np.linspace(0.05, 0.45, 9):
        assert head.radius(head.drop(r)) == pytest.approx(r, rel=1e-6)


def test_dish_labels_map_to_profiles():
    assert dish_kind("DIN Torispherical") == "klopper"
    assert dish_kind("Torispherical") == "torispherical"
    assert dish_kind("2:1 Elliptical") == "ellipsoidal"
    assert dish_kind("45 deg conical") == "cone"
    assert dish_kind("") == "flat"


def test_impeller_labels_give_style_blades_and_angle():
    assert impeller_style("PBT, 45° (4)") == {"style": "pitched", "blades": 4, "angle_deg": 45.0}
    assert impeller_style("Rushton gassing")["style"] == "rushton"
    assert impeller_style("Optifoil, 30° (3)")["style"] == "hydrofoil"
    assert impeller_style("Half-moon")["style"] == "halfmoon"


def test_drawing_payload_has_a_monotone_capacity_curve_and_vortex():
    row = pd.Series({"D_tank_m": 0.2, "L_tan_tan_m": 0.3, "bottom_dish": "Torispherical",
                     "D_imp_m": 0.1, "impeller_count": 1, "imp1_clearance_m": 0.03,
                     "impeller_type": "PBT, 45° (4)", "baffles": 0})
    d = drawing_data(row, 5.0, 300)
    z, v = d["capacity"]["z_mm"], d["capacity"]["V_L"]
    assert z[0] == pytest.approx(-d["bot_depth_mm"]) and z[-1] == pytest.approx(300.0)
    assert all(b >= a for a, b in zip(v, v[1:])) and v[-1] == pytest.approx(d["total_L"])
    assert d["bottom"][-1] == [pytest.approx(100.0), pytest.approx(0.0, abs=1e-3)]
    assert d["impellers"][0]["style"] == "pitched" and d["vortex"]["r_mm"][-1] == pytest.approx(100.0)
    assert drawing_data(pd.Series({"D_tank_m": 0.0}), None) is None
