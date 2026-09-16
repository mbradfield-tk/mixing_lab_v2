"""Regression tests for Vessel Assessment table CSV exports."""

import os
import sys
from types import SimpleNamespace

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pages.vessel_assessment import _build_csv_exports


def test_vessel_assessment_csv_exports_match_current_tables():
    state = SimpleNamespace(
        va_hydro_df=pd.DataFrame({"Parameter": ["Reynolds number"], "Value": ["10000"]}),
        va_dam_df=pd.DataFrame({"Damköhler": ["Da_macro"], "Value": ["0.4"]}),
        va_mt_df=pd.DataFrame({"Transfer path": ["Gas-liquid"]}),
        va_sl_df=pd.DataFrame({"Parameter": ["Solid-liquid kLa_SL"]}),
        va_heat_df=pd.DataFrame({"Parameter": ["Heat generation Q_gen"]}),
    )

    _build_csv_exports(state)

    assert b"Reynolds number" in state.va_hydro_csv
    assert b"Da_macro" in state.va_dam_csv
    assert b"Gas-liquid" in state.va_mt_csv
    assert b"Solid-liquid kLa_SL" in state.va_sl_csv
    assert b"Heat generation Q_gen" in state.va_heat_csv
