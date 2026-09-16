"""Regression tests for Vessel Comparison table CSV exports."""

import os
import sys
from types import SimpleNamespace

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pages.vessel_comparison import _build_csv_exports


def test_vessel_comparison_csv_exports_match_current_tables():
    state = SimpleNamespace(
        vc_summary_df=pd.DataFrame({"Reactor": ["Basis"], "P/V (W/L)": [0.03303]}),
        vc_detail_df=pd.DataFrame({"Corner": ["max RPM / max V"]}),
        vc_rpm_ref_df=pd.DataFrame({"Reactor": ["Basis"], "RPM max": [300]}),
        vc_heat_df=pd.DataFrame({"Assessment": ["Capacity adequate"]}),
        vc_scale_df=pd.DataFrame({"Status": ["Matched"]}),
        vc_scale_full_df=pd.DataFrame({"P/V (W/L)": [0.03303]}),
        vc_scale_pct_df=pd.DataFrame({"P/V (W/L)": ["+0.0%"]}),
        vc_impact_df=pd.DataFrame({"P/V x": [1.0]}),
    )

    _build_csv_exports(state)

    assert b"P/V (W/L)" in state.vc_summary_csv
    assert b"max RPM / max V" in state.vc_detail_csv
    assert b"Capacity adequate" in state.vc_heat_csv
    assert b"Matched" in state.vc_scale_csv
    assert b"+0.0%" in state.vc_scale_pct_csv