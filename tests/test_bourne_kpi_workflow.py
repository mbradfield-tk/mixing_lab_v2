"""Workflow tests for the Bourne Protocol decision tree and its hand-off to the
Reaction Sensitivity Protocol."""

import csv
import io
import os
import sys
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils import bourne_kpi as kpi
from utils.calculations import characteristic_reaction_time
from pages import bourne_protocol as bp
from pages import mixing_sensitivity as ms


# --- utils/bourne_kpi -----------------------------------------------------------
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


# --- Decision tree ----------------------------------------------------------------
def _state(s1=None, s2=None, s3=None, ratio_rows=None):
    def res(status):
        return None if status is None else {"status": status, "n_sensitive": 1 if status == "sensitive" else 0,
                                            "n_total": 1, "sensitive_names": "Yield (12.0%)" if status == "sensitive" else "",
                                            "results": [{"threshold": 5.0}]}
    hydro = pd.DataFrame(ratio_rows or [{"P/m (W/kg)": 0.02}, {"P/m (W/kg)": 0.2}, {"P/m (W/kg)": 2.0}])
    return SimpleNamespace(
        _gui=None,
        bp_t1_assessed=s1 is not None, bp_t1_result=res(s1), bp_t1_sensitive=s1 == "sensitive",
        bp_t2_assessed=s2 is not None, bp_t2_result=res(s2), bp_t2_sensitive=s2 == "sensitive",
        bp_t3_assessed=s3 is not None, bp_t3_result=res(s3), bp_t3_sensitive=s3 == "sensitive",
        bp_t1_hydro_df=hydro, bp_project_name="P", bp_step_text="3", bp_unit_operation="Reaction",
        bp_process_version="v1", bp_reactor="R", bp_fluid="Water", bp_v_l=1.0,
        bp_sens_csv_ready=False, bp_sens_csv_bytes=b"", bp_sens_csv_name="",
    )


def test_inconclusive_test1_then_insensitive_test2_is_not_micromixing():
    o = bp._protocol_outcome(_state("inconclusive", "not_sensitive"))
    assert o["dominant"] == "Inconclusive"
    assert o["confirmed"] is False


def test_inadequate_range_is_inconclusive_even_when_test2_resolves():
    small = [{"P/m (W/kg)": 0.2}, {"P/m (W/kg)": 0.2}, {"P/m (W/kg)": 0.4}]
    o = bp._protocol_outcome(_state("not_sensitive", "not_sensitive", ratio_rows=small))
    assert o["s1_eff"] == "inconclusive"
    assert o["dominant"] == "Inconclusive"


def test_confirmed_paths():
    assert bp._protocol_outcome(_state("not_sensitive"))["dominant"] == "Mixing-insensitive"
    assert bp._protocol_outcome(_state("sensitive", "not_sensitive"))["dominant"] == "Micromixing"
    assert bp._protocol_outcome(_state("sensitive", "sensitive", "sensitive"))["dominant"] == "Mesomixing"
    assert bp._protocol_outcome(_state("sensitive", "sensitive", "not_sensitive"))["dominant"] == "Macromixing"
    o = bp._protocol_outcome(_state("sensitive", "inconclusive", "sensitive"))
    assert o["dominant"] == "Mesomixing" and o["tentative"] is True


def test_test3_inconclusive_has_its_own_verdict():
    state = _state("sensitive", "sensitive")
    state.bp_t3_kpi_df = pd.DataFrame([
        {"KPI": "Yield", "Unit": "%", "Surface": 90.0, "Mid": 100.0, "Impeller": 110.0},
        {"KPI": "Purity", "Unit": "%", "Surface": 99.5, "Mid": 100.0, "Impeller": 100.5},
    ])
    state.bp_t3_kpi_result_df = pd.DataFrame()
    state.bp_t3_verdict = ""
    state.bp_pdf_ready = True
    bp.on_bp_t3_assess(state)
    assert state.bp_t3_result["status"] == "inconclusive"
    assert "unresolved" in state.bp_t3_verdict.lower()
    assert "macromixing" not in state.bp_t3_verdict.lower().split("unresolved")[0]


def test_summary_bullets_reflect_actual_statuses():
    state = _state("inconclusive", "not_sensitive")
    bp._build_summary(state)
    assert "inconclusive" in state.bp_summary.lower()
    assert "MICROMIXING" not in state.bp_summary


# --- CSV hand-off ---------------------------------------------------------------------
def _export_dict(state) -> dict:
    bp.on_bp_export_sens_csv(state)
    rows = list(csv.reader(io.StringIO(state.bp_sens_csv_bytes.decode("utf-8"))))
    return dict(rows[1:])


def test_inconclusive_test1_exports_as_inconclusive_and_imports_as_such(tmp_path):
    d = _export_dict(_state("inconclusive"))
    assert d["overall_sensitive"] == "inconclusive"
    assert d["test1_status"] == "inconclusive"
    assert d["step_number"] == "3" and d["unit_operation"] == "Reaction"

    path = tmp_path / "b.csv"
    path.write_text("field,value\n" + "\n".join(f"{k},{v}" for k, v in d.items()), encoding="utf-8")
    st = SimpleNamespace(_gui=None, ms_bourne_upload=str(path), ms_bourne_status="", ms_bourne_mech="",
                         ms_bourne_tests=[], ms_bourne_findings_df=pd.DataFrame(), ms_bourne_meta={},
                         ms_bourne_meta_caption="", ms_started=False, ms_project_name="", ms_step_text="",
                         ms_unit_operation=ms.ms_unit_operation_options[0], ms_process_version="")
    ms.on_ms_bourne_import(st)
    assert st.ms_bourne_status.startswith("Ran - inconclusive")
    assert st.ms_project_name == "P" and st.ms_step_text == "3"
    assert st.ms_unit_operation == "Reaction" and st.ms_process_version == "v1"


def test_tentative_mechanism_is_not_exported_as_confirmed():
    d = _export_dict(_state("sensitive", "inconclusive", "sensitive"))
    assert d["overall_sensitive"] == "yes"
    assert d["dominant_mechanism"] == ""
    assert d["dominant_mechanism_tentative"] == "Mesomixing"


def test_pdf_test3_snapshot_uses_user_ratios_in_w_per_kg():
    state = SimpleNamespace(bp_d_imp=0.05, bp_np=5.0, bp_rho=1000.0, bp_v_l=1.0, bp_t1_pm_eff=0.2,
                            bp_t2_feed_vol=100.0, bp_t2_mode="Feed rate", bp_t2_rate=5.0, bp_t2_time=20.0,
                            bp_t3_surface_ratio=0.05, bp_t3_mid_ratio=1.0, bp_t3_impeller_ratio=5.0)
    snap = bp._t3_conditions_snap(state)
    assert [r["eps_loc/eps_avg"] for r in snap["rows"]] == [0.05, 1.0, 5.0]
    assert snap["rows"][1]["eps_loc (W/kg)"] == pytest.approx(0.2, rel=1e-6)


# --- Shared reaction time -------------------------------------------------------------
def test_characteristic_reaction_time_is_initial_rate_based():
    t, t90, basis = characteristic_reaction_time("2", 2.0, 1.0)
    assert t == 0.5 and t90 == 4.5 and "90%" in basis
    assert characteristic_reaction_time("1", 4.0)[0] == 0.25
    assert characteristic_reaction_time("0", 2.0, 4.0)[:2] == (2.0, 1.8)
    assert characteristic_reaction_time("2", 2.0, 1.0, 7.5) == (7.5, 7.5, "specified directly")
    assert characteristic_reaction_time("1", 0.0)[0] == 0.0


def test_step5_classifies_on_initial_time_not_90pct_window():
    st = SimpleNamespace(**{k: getattr(ms, k) for k in dir(ms) if k.startswith("ms_")})
    st._ms_cache = {}
    st.ms_started = True
    st.ms_competing = "No"
    st.ms_rxn_order, st.ms_rxn_k, st.ms_rxn_c0, st.ms_rxn_trxn = "2", 2.0, 1.0, 0.0  # t_rxn = 0.5 s
    ms._recompute(st)
    assert "Fast reaction" in st.ms_step5_assess          # 0.1 <= 0.5 < 1 s band
    assert "t_rxn = 0.5 s" in st.ms_trxn_caption
    assert st._ms_cache["t_rxn"] == 0.5
