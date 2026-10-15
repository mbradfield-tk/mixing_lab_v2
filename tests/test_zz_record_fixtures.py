"""ONE-OFF: freeze the Taipy-page-derived inputs and parity values into JSON fixtures."""
import json
import os
import sys
import warnings
from pathlib import Path

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

with warnings.catch_warnings():
    warnings.simplefilter("ignore", DeprecationWarning)
    from fastapi.testclient import TestClient

import api.main as api_main  # noqa: E402
import test_api as ta  # noqa: E402
import test_contracts as tc  # noqa: E402
import test_golden_outputs as g  # noqa: E402
import test_reports as tr  # noqa: E402
from core.serialize import jsonable  # noqa: E402

OUT = Path(__file__).parent / "golden"
V1 = "/api/v1"


def _dump(model):
    return json.loads(model.model_dump_json())


def _j(obj):
    return json.loads(json.dumps(jsonable(obj)))


def test_record(monkeypatch, tmp_path):
    from pages import bourne_protocol as bp
    from pages import heat_transfer as ht
    from pages import mixing_sensitivity as ms
    from pages import vessel_assessment as va
    from pages import vessel_comparison as vc
    for mod in (ms, va, vc, ht, bp):
        monkeypatch.setattr(mod, "notify", lambda *a, **k: None)
    monkeypatch.setattr(api_main, "log_access", lambda **_kw: None)
    client = TestClient(api_main.create_app(), raise_server_exceptions=False)

    # --- request payloads -------------------------------------------------------------
    req = {"va_default": _dump(tc._va_request(False)), "va_full": _dump(tc._va_request(True)),
           "va_env_params": list(va.va_env_params), "va_reaction": va.va_reaction}
    real = ms._protocol_inputs
    scen = {}
    for name in tc.MS_SCENARIOS:
        captured = {}

        def spy(state, captured=captured):
            captured["inputs"], captured["state"] = real(state), state
            return captured["inputs"]
        monkeypatch.setattr(ms, "_protocol_inputs", spy)
        g.SCENARIOS[name]()
        scen[name] = _dump(tc._protocol_request(captured["inputs"], captured["state"]))
    monkeypatch.setattr(ms, "_protocol_inputs", real)
    req["ms_scenarios"] = scen
    for key, fn in (("va_report", tr._va_report_request), ("ms_report", tr._ms_report_request),
                    ("vc_report", tr._vc_report_request), ("bp_report", tr._bp_report_request),
                    ("ht_cool", tr._ht_cool_request), ("ht_rxn", tr._ht_rxn_request)):
        req[key] = _dump(fn())
    (OUT / "requests.json").write_text(json.dumps(req, indent=1, ensure_ascii=False))

    # --- page parity values -----------------------------------------------------------
    par = {}
    st = g._state(vc, **g._VC_FULL)
    vc._build_targets(st)
    vc.on_vc_compute(st)
    target_col = [c for c in st.vc_targets_df.columns if c != "Reactor"][0]
    par["comparison"] = _j({
        **{k: getattr(st, k) for k in (
            "vc_reaction", "vc_rxn_order", "vc_rxn_k", "vc_T_cool", "vc_fluid", "vc_T", "vc_P",
            "vc_rxn_c0", "vc_rxn_trxn", "vc_rxn_dh", "vc_vs", "vc_rho_p", "vc_d50", "vc_phi",
            "vc_x_wt", "vc_szw", "vc_gmb_z", "vc_cd", "vc_basis", "vc_basis_rpm",
            "vc_basis_vol", "vc_feed_basis", "vc_feed_volume_mL", "vc_feed_time_hr",
            "vc_status", "vc_summary_df", "vc_detail_df", "vc_rpm_ref_df", "vc_heat_df",
            "vc_scale_df", "vc_scale_full_df", "vc_scale_pct_df", "vc_impact_df",
            "vc_feed_plan_df")},
        "vc_reactors": list(st.vc_reactors),
        "vc_env_params_options": list(st.vc_env_params_options),
        "feed_pipe_mm": {r["Reactor"]: r["Feed pipe ID (mm)"]
                         for r in st.vc_feed_pipe_df.to_dict("records")},
        "fixed": {r["Reactor"]: r[target_col] for r in st.vc_targets_df.to_dict("records")},
    })

    ht_par = {}
    st = g._state(ht, rho=1100.0, wall_k=20.0, cp_jacket=3000.0, lining_thickness_mm=0.0)
    ht.on_compute(st)
    kpi = {r["Metric"]: r["Value"] for r in st.kpi_df.to_dict("records")}
    ht_par.update(reactor=st.selected_reactor, defaults=[st.n_rpm, st.v_l, st.a_ht],
                  cool_body={**ta._ht_body(st), "T_target_C": st.t_target, "q_rxn_W": st.q_rxn},
                  corr_df=st.corr_df, htm_compare_df=st.htm_compare_df,
                  summary_df=st.summary_df, U_kpi=kpi["U (W/m2.K)"])
    st = g._state(ht, ht_mode=ht.HT_MODE_RXN)
    ht.on_compute(st)
    ht_par.update(rxn_body={**ta._ht_body(st), "reaction": {
        "order": st.rxn_order, "k": st.rxn_k, "C0_mol_L": st.rxn_c0, "dH_kJ_mol": st.rxn_dH}},
        rxn_summary_df=st.rxn_summary_df)
    st = g._state(ht, ht_mode=ht.HT_MODE_SWEEP, sweep_color_range_mode="Custom",
                  sweep_u_color_min=100.0, sweep_u_color_max=900.0)
    ht._refresh_sweep_ranges(st)
    ht.on_compute(st)
    ht_par.update(sweep_body={**ta._ht_body(st), "x_parameter": "n_rpm", "y_parameter": "v_l",
                              "x_range": [st.sweep_x_min, st.sweep_x_max],
                              "y_range": [st.sweep_y_min, st.sweep_y_max],
                              "U_color_range": [100.0, 900.0]},
                  sweep_U=st.sweep_u_fig.data[0].z)
    par["heat_transfer"] = _j(ht_par)

    st = g._state(bp, bp_t1_adj_mode="On", bp_t2_feed_vol=50.0, bp_t3_impeller_ratio=4.0,
                  bp_project_name="E2E", bp_step_text="3")
    st.bp_t1_adj_vols_df = pd.DataFrame([{"Volume (L)": 0.08}, {"Volume (L)": 0.1}])
    bp.on_bp_start(st)
    bp._build_plan(st)
    responses = {1: (80.0, 90.0, 95.0), 2: (80.0, 90.0, 95.0), 3: (89.0, 90.0, 90.5)}
    for n in (1, 2, 3):
        low, ctr, high = bp.KPI_COLUMNS[n]
        lo, ce, hi = responses[n]
        setattr(st, f"bp_t{n}_kpi_df", pd.DataFrame([{
            "KPI": "Yield", "Unit": "%", low: lo, ctr: ce, high: hi, "Std dev": None,
            "Replicates": None}]))
        getattr(bp, f"on_bp_t{n}_assess")(st)
    bp.on_bp_export_sens_csv(st)
    par["bourne"] = _j({
        **{k: getattr(st, k) for k in (
            "bp_reactor", "bp_fluid", "bp_v_l", "bp_T", "bp_t1_hydro_df", "bp_t1_adj_result_df",
            "bp_t1_adj_caption", "bp_t2_cond_df", "bp_t3_cond_df", "bp_reactor_summary_df",
            "bp_t1_ctr_info", "bp_t1_verdict", "bp_t2_verdict", "bp_t3_verdict",
            "bp_t1_kpi_result_df", "bp_summary")},
        "t1_max_pct": st.bp_t1_result["results"][0]["max_pct"],
        "range_ratio": bp._test1_range_ratio(st),
        "sens_csv": st.bp_sens_csv_bytes.decode("utf-8"),
        "kpi_columns_2": list(bp.KPI_COLUMNS[2]),
        "default_v_l": bp.bp_v_l, "default_rpm_center": bp.bp_t1_rpm_center,
    })

    from core.options import BourneStatus, Competing, Kinetics, Phase
    yld = [{"name": "Yield", "unit": "%", "low": 80, "centre": 90, "high": 95}]
    csv = client.post(f"{V1}/bourne/sensitivity-csv", json={
        "reactor": ta.REACTOR, "test1": yld, "test2": yld,
        "project": {"project_name": "E2E", "step_number": "3"}}).content
    path = tmp_path / "bourne.csv"
    path.write_bytes(csv)
    st = g._state(ms, ms_started=True, ms_bourne_upload=str(path), ms_semi_batch="On",
                  ms_phases=[Phase.LIQUID.label, Phase.GAS.label],
                  ms_competing=Competing.YES.label, ms_da_mode="On")
    ms.on_ms_reaction_change(st)
    ms.on_ms_bourne_import(st)
    par["sensitivity"] = _j({
        **{k: getattr(st, k) for k in (
            "ms_bourne_meta_caption", "ms_bourne_meta", "ms_reaction", "ms_rxn_order", "ms_rxn_k",
            "ms_rxn_c0", "ms_rxn_dh", "ms_rho_cp", "ms_rxn_trxn", "ms_c0_heat", "ms_da_reactor",
            "ms_da_rpm", "ms_da_vl", "ms_rxn_T", "ms_kinetics_md", "ms_dt_ad_caption",
            "ms_da_caption", "ms_trxn_caption", "ms_summary_note", "ms_verdict", "ms_ready",
            "ms_show_dh_action", "ms_findings_df", "ms_nextsteps_df",
            *[f"ms_step{n}_assess" for n in range(6)])},
        "bourne_status": BourneStatus.from_label(st.ms_bourne_status).value,
        "bourne_findings": st.ms_bourne_findings_df.to_dict("records"),
        "kinetics": Kinetics.from_label(st.ms_kinetics_avail).value,
        "dh_ref_options": sorted(ms.dh_ref_options),
    })
    (OUT / "page_parity.json").write_text(json.dumps(par, indent=1, ensure_ascii=False))
