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
    _refresh_table_csv_exports,
)
from pages.mixing_sensitivity import (
    _build_verdict,
    _damkohler_screening_note,
    _heat_transfer_summary,
    _mesomixing_risk,
    _reaction_timescale_profile,
    on_ms_update_assessment,
    on_ms_bourne_import,
)
from utils.calculations.mixing_times import blend_time_turbulent


def test_blend_time_decreases_as_power_number_increases():
    slow = blend_time_turbulent(Np=0.5, N=1.0, D=0.2, T=1.5, H=1.0)
    fast = blend_time_turbulent(Np=5.0, N=1.0, D=0.2, T=1.5, H=1.0)
    assert fast < slow
    assert slow > 0.0


def test_blank_kpi_values_are_missing_not_zeroed():
    df = _new_kpi_df(1)
    assert pd.isna(df.loc[0, "Low speed"])
    assert pd.isna(df.loc[0, "Centre"])
    assert pd.isna(df.loc[0, "High speed"])


def test_bourne_table_exports_reflect_current_results():
    state = SimpleNamespace(
        bp_t1_hydro_df=pd.DataFrame({"Condition": ["Centre"], "P/m (W/kg)": [0.2]}),
        bp_t1_adj_result_df=pd.DataFrame(),
        bp_t1_kpi_result_df=pd.DataFrame({"KPI": ["Yield"], "Sensitive?": ["Yes"]}),
        bp_t2_cond_df=pd.DataFrame(),
        bp_t2_kpi_result_df=pd.DataFrame(),
        bp_t3_cond_df=pd.DataFrame(),
        bp_t3_kpi_result_df=pd.DataFrame(),
    )

    _refresh_table_csv_exports(state)

    assert b"P/m (W/kg)" in state.bp_t1_conditions_csv
    assert b"Yield" in state.bp_t1_results_csv


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


def test_inconclusive_test1_keeps_protocol_open_for_more_testing():
    state = SimpleNamespace(
        _gui=None,
        bp_t1_kpi_df=pd.DataFrame([
            {"KPI": "Yield", "Unit": "%", "Low speed": 90.0, "Centre": 100.0, "High speed": 116.7},
            {"KPI": "Purity", "Unit": "%", "Low speed": 99.0, "Centre": 100.0, "High speed": 101.0},
        ]),
        bp_t1_kpi_result_df=pd.DataFrame(),
        bp_t1_result=None,
        bp_t1_assessed=False,
        bp_t1_sensitive=False,
        bp_t1_verdict="",
        bp_t2_assessed=False,
        bp_t2_sensitive=False,
        bp_t2_result=None,
        bp_t2_verdict="",
        bp_show_t2=False,
        bp_t2_kpi_df=pd.DataFrame(),
        bp_show_t3=False,
        bp_t3_assessed=False,
        bp_t3_sensitive=False,
        bp_t3_result=None,
        bp_t3_verdict="",
    )
    state.bp_show_summary = False
    from pages.bourne_protocol import on_bp_t1_assess
    on_bp_t1_assess(state)
    assert state.bp_t1_assessed is True
    assert state.bp_t1_result["status"] == "inconclusive"
    assert state.bp_show_t2 is True
    assert "Proceed to **Test 2**" in state.bp_t1_verdict


def test_inadequate_test1_range_is_not_treated_as_definitively_insensitive():
    state = SimpleNamespace(
        _gui=None,
        bp_t1_kpi_df=pd.DataFrame([
            {"KPI": "Yield", "Unit": "%", "Low speed": 100.0, "Centre": 100.0, "High speed": 101.0},
        ]),
        bp_t1_hydro_df=pd.DataFrame([
            {"Condition": "Low (0.1× P/m)", "P/m (W/kg)": 0.2},
            {"Condition": "Centre (1× P/m)", "P/m (W/kg)": 0.2},
            {"Condition": "High (10× P/m)", "P/m (W/kg)": 0.4},
        ]),
        bp_t1_kpi_result_df=pd.DataFrame(),
        bp_t1_result=None,
        bp_t1_assessed=False,
        bp_t1_sensitive=False,
        bp_t1_verdict="",
        bp_t2_assessed=False,
        bp_t2_sensitive=False,
        bp_t2_result=None,
        bp_t2_verdict="",
        bp_show_t2=False,
        bp_t2_kpi_df=pd.DataFrame(),
        bp_show_t3=False,
        bp_t3_assessed=False,
        bp_t3_sensitive=False,
        bp_t3_result=None,
        bp_t3_verdict="",
    )
    from pages.bourne_protocol import on_bp_t1_assess
    on_bp_t1_assess(state)
    assert state.bp_t1_result["status"] == "not_sensitive"
    assert state.bp_show_t2 is True
    assert "tested range" in state.bp_t1_verdict.lower()


def test_editing_test2_results_keeps_protocol_on_test_2():
    state = SimpleNamespace(
        _gui=None,
        bp_t1_assessed=True,
        bp_t1_sensitive=True,
        bp_t1_verdict="Test 1 assessed",
        bp_show_t2=True,
        bp_t2_assessed=True,
        bp_t2_sensitive=True,
        bp_t2_result={"status": "sensitive", "n_sensitive": 1, "n_total": 1},
        bp_t2_verdict="Test 2 assessed",
        bp_t2_kpi_df=pd.DataFrame([
            {"KPI": "Yield", "Unit": "%", "Slow feed": 90.0, "Centre": 100.0, "Fast feed": 110.0},
        ]),
        bp_t2_kpi_result_df=pd.DataFrame(),
        bp_show_t3=True,
        bp_t3_assessed=False,
        bp_t3_sensitive=False,
        bp_t3_result=None,
        bp_t3_verdict="",
    )
    from pages.bourne_protocol import on_bp_t2_kpi_edit
    on_bp_t2_kpi_edit(state, "bp_t2_kpi_df", {"index": 0, "col": "Centre", "value": 90.0})
    assert state.bp_t1_assessed is True
    assert state.bp_show_t2 is True
    assert state.bp_t2_assessed is False


def test_mechanism_language_uses_consistent_with_not_definitive_labels():
    state = SimpleNamespace(
        _gui=None,
        bp_t1_assessed=True,
        bp_t1_sensitive=True,
        bp_t1_result={"status": "sensitive", "n_sensitive": 1, "n_total": 1},
        bp_t2_assessed=False,
        bp_t2_sensitive=False,
        bp_t2_result=None,
        bp_t2_verdict="",
        bp_show_t2=True,
        bp_t2_kpi_df=pd.DataFrame([
            {"KPI": "Yield", "Unit": "%", "Slow feed": 90.0, "Centre": 100.0, "Fast feed": 110.0},
        ]),
        bp_t2_kpi_result_df=pd.DataFrame(),
        bp_show_t3=False,
        bp_t3_assessed=False,
        bp_t3_sensitive=False,
        bp_t3_result=None,
        bp_t3_verdict="",
        bp_t3_kpi_df=pd.DataFrame(),
    )
    from pages.bourne_protocol import on_bp_t2_assess
    on_bp_t2_assess(state)
    assert "consistent with" in state.bp_t2_verdict.lower()
    assert "mesomixing" in state.bp_t2_verdict.lower()

    state2 = SimpleNamespace(
        _gui=None,
        bp_t1_assessed=True,
        bp_t1_sensitive=True,
        bp_t2_assessed=True,
        bp_t2_sensitive=True,
        bp_t2_result={"status": "sensitive", "n_sensitive": 1, "n_total": 1},
        bp_t2_verdict="",
        bp_show_t2=True,
        bp_t3_assessed=False,
        bp_t3_sensitive=False,
        bp_t3_result=None,
        bp_t3_verdict="",
        bp_t3_kpi_df=pd.DataFrame([
            {"KPI": "Yield", "Unit": "%", "Surface": 90.0, "Mid": 100.0, "Impeller": 120.0},
        ]),
        bp_t3_kpi_result_df=pd.DataFrame(),
    )
    from pages.bourne_protocol import on_bp_t3_assess
    on_bp_t3_assess(state2)
    assert "consistent with" in state2.bp_t3_verdict.lower()
    assert "mesomixing" in state2.bp_t3_verdict.lower()


def test_reaction_time_bands_are_preliminary_and_direct_to_damkohler():
    note = _damkohler_screening_note(0.05)
    assert "preliminary screening heuristic" in note.lower()
    assert "Da_macro" in note and "Da_micro" in note


def test_reaction_timescale_profile_uses_process_window_for_supported_orders():
    initial, worst, basis = _reaction_timescale_profile("1", 2.0, 1.0)
    assert initial == 0.5
    assert worst > initial
    assert "90%" in basis

    initial, worst, _ = _reaction_timescale_profile("2", 2.0, 4.0)
    assert initial == 0.125
    assert worst == 1.125

    initial, worst, _ = _reaction_timescale_profile("0", 2.0, 4.0)
    assert initial == 2.0
    assert worst == 1.8


def test_reaction_timescale_profile_preserves_direct_override():
    assert _reaction_timescale_profile("2", 2.0, 4.0, 7.5) == (
        7.5, 7.5, "specified directly")


def test_update_assessment_preserves_inputs_and_recomputes(monkeypatch):
    import pages.mixing_sensitivity as mixing_sensitivity

    calls = []

    def fake_recompute(state):
        calls.append(state)

    monkeypatch.setattr(mixing_sensitivity, "_safe_recompute", fake_recompute)
    monkeypatch.setattr(mixing_sensitivity, "notify", lambda *args: None)
    state = SimpleNamespace(
        ms_started=False,
        ms_reaction="Selected reaction",
        ms_rxn_k=2.0,
        ms_phases=["Liquid", "Solid"],
        ms_pdf_ready=True,
        ms_pdf_bytes=b"old report",
    )

    on_ms_update_assessment(state)

    assert state.ms_started is True
    assert state.ms_pdf_ready is False
    assert state.ms_pdf_bytes == b""
    assert state.ms_reaction == "Selected reaction"
    assert state.ms_rxn_k == 2.0
    assert state.ms_phases == ["Liquid", "Solid"]
    assert calls == [state]


def test_semi_batch_requires_feed_zone_assessment_not_auto_sensitive():
    meso_sensitive, require_feed_zone = _mesomixing_risk("No", True)
    assert meso_sensitive is False
    assert require_feed_zone is True

    meso_sensitive, require_feed_zone = _mesomixing_risk("Yes", True)
    assert meso_sensitive is True
    assert require_feed_zone is False


def test_thermal_severity_is_separate_from_heat_transfer_capability():
    exo = _heat_transfer_summary(-100.0, 150.0)
    assert "thermal severity" in exo.lower()
    assert "cooling" in exo.lower()
    assert "runaway" in exo.lower()

    endo = _heat_transfer_summary(80.0, 60.0)
    assert "endothermic" in endo.lower()
    assert "heat input" in endo.lower()


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


def test_bourne_metadata_is_preserved_structurally_on_import(tmp_path):
    csv_path = tmp_path / "bourne_results.csv"
    csv_path.write_text(
        "field,value\n"
        "record_type,bourne_results\n"
        "project_name,Demo Project\n"
        "reactor,EasyMax 102\n"
        "fluid,Water\n"
        "test1_assessed,yes\n"
        "test2_assessed,no\n"
        "test3_assessed,no\n"
        "overall_sensitive,yes\n"
        "dominant_mechanism,Micromixing\n"
        "protocol_version,1.2\n"
        "test_status,Ran - sensitivity confirmed\n",
        encoding="utf-8",
    )
    state = SimpleNamespace(
        _gui=None,
        ms_bourne_upload=str(csv_path),
        ms_bourne_status="Not run - skip pre-screen",
        ms_bourne_mech="Not resolved",
        ms_bourne_tests=["Test 1"],
        ms_bourne_findings_df=pd.DataFrame(columns=["Test", "Finding", "Sensitive KPI(s)"]),
        ms_bourne_meta_caption="",
        ms_bourne_meta={},
        ms_started=True,
    )
    on_ms_bourne_import(state)
    assert state.ms_bourne_meta["project_name"] == "Demo Project"
    assert state.ms_bourne_meta["reactor"] == "EasyMax 102"
    assert state.ms_bourne_meta["fluid"] == "Water"
    assert state.ms_bourne_meta["test_status"] == "Ran - sensitivity confirmed"
    assert state.ms_bourne_meta["protocol_version"] == "1.2"


def test_variability_awareness_requires_signal_above_noise():
    df = pd.DataFrame([
        {
            "KPI": "Yield",
            "Unit": "%",
            "Low speed": 95.0,
            "Centre": 100.0,
            "High speed": 105.0,
            "Std dev": 4.0,
            "Replicates": 3,
            "Precision": 0.5,
        },
    ])
    res = _assess_kpis(df, 1)
    assert res is not None
    assert res["status"] == "not_sensitive"


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
