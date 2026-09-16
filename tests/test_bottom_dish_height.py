"""Regression tests for measured reactor bottom-dish heights."""

import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from heat_transfer_core import liquid_height_from_volume as core_liquid_height
from utils.calculations.geometry import dish_geometry, liquid_height_from_volume
from vessel_schematic import _geometry


def test_measured_bottom_dish_height_overrides_dish_type_estimate():
    row = pd.Series({
        "D_tank_m": 0.1,
        "H_m": 0.13,
        "bottom_dish": "Torispherical",
        "top_dish": "Flat",
        "H_bottom_dish_m": 0.01,
        "impeller_count": 0,
    })

    geometry = _geometry(row)
    volume, depth = dish_geometry(0.1, "Torispherical", 0.01)

    assert geometry is not None
    assert geometry["bot_depth"] == 0.01
    assert depth == 0.01
    assert volume > 0


def test_measured_dish_height_is_shared_by_heat_transfer_backend():
    volume_l = 1.0
    shared = liquid_height_from_volume(
        volume_l, 0.18, 0.28, "Torispherical", 0.015)
    core = core_liquid_height(
        volume_l, 0.18, 0.28, "Torispherical", 0.015)

    assert shared == core
    assert shared > 0.015
