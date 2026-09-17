"""Regression tests for Heat Transfer table CSV exports."""

import os
import sys
from types import SimpleNamespace

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pages.heat_transfer import _build_csv_exports


def test_heat_transfer_csv_exports_match_current_tables():
    state = SimpleNamespace(
        rxn_summary_df=pd.DataFrame({"Metric": ["Peak temperature"]}),
        kpi_df=pd.DataFrame({"Metric": ["U (W/m2.K)"]}),
        corr_df=pd.DataFrame({"Correlation": ["Dittus-Boelter"]}),
        htm_compare_df=pd.DataFrame({"Medium": ["Water"]}),
        summary_df=pd.DataFrame({"Metric": ["Time to target"]}),
    )

    _build_csv_exports(state)

    assert b"Peak temperature" in state.rxn_summary_csv
    assert b"U (W/m2.K)" in state.kpi_csv
    assert b"Dittus-Boelter" in state.corr_csv
    assert b"Water" in state.htm_compare_csv
    assert b"Time to target" in state.summary_csv
