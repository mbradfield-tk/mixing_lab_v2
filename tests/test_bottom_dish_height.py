"""Regression tests for measured reactor bottom-dish heights."""

import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from heat_transfer_core import liquid_height_from_volume as core_liquid_height
from utils.calculations.geometry import dish_geometry, liquid_height_from_volume
from vessel_schematic import _geometry


def _full_height_row(top_dish: str) -> pd.Series:
    return pd.Series({
        "D_tank_m": 1.0,
        "L_tan_tan_m": 2.0,
        "H_max_m": 2.25,
        "H_bot_dish_m": 0.25,
        "H_m": 2.8,
        "bottom_dish": "2:1 Elliptical",
        "top_dish": top_dish,
        "impeller_count": 0,
    })


def test_full_height_envelope_is_measured_from_bottom_apex():
    geometry = _geometry(_full_height_row("2:1 Elliptical"))

    assert geometry is not None
    assert geometry["H"] == 2.0
    assert geometry["bot_depth"] == 0.25
    assert geometry["full_height"] == 2.8
    assert geometry["full_top"] == 2.55
    assert geometry["show_full_height"] is True


def test_missing_full_height_does_not_add_reference_envelope():
    row = _full_height_row("")
    row["H_m"] = None

    geometry = _geometry(row)

    assert geometry is not None
    assert geometry["show_full_height"] is False


def test_full_height_corner_is_shown_for_every_top_shape():
    flat = _geometry(_full_height_row("Flat"))
    elliptical = _geometry(_full_height_row("2:1 Elliptical"))
    blank = _geometry(_full_height_row(""))

    assert flat is not None and flat["show_full_height_box"] is True
    assert elliptical is not None and elliptical["show_full_height_box"] is True
    assert blank is not None and blank["show_full_height_box"] is True


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
