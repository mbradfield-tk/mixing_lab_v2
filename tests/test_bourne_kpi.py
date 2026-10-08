"""Bourne KPI rules (utils.bourne_kpi) and shared reaction-time / mixing-time helpers."""

import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils import bourne_kpi as kpi  # noqa: E402
from utils.calculations import characteristic_reaction_time  # noqa: E402
from utils.calculations.mixing_times import blend_time_turbulent  # noqa: E402


def test_partially_blank_row_is_skipped_not_scored_as_zero():
    df = pd.DataFrame([{"KPI": "Yield", "Unit": "%", "Low speed": np.nan,
                        "Centre": 100.0, "High speed": 101.0}])
    assert kpi.assess_kpis(df, 1) is None
    assert kpi.incomplete_rows(df, 1) == ["Yield (missing Low speed)"]


def test_complete_row_with_blank_noise_columns_assesses_normally():
    df = kpi.new_kpi_df(1)
    df.loc[0, ["Low speed", "Centre", "High speed"]] = [90.0, 100.0, 110.0]
    res = kpi.assess_kpis(df, 1)
    assert res["status"] == "sensitive"
    assert res["incomplete"] == []
    assert "Threshold (%)" in res["table"].columns


def test_noise_columns_exist_in_fresh_table_and_suppress_small_signals():
    df = kpi.new_kpi_df(1)
    assert set(kpi.NOISE_COLUMNS) <= set(df.columns)
    df.loc[0, ["Low speed", "Centre", "High speed", "Std dev", "Replicates"]] = [95.0, 100.0, 105.0, 4.0, 3]
    res = kpi.assess_kpis(df, 1)
    assert res["status"] == "not_sensitive"
    assert res["table"].loc[0, "Sensitive?"] == "No (within noise)"


def test_prefix_quotes_the_kpi_specific_threshold():
    df = pd.DataFrame([{"KPI": "Impurity A", "Unit": "%", "Low speed": 1.0, "Centre": 1.0, "High speed": 1.08}])
    res = kpi.assess_kpis(df, 1)
    assert res["status"] == "not_sensitive"
    assert "≥ 10%" in kpi.kpi_prefix(res)


def test_mirror_keeps_existing_responses_when_kpi_names_match():
    src = pd.DataFrame([{"KPI": "Yield", "Unit": "%"}])
    existing = kpi.new_kpi_df(2, seed_names=[("Yield", "%")])
    existing.loc[0, "Centre"] = 42.0
    out = kpi.mirror_kpis(src, 2, existing)
    assert out.loc[0, "Centre"] == 42.0
    fresh = kpi.mirror_kpis(pd.DataFrame([{"KPI": "Purity", "Unit": "%"}]), 2, existing)
    assert pd.isna(fresh.loc[0, "Centre"]) and fresh.loc[0, "KPI"] == "Purity"


def test_characteristic_reaction_time_is_initial_rate_based():
    t, t90, basis = characteristic_reaction_time("2", 2.0, 1.0)
    assert t == 0.5 and t90 == 4.5 and "90%" in basis
    assert characteristic_reaction_time("1", 4.0)[0] == 0.25
    assert characteristic_reaction_time("0", 2.0, 4.0)[:2] == (2.0, 1.8)
    assert characteristic_reaction_time("2", 2.0, 1.0, 7.5) == (7.5, 7.5, "specified directly")
    assert characteristic_reaction_time("1", 0.0)[0] == 0.0


def test_blend_time_decreases_as_power_number_increases():
    slow = blend_time_turbulent(Np=0.5, N=1.0, D=0.2, T=1.5, H=1.0)
    fast = blend_time_turbulent(Np=5.0, N=1.0, D=0.2, T=1.5, H=1.0)
    assert fast < slow
    assert slow > 0.0
