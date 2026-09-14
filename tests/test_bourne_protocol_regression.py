import os
import sys
from types import SimpleNamespace

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pages.bourne_protocol import (
    _assess_kpis,
    _assess_with_threshold,
    _build_t2,
    _invalidate_assessments,
    _new_kpi_df,
)
from pages.mixing_sensitivity import _build_verdict
from utils.calculations.mixing_times import blend_time_turbulent


def test_blend_time_decreases_as_flow_number_increases():
    slow = blend_time_turbulent(Np=5.0, N=1.0, D=0.2, T=1.5, H=1.0, Nq=0.5)
    fast = blend_time_turbulent(Np=5.0, N=1.0, D=0.2, T=1.5, H=1.0, Nq=1.5)
    assert fast < slow
    assert slow > 0.0


def test_blank_kpi_values_are_missing_not_zeroed():
    df = _new_kpi_df(1)
    assert pd.isna(df.loc[0, "Low speed"])
    assert pd.isna(df.loc[0, "Centre"])
    assert pd.isna(df.loc[0, "High speed"])


def test_mixed_kpi_signal_is_inconclusive_not_confirmed_sensitive():
    df = pd.DataFrame([
        {"KPI": "Yield", "Unit": "%", "Low speed": 95.0, "Centre": 100.0, "High speed": 105.0},
        {"KPI": "Purity", "Unit": "%", "Low speed": 99.0, "Centre": 100.0, "High speed": 101.0},
    ])
    res = _assess_kpis(df, 1)
    assert res is not None
    assert res["status"] == "inconclusive"
    assert res["sensitive"] is False


def test_critical_kpi_override_is_sensitive_even_if_secondary_kpis_are_not():
    df = pd.DataFrame([
        {"KPI": "Impurity level", "Unit": "ppm", "Low speed": 10.0, "Centre": 100.0, "High speed": 190.0},
        {"KPI": "Yield", "Unit": "%", "Low speed": 99.0, "Centre": 100.0, "High speed": 101.0},
    ])
    res = _assess_kpis(df, 1)
    assert res is not None
    assert res["status"] == "sensitive"
    assert res["sensitive"] is True


def test_kpi_specific_threshold_is_respected():
    df = pd.DataFrame([
        {"KPI": "Impurity level", "Unit": "ppm", "Low speed": 20.0, "Centre": 100.0, "High speed": 110.0},
    ])
    res = _assess_kpis(df, 1)
    assert res is not None
    assert res["status"] == "sensitive"
    assert res["results"][0]["max_pct"] >= 10.0


def test_test2_conditions_are_ordered_slow_center_fast():
    state = SimpleNamespace(bp_t2_feed_vol=100.0, bp_t2_mode="Feed rate", bp_t2_rate=5.0, bp_t2_time=20.0)
    _build_t2(state)
    assert [row["Condition"] for _, row in state.bp_t2_cond_df.iterrows()] == [
        "Slow (1/3× rate)",
        "Centre",
        "Fast (3× rate)",
    ]


def test_near_zero_center_does_not_force_100pct_change():
    max_pct, sensitive = _assess_with_threshold(0.0, 0.0, 0.1, threshold=5.0)
    assert max_pct < 100.0
    assert sensitive is True


def test_unknown_data_overrides_low_risk_verdict():
    verdict, kind = _build_verdict(
        b_sensitive=False,
        b_mechs=[],
        b_done=True,
        findings=[
            ("Kinetics", "⚪ Unknown", "Reaction kinetics not available."),
            ("Heat transfer", "⚪ Unknown", "No ΔH data available."),
        ],
        competing="No",
    )
    assert "Incomplete assessment" in verdict
    assert kind == "warning"


def test_upstream_input_change_invalidates_assessments():
    state = SimpleNamespace(
        bp_t1_assessed=True,
        bp_t1_sensitive=True,
        bp_t1_result={"status": "sensitive"},
        bp_t1_verdict="Sensitive",
        bp_t2_assessed=True,
        bp_t2_sensitive=False,
        bp_t2_result={"status": "not_sensitive"},
        bp_t2_verdict="Not sensitive",
        bp_t3_assessed=True,
        bp_t3_sensitive=True,
        bp_t3_result={"status": "sensitive"},
        bp_t3_verdict="Sensitive",
        bp_show_t2=True,
        bp_show_t3=True,
        bp_pdf_ready=True,
        bp_sens_csv_ready=True,
        bp_status="Protocol started. Run Test 1 conditions and enter the responses.",
    )

    _invalidate_assessments(state)

    assert state.bp_t1_assessed is False
    assert state.bp_t1_result is None
    assert state.bp_t2_assessed is False
    assert state.bp_t3_assessed is False
    assert state.bp_show_t2 is False
    assert state.bp_show_t3 is False
    assert state.bp_pdf_ready is False
    assert state.bp_sens_csv_ready is False
    assert "reassessment required" in state.bp_status.lower()
