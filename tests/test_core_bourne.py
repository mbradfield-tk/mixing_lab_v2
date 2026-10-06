"""Unit tests for core.bourne_plan and the core.bourne_io export/import round trip."""

import io
import os
import sys

import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import bourne_io, bourne_plan as plan
from core.options import BourneStatus, CenterMode
from core.sensitivity_rules import bourne_outcome

SYS = plan.BourneSystem(D_imp=0.05, Np=1.27, rho=997.0, mu=0.00089, D_mol=2.3e-9,
                        V_L=0.1, n_min=50.0, n_max=1500.0, D_tank=0.1, H_liquid=0.08)


def test_n_for_pm_inverts_specific_power():
    n = plan.n_for_pm(0.5, SYS.V_m3, SYS.Np, SYS.D_imp)
    assert plan.specific_power(SYS, n) == pytest.approx(0.5, rel=1e-9)


def test_center_point_is_structured_and_caption_matches():
    c = plan.center_point(SYS, CenterMode.CUSTOM_RPM, 0.0, 2000.0)
    assert c["source"] == "custom_rpm" and c["in_range"] is False and c["n_rpm"] == 2000.0
    pm, info = plan.resolve_center_pm(SYS, CenterMode.CUSTOM_RPM, 0.0, 2000.0)
    assert pm == c["pm"] and "Outside reactor range (50–1500 RPM)" in info
    assert plan.center_point(SYS, CenterMode.CUSTOM_PM, 2.0, 0.0)["in_range"] is None
    assert plan.center_point(SYS, CenterMode.DEFAULT, 0.0, 0.0)["pm"] == plan.DEFAULT_CENTER_PM


def test_test1_conditions_clamp_and_span_100x_when_unclamped():
    rows = plan.test1_conditions(SYS, 0.2)
    pm = [r["P/m (W/kg)"] for r in rows]
    assert all(r["note"] == "" for r in rows)
    assert plan.pm_range_ratio(pm) == pytest.approx(100.0, rel=1e-6)
    tight = plan.BourneSystem(**{**SYS.__dict__, "n_max": 400.0})
    clamped = plan.test1_conditions(tight, 0.2)
    assert clamped[2]["note"] == " (clamped to N_max)" and clamped[2]["N (RPM)"] == 400.0


def test_speed_setpoints_hold_pm_as_volume_grows():
    rows, clamped = plan.speed_setpoints(SYS, 0.2, [("Initial", 0.1), ("Adj. 1", 0.2)])
    assert not clamped
    rpm1, rpm2 = rows[0]["Centre (RPM)"][0], rows[1]["Centre (RPM)"][0]
    assert rpm2 / rpm1 == pytest.approx(2 ** (1 / 3))  # N ∝ V^(1/3) at constant P/m


def test_test2_and_test3_conditions():
    t2 = plan.test2_conditions(90.0, True, 3.0, 0.0)
    assert [r["Feed time (min)"] for r in t2] == pytest.approx([90.0, 30.0, 10.0])
    t3 = plan.test3_conditions(SYS, 0.2, [("Surface", 0.1), ("Impeller zone", 3.0)])
    assert t3[1]["ε_loc (W/kg)"] == pytest.approx(30 * t3[0]["ε_loc (W/kg)"])


def test_export_then_parse_round_trip():
    outcome = bourne_outcome("sensitive", "sensitive", "not_sensitive", ratio=120.0)
    rows = bourne_io.export_rows(
        outcome, {"project_name": "P1", "reactor": "R-1", "fluid": "Water",
                  "working_volume_L": 2.5}, {1: "Yield (12.0%)", 2: "Purity (6.0%)"})
    df = pd.read_csv(io.BytesIO(bourne_io.write_csv(rows)), dtype=str, keep_default_na=False)
    imp = bourne_io.parse(df)
    assert imp["overall"] == "yes" and imp["mechanism"] == "Macromixing"
    assert imp["tests_done"] == [1, 2, 3] and imp["status"] is BourneStatus.CONFIRMED
    assert imp["findings"][0]["Sensitive KPI(s)"] == "Yield (12.0%)"
    assert imp["findings"][2]["Sensitive KPI(s)"] == "None (no KPI over threshold)"
    assert imp["meta"]["working_volume_L"] == "2.5"
    assert "**Project:** P1" in imp["meta_caption"]


def test_parse_rejects_foreign_csv():
    with pytest.raises(ValueError):
        bourne_io.parse(pd.DataFrame({"a": ["x"]}))
    with pytest.raises(ValueError):
        bourne_io.parse(pd.DataFrame({"field": ["record_type"], "value": ["other"]}))
    kpi_table = pd.DataFrame({"KPI": ["Yield (%)"], "Low speed": ["45"], "Sensitive?": ["No"]})
    with pytest.raises(ValueError, match="Generate Sensitivity CSV"):
        bourne_io.parse(kpi_table)
