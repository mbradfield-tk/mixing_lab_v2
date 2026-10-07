"""HTTP API (FastAPI) tests: JSON over HTTP equals the service results (which
test_contracts ties to the page goldens), plus auth, uploads, errors and static files."""
import json
import sys
import warnings
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

with warnings.catch_warnings():
    warnings.simplefilter("ignore", DeprecationWarning)
    from fastapi.testclient import TestClient

import api.main as api_main  # noqa: E402
from api import cache as api_cache  # noqa: E402
from core import auth, repositories as repos  # noqa: E402
from core import schemas as s  # noqa: E402
from core import services as sv  # noqa: E402
from reports import charts  # noqa: E402

import test_contracts as contracts  # noqa: E402

V1 = "/api/v1"
REACTOR = "TMA EasyMax-102"


@pytest.fixture(autouse=True)
def _no_usage_log(monkeypatch):
    monkeypatch.setattr(api_main, "log_access", lambda **_kw: None)
    api_cache.clear()


@pytest.fixture
def client():
    return TestClient(api_main.create_app(), raise_server_exceptions=False)


@pytest.fixture
def admin_env(monkeypatch):
    monkeypatch.setenv(auth.ADMIN_USER_ENV, "ops")
    monkeypatch.setenv(auth.ADMIN_PW_ENV, "pw")


@pytest.fixture
def token(client, admin_env):
    res = client.post(f"{V1}/auth/login", json={"username": "ops", "password": "pw"})
    assert res.status_code == 200
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


@pytest.fixture
def temp_tables(tmp_path, monkeypatch):
    """Point every repository at a temp copy of its CSV."""
    for repo in repos.REPOSITORIES.values():
        path = tmp_path / repo.path.name
        if repo.path.exists():
            path.write_bytes(repo.path.read_bytes())
        else:
            path.write_text(",".join(repo.columns) + "\n")
        monkeypatch.setattr(repo, "path", path)


def _json(model) -> dict:
    return json.loads(model.model_dump_json())


# --- parity with the services -----------------------------------------------
@pytest.mark.parametrize("full", [False, True])
def test_point_over_http_equals_service(client, full):
    req = contracts._va_request(full)
    res = client.post(f"{V1}/assessment/point", json=_json(req))
    assert res.status_code == 200
    assert res.json() == _json(sv.evaluate(req))


@pytest.mark.parametrize("path, req, service", [
    ("/heat-transfer/heat-cool", s.HeatCoolRequest(reactor=REACTOR, T_jacket_C=-10, T_target_C=5),
     sv.heat_cool),
    ("/bourne/plan", s.BournePlanRequest(reactor=REACTOR), sv.bourne_plan),
    ("/fluids/blend", s.BlendRequest(components=[s.BlendComponent(name="Water", amount=1),
                                                 s.BlendComponent(name="Toluene", amount=1)]),
     sv.blend),
    ("/comparison", s.ComparisonRequest(reactors=[REACTOR, "Cambrex R-101"]),
     sv.comparison_summary),
    ("/units/convert", s.UnitConversionRequest(property="Pressure", from_unit="bar", value=2),
     sv.convert_units),
])
def test_calculations_over_http_equal_services(client, path, req, service):
    res = client.post(V1 + path, json=_json(req))
    assert res.status_code == 200, res.text
    assert res.json() == _json(service(req))


def test_every_chart_kind_returns_plotly_json(client):
    payloads = {
        "assessment-envelope": {"point": _json(contracts._va_request())},
        "assessment-surfaces": {"point": _json(contracts._va_request()),
                                "envelope_parameters": ["P_V_W_L"]},
        "comparison-envelope": {"comparison": {"reactors": [REACTOR, "Cambrex R-101"]},
                                "parameters": ["P_V_W_L"]},
        "heat-cool": {"reactor": REACTOR, "T_jacket_C": -10, "T_target_C": 5},
        "reaction-profile": {"reactor": REACTOR, "T_jacket_C": 10,
                             "reaction": {"order": "2", "k": 0.5, "C0_mol_L": 1}},
        "ua-surface": {"reactor": REACTOR, "T_jacket_C": -10, "n_points": 5},
        "bourne-speed-plan": {"reactor": REACTOR},
        "solvent-properties": {"name": "Water", "T_C": 40},
        "blend-phases": {"components": [{"name": "Water", "amount": 1},
                                        {"name": "Toluene", "amount": 1}]},
    }
    assert set(payloads) == set(charts.CHARTS)
    for kind, payload in payloads.items():
        res = client.post(f"{V1}/charts/{kind}", json=payload)
        assert res.status_code == 200, (kind, res.text)
        figs = res.json()["figures"]
        assert figs and all("data" in f and "layout" in f for f in figs.values()), kind


def test_assessment_envelope_chart_matches_report_figure(client):
    from reports.service import assessment_envelope, figure_json

    req = s.AssessmentReportRequest(point=contracts._va_request())
    res = client.post(f"{V1}/charts/assessment-envelope", json=_json(req)).json()
    assert res["figures"]["envelope"] == figure_json(assessment_envelope(req)[0])


def test_report_endpoint_returns_a_pdf(client, monkeypatch):
    monkeypatch.setenv("MIXING_LAB_CHART_RENDERER", "matplotlib")
    res = client.post(f"{V1}/reports/heat-cool",
                      json={"reactor": REACTOR, "T_jacket_C": -10, "T_target_C": 5})
    assert res.status_code == 200
    assert res.headers["content-type"] == "application/pdf"
    assert res.content.startswith(b"%PDF") and "attachment" in res.headers["content-disposition"]
    assert client.post(f"{V1}/reports/nope", json={}).status_code == 404


# --- databases --------------------------------------------------------------
def test_reads_need_no_login(client):
    res = client.get(f"{V1}/vessels", params={"q": "100", "field": "V_L_max", "op": ">"})
    assert res.status_code == 200 and res.json()["status"].endswith("V_L_max > 100.")
    assert client.get(f"{V1}/vessels/{REACTOR}").json()["reactor_name"] == REACTOR
    assert client.get(f"{V1}/vessels/Nope").status_code == 404
    assert client.get(f"{V1}/fluids/custom/columns").status_code == 200
    assert client.get(f"{V1}/vessels/export").headers["content-type"].startswith("text/csv")


def test_login_and_protected_writes(client, temp_tables, token, admin_env):
    bead = {"particle_name": "API bead", "rho_p_kg_m3": 2500, "d10_um": 10, "d50_um": 50,
            "d90_um": 90}
    assert client.post(f"{V1}/particles", json=bead).status_code == 403
    res = client.post(f"{V1}/particles", json=bead, headers=token)
    assert res.status_code == 201 and res.json()["particle_name"] == "API bead"
    assert client.post(f"{V1}/particles", json=bead, headers=token).status_code == 422
    res = client.patch(f"{V1}/particles/API bead", json={"notes": "edited"}, headers=token)
    assert res.json()["notes"] == "edited"
    assert client.patch(f"{V1}/particles/API bead", json={"bogus": 1},
                        headers=token).status_code == 422
    assert client.delete(f"{V1}/particles/API bead", headers=token).status_code == 204
    assert client.get(f"{V1}/particles/API bead").status_code == 404
    bad = {"Authorization": "Bearer not-a-token"}
    assert client.post(f"{V1}/particles", json=bead, headers=bad).status_code == 401


def test_login_failures(client, monkeypatch):
    monkeypatch.delenv(auth.ADMIN_USER_ENV, raising=False)
    monkeypatch.delenv(auth.ADMIN_PW_ENV, raising=False)
    body = {"username": "admin", "password": "admin_tak_2026"}
    assert client.post(f"{V1}/auth/login", json=body).status_code == 503
    monkeypatch.setenv(auth.ADMIN_USER_ENV, "ops")
    monkeypatch.setenv(auth.ADMIN_PW_ENV, "pw")
    assert client.post(f"{V1}/auth/login", json=body).status_code == 401


def test_results_are_open_to_the_local_user(client, temp_tables):
    row = {"reactor": REACTOR, "RPM": 300, "Assessment": "Potentially sensitive"}
    assert client.post(f"{V1}/results", json=[row]).status_code == 201
    res = client.get(f"{V1}/results", params={"reactor": [REACTOR]}).json()
    assert res["count"] == 1 and res["counts"]["potentially_sensitive"] == 1
    assert client.delete(f"{V1}/results").status_code == 204
    assert client.get(f"{V1}/results").json()["count"] == 0


def test_created_vessels_get_an_id_and_search_name(client, temp_tables, token):
    res = client.post(f"{V1}/vessels", json={"reactor_name": "API vessel", "owner": "QA",
                                              "V_L_max": 2.5}, headers=token)
    assert res.status_code == 201
    row = client.get(f"{V1}/vessels/API vessel").json()
    assert row["reactor_id"].startswith("RX-") and row["search_name"]
    assert client.post(f"{V1}/vessels", json={"reactor_name": "API vessel"},
                       headers=token).status_code == 422


def test_assessment_page_endpoints_match_the_taipy_page(client, temp_tables):
    from core.envelope import DEFAULT_ENVELOPE, ENVELOPE_PARAMETERS
    from core.operating_point import evaluate_point
    from reports.tables import assessment_tables

    params = client.get(f"{V1}/assessment/parameters").json()
    assert [p["label"] for p in params] == ENVELOPE_PARAMETERS
    assert {p["label"] for p in params if p["default"]} == set(DEFAULT_ENVELOPE)

    d = client.get(f"{V1}/assessment/vessel-defaults/{REACTOR}").json()
    assert d["corr_sources"][0]["code"] == "Literature" and d["N_rpm"] > 0
    assert client.get(f"{V1}/assessment/vessel-defaults/Nope").status_code == 404

    fp = client.get(f"{V1}/fluids/properties", params={"name": "toluene", "T_C": 40}).json()
    assert fp["name"] == "Toluene" and fp["found"] and fp["rho_kg_m3"] < 862
    assert not client.get(f"{V1}/fluids/properties", params={"name": "no such"}).json()["found"]

    body = {"reactor": REACTOR, "N_rpm": d["N_rpm"], "V_L": d["V_L"],
            "reaction": {"order": "2", "k": 0.5, "C0_mol_L": 1.0, "dH_kJ_mol": -80},
            "heat": {"T_process_C": 25, "T_coolant_C": 15}, "gas": {"present": True},
            "solids": {"rho_p_kg_m3": 2500, "d50_um": 100}}
    res = client.post(f"{V1}/assessment/tables", json=body).json()
    inp, t_rxn, _row = sv.point_inputs(s.PointRequest.model_validate(body))
    page = assessment_tables(evaluate_point(inp, d["N_rpm"] / 60, d["V_L"]), d["N_rpm"], t_rxn,
                             solids_on=True, gas_on=True, fed_on=False)
    for key in ("hydro", "damkohler", "mass_transfer", "solids", "heat"):
        assert res[key] == page[key].to_dict("records"), key
    assert res["assessment"] == page["assessment"] and res["t_rxn_s"] == t_rxn
    assert res["applicability"].startswith("**Correlation applicability:**")

    assert client.post(f"{V1}/assessment/save",
                       json={"point": body, "reaction_name": "Grignard"}).status_code == 201
    saved = client.get(f"{V1}/results").json()["records"][-1]
    assert saved["reaction"] == "Grignard" and saved["Da_macro"] == res["point"]["Da_macro"]


def test_comparison_page_endpoints_match_the_taipy_page(client, temp_tables, monkeypatch):
    from types import SimpleNamespace

    from core.serialize import jsonable
    from pages import vessel_comparison as vc
    from test_golden_outputs import _VC_FULL, _state

    monkeypatch.setattr(vc, "notify", lambda *_a, **_k: None)
    st = _state(vc, **_VC_FULL)
    vc._build_targets(st)
    vc.on_vc_compute(st)
    assert isinstance(st, SimpleNamespace) and st._vc_cache

    names = list(st.vc_reactors)
    setup = client.post(f"{V1}/comparison/setup", json={"reactors": names}).json()
    assert setup["feed_pipe_mm"] == {r["Reactor"]: r["Feed pipe ID (mm)"]
                                     for r in st.vc_feed_pipe_df.to_dict("records")}
    target_col = [c for c in st.vc_targets_df.columns if c != "Reactor"][0]
    assert setup["fixed"] == {r["Reactor"]: r[target_col] for r in st.vc_targets_df.to_dict("records")}

    kin = client.get(f"{V1}/kinetics/defaults", params={"reaction": st.vc_reaction}).json()
    assert kin["order"] == st.vc_rxn_order and kin["k"] == st.vc_rxn_k

    comparison = {
        "reactors": names, "reaction_name": st.vc_reaction, "T_coolant_C": st.vc_T_cool,
        "fluid": {"name": st.vc_fluid, "T_C": st.vc_T, "P_atm": st.vc_P},
        "reaction": {"order": st.vc_rxn_order, "k": st.vc_rxn_k, "C0_mol_L": st.vc_rxn_c0,
                     "t_rxn_s": st.vc_rxn_trxn, "dH_kJ_mol": st.vc_rxn_dh},
        "gas": {"present": True, "v_s_m_s": st.vc_vs, "coalescing": True},
        "solids": {"rho_p_kg_m3": st.vc_rho_p, "d50_um": st.vc_d50, "sphericity": st.vc_phi,
                   "loading_g_per_100g": st.vc_x_wt, "zwietering_S": st.vc_szw,
                   "gmb_z": st.vc_gmb_z, "clearance_ratio": st.vc_cd},
        "feed": {"location": "near_impeller", "pipe_id_mm": setup["feed_pipe_mm"]},
    }
    body = {"comparison": comparison,
            "scale_up": {"basis_reactor": st.vc_basis, "parameter": "P_V_W_L",
                         "basis_N_rpm": st.vc_basis_rpm, "basis_V_L": st.vc_basis_vol,
                         "solve_for": "N_rpm", "fixed": setup["fixed"]},
            "feed_schedule": {"basis_reactor": st.vc_feed_basis,
                              "volume_mL": st.vc_feed_volume_mL, "time_h": st.vc_feed_time_hr}}
    res = client.post(f"{V1}/comparison/tables", json=body).json()
    pairs = {"summary": st.vc_summary_df, "detail": st.vc_detail_df, "rpm_ref": st.vc_rpm_ref_df,
             "heat": st.vc_heat_df, "scale": st.vc_scale_df, "scale_full": st.vc_scale_full_df,
             "scale_pct": st.vc_scale_pct_df, "impact": st.vc_impact_df,
             "feed_plan": st.vc_feed_plan_df}
    for key, df in pairs.items():
        assert res[key] == jsonable(df), key
    assert res["status"] == st.vc_status and res["feed_ok"] is False  # the full scenario overflows
    assert {p["label"] for p in res["parameters"]} == set(st.vc_env_params_options)

    saved = client.post(f"{V1}/comparison/save", json=comparison)
    assert saved.status_code == 201 and saved.json() == {"saved": len(names), "count": len(names)}


def _ht_body(st) -> dict:
    """The HTTP request for a Taipy Heat Transfer state, every editable value sent explicitly."""
    return {
        "reactor": st.selected_reactor, "fluid": st.selected_fluid, "N_rpm": st.n_rpm,
        "V_L": st.v_l, "D_tank_m": st.d_tank, "D_imp_m": st.d_imp, "Np": st.np_in,
        "A_ht_m2": st.a_ht, "T_start_C": st.t_start, "T_jacket_C": st.t_jacket,
        "htm": st.selected_htm, "nusselt_correlation": st.nusselt_correlation,
        "v_jacket_m_s": st.v_jacket, "d_hyd_jacket_m": st.d_hyd_jacket,
        "m_dot_jacket_kg_s": st.m_dot_jacket, "wall_material": st.wall_material,
        "wall_thickness_mm": st.wall_thickness_mm, "lining_material": st.lining_material,
        "fouling_m2K_W": st.fouling, "include_agitator": st.include_agitator == "On",
        "mu_wall_Pa_s": st.mu_wall, "rho_kg_m3": st.rho, "mu_Pa_s": st.mu, "cp_J_kgK": st.cp,
        "k_W_mK": st.k_fluid, "cp_jacket_J_kgK": st.cp_jacket, "wall_k_W_mK": st.wall_k,
        "lining_k_W_mK": st.lining_k, "lining_thickness_mm": st.lining_thickness_mm,
        "time_unit": st.time_unit,
    }


def test_heat_transfer_endpoints_match_the_taipy_page(client, monkeypatch):
    from core.serialize import jsonable
    from pages import heat_transfer as ht
    from test_golden_outputs import _state

    monkeypatch.setattr(ht, "notify", lambda *_a, **_k: None)
    st = _state(ht, rho=1100.0, wall_k=20.0, cp_jacket=3000.0, lining_thickness_mm=0.0)
    ht.on_compute(st)
    d = client.get(f"{V1}/heat-transfer/defaults/{st.selected_reactor}").json()
    assert (d["N_rpm"], d["V_L"], d["A_ht_m2"]) == (st.n_rpm, st.v_l, st.a_ht)
    assert client.get(f"{V1}/fluids/thermal", params={"name": "Water"}).json()["cp_J_kgK"] == 4182.0

    res = client.post(f"{V1}/heat-transfer/heat-cool",
                      json={**_ht_body(st), "T_target_C": st.t_target, "q_rxn_W": st.q_rxn}).json()
    assert res["correlations"] == jsonable(st.corr_df)
    assert res["media"] == jsonable(st.htm_compare_df)
    assert res["summary"] == jsonable(st.summary_df)
    kpi = {r["Metric"]: r["Value"] for r in st.kpi_df.to_dict("records")}
    assert round(res["coefficients"]["U_W_m2K"], 2) == kpi["U (W/m2.K)"]

    st = _state(ht, ht_mode=ht.HT_MODE_RXN)
    ht.on_compute(st)
    res = client.post(f"{V1}/heat-transfer/reaction-profile", json={
        **_ht_body(st), "reaction": {"order": st.rxn_order, "k": st.rxn_k,
                                     "C0_mol_L": st.rxn_c0, "dH_kJ_mol": st.rxn_dH}}).json()
    assert res["summary"] == jsonable(st.rxn_summary_df)

    st = _state(ht, ht_mode=ht.HT_MODE_SWEEP, sweep_color_range_mode="Custom",
                sweep_u_color_min=100.0, sweep_u_color_max=900.0)
    ht._refresh_sweep_ranges(st)
    ht.on_compute(st)
    body = {**_ht_body(st), "x_parameter": "n_rpm", "y_parameter": "v_l",
            "x_range": [st.sweep_x_min, st.sweep_x_max], "y_range": [st.sweep_y_min, st.sweep_y_max],
            "U_color_range": [100.0, 900.0]}
    surf = client.post(f"{V1}/heat-transfer/ua-surface", json=body).json()
    assert surf["U_W_m2K"] == jsonable(st.sweep_u_fig.data[0].z)
    chart = client.post(f"{V1}/charts/ua-surface", json=body).json()
    assert chart["figures"]["U"]["data"][0]["cmin"] == 100.0


def test_bourne_page_endpoints_match_the_taipy_page(client, monkeypatch):
    import pandas as pd

    from core.serialize import jsonable
    from pages import bourne_protocol as bp
    from test_golden_outputs import _state

    monkeypatch.setattr(bp, "notify", lambda *_a, **_k: None)
    st = _state(bp, bp_t1_adj_mode="On", bp_t2_feed_vol=50.0, bp_t3_impeller_ratio=4.0,
                bp_project_name="E2E", bp_step_text="3")
    st.bp_t1_adj_vols_df = pd.DataFrame([{"Volume (L)": 0.08}, {"Volume (L)": 0.1}])
    bp.on_bp_start(st)
    bp._build_plan(st)

    responses = {1: (80.0, 90.0, 95.0), 2: (80.0, 90.0, 95.0), 3: (89.0, 90.0, 90.5)}
    kpis = {}
    for n in (1, 2, 3):
        low, ctr, high = bp.KPI_COLUMNS[n]
        lo, ce, hi = responses[n]
        setattr(st, f"bp_t{n}_kpi_df", pd.DataFrame([{
            "KPI": "Yield", "Unit": "%", low: lo, ctr: ce, high: hi, "Std dev": None,
            "Replicates": None}]))
        getattr(bp, f"on_bp_t{n}_assess")(st)
        kpis[f"test{n}"] = [{"name": "Yield", "unit": "%", "low": lo, "centre": ce, "high": hi}]

    req = {"reactor": st.bp_reactor, "fluid": st.bp_fluid, "V_L": st.bp_v_l,
           "fed_batch_volumes_L": [0.08, 0.1], "feed_volume_mL": 50.0, "impeller_ratio": 4.0}
    tables = client.post(f"{V1}/bourne/plan/tables", json=req).json()
    assert tables["test1"] == jsonable(st.bp_t1_hydro_df)
    assert tables["setpoints"] == jsonable(st.bp_t1_adj_result_df)
    assert tables["setpoints_caption"] == st.bp_t1_adj_caption
    assert tables["test2"] == jsonable(st.bp_t2_cond_df)
    assert tables["test3"] == jsonable(st.bp_t3_cond_df)
    assert tables["reactor_limits"] == jsonable(st.bp_reactor_summary_df)
    assert tables["centre_info"] == st.bp_t1_ctr_info

    res = client.post(f"{V1}/bourne/assess", json={**req, **kpis}).json()
    assert [t["verdict"] for t in res["tests"]] == [st.bp_t1_verdict, st.bp_t2_verdict,
                                                     st.bp_t3_verdict]
    assert res["tests"][0]["kpis"] == jsonable(st.bp_t1_kpi_result_df)
    assert res["summary"] == st.bp_summary
    assert res["summary"] == "\n".join(["### Decision-tree conclusion", ""]
                                       + ["- " + ln for ln in res["test_lines"]] + ["", res["conclusion"]])
    k1 = res["tests"][0]["kpi_details"][0]
    assert k1["max_change_pct"] == pytest.approx(st.bp_t1_result["results"][0]["max_pct"])
    assert (k1["sensitive"], k1["threshold_pct"], k1["centre"]) == (True, 5.0, 90.0)
    assert res["pm_span"] == pytest.approx(bp._test1_range_ratio(st))

    bp.on_bp_export_sens_csv(st)
    csv = client.post(f"{V1}/bourne/sensitivity-csv",
                      json={**req, **kpis, "project": {"project_name": "E2E", "step_number": "3"}})
    assert csv.status_code == 200 and csv.headers["content-type"].startswith("text/csv")
    assert csv.content == st.bp_sens_csv_bytes
    opts = client.get(f"{V1}/bourne/options").json()
    assert opts["kpi_columns"]["2"] == list(bp.KPI_COLUMNS[2])
    d = client.get(f"{V1}/bourne/defaults/{st.bp_reactor}").json()
    assert d["V_L"] == pytest.approx(bp.bp_v_l) and d["centre_rpm"] == pytest.approx(bp.bp_t1_rpm_center)
    assert d["reactor_limits"] == jsonable(st.bp_reactor_summary_df)


def test_sensitivity_page_endpoints_match_the_taipy_page(client, monkeypatch, tmp_path):
    from core.options import BourneStatus, Competing, Kinetics, Phase
    from core.serialize import jsonable
    from pages import mixing_sensitivity as ms
    from test_golden_outputs import _state

    monkeypatch.setattr(ms, "notify", lambda *_a, **_k: None)
    yld = [{"name": "Yield", "unit": "%", "low": 80, "centre": 90, "high": 95}]
    csv = client.post(f"{V1}/bourne/sensitivity-csv", json={
        "reactor": REACTOR, "test1": yld, "test2": yld,
        "project": {"project_name": "E2E", "step_number": "3"}}).content
    path = tmp_path / "bourne.csv"
    path.write_bytes(csv)

    st = _state(ms, ms_started=True, ms_bourne_upload=str(path), ms_semi_batch="On",
                ms_phases=[Phase.LIQUID.label, Phase.GAS.label], ms_competing=Competing.YES.label,
                ms_da_mode="On")
    ms.on_ms_reaction_change(st)
    ms.on_ms_bourne_import(st)

    imp = client.post(f"{V1}/sensitivity/bourne-import",
                      files={"file": ("bourne.csv", csv, "text/csv")}).json()
    assert imp["status"] == BourneStatus.from_label(st.ms_bourne_status).value
    assert imp["meta_caption"] == st.ms_bourne_meta_caption and imp["meta"] == st.ms_bourne_meta
    assert [{"Test": r["test"], "Finding": r["finding"], "Sensitive KPI(s)": r["sensitive_kpis"]}
            for r in imp["findings"]] == st.ms_bourne_findings_df.to_dict("records")
    bad = client.post(f"{V1}/sensitivity/bourne-import",
                      files={"file": ("x.csv", b"a,b\n1,2\n", "text/csv")})
    assert bad.status_code == 422 and "Not a Bourne results CSV" in bad.text

    d = client.get(f"{V1}/sensitivity/reaction-defaults", params={"reaction": st.ms_reaction}).json()
    assert (d["order"], d["k"], d["C0_mol_L"], d["dH_kJ_mol"]) == (
        st.ms_rxn_order, st.ms_rxn_k, st.ms_rxn_c0, st.ms_rxn_dh)
    assert d["rho_cp_kJ_m3K"] in (None, st.ms_rho_cp)

    req = {
        "reaction": {"order": st.ms_rxn_order, "k": st.ms_rxn_k, "C0_mol_L": st.ms_rxn_c0,
                     "t_rxn_s": st.ms_rxn_trxn, "dH_kJ_mol": st.ms_rxn_dh},
        "reaction_type": d["reaction_type"],
        "kinetics": Kinetics.from_label(st.ms_kinetics_avail).value,
        "bourne": imp["status"], "bourne_mechanism": imp["mechanism"],
        "bourne_tests_done": imp["tests_done"], "bourne_results": imp["findings"],
        "semi_batch": True, "phases": ["liquid", "gas"], "competing": "yes",
        "c0_heat_mol_L": st.ms_c0_heat, "rho_cp_kJ_m3K": st.ms_rho_cp,
        "screening_vessel": {"reactor": st.ms_da_reactor, "N_rpm": st.ms_da_rpm,
                             "V_L": st.ms_da_vl, "solvent": d["solvent"], "T_C": st.ms_rxn_T},
    }
    page = client.post(f"{V1}/sensitivity/page", json=req).json()
    assert page["steps"] == [getattr(st, f"ms_step{n}_assess") for n in range(6)]
    for key, attr in (("kinetics_md", "ms_kinetics_md"), ("dt_ad_caption", "ms_dt_ad_caption"),
                      ("da_caption", "ms_da_caption"), ("trxn_caption", "ms_trxn_caption"),
                      ("summary_note", "ms_summary_note"), ("verdict", "ms_verdict"),
                      ("ready", "ms_ready"), ("show_dh_action", "ms_show_dh_action")):
        assert page[key] == getattr(st, attr), key
    assert page["da_caption"]
    assert page["findings"] == jsonable(st.ms_findings_df)
    assert page["next_steps"] == jsonable(st.ms_nextsteps_df)
    from core.messages import icon
    assert [{"Sensitivity Type": f["area"], "Finding": f"{icon(f['kind'])} {f['status']} - {f['detail']}"}
            for f in page["insights"]] == page["findings"]
    assert [{"Area": a["area"], "Recommended action": a["action"]} for a in page["actions"]] == page["next_steps"]
    assert page["verdict"].startswith(icon(page["verdict_kind"]))

    opts = client.get(f"{V1}/sensitivity/options").json()
    assert sorted(opts["dh_references"]) == sorted(ms.dh_ref_options)
    pdf = client.post(f"{V1}/reports/sensitivity", json={
        "protocol": req, "reaction_name": st.ms_reaction, "bourne_meta": imp["meta"]})
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")


def test_vessel_import_preview_and_apply(client, temp_tables, token):
    df = repos.reactors.load()
    csv = df.head(1).assign(owner="API test owner").to_csv(index=False).encode()
    files = {"file": ("v.csv", csv, "text/csv")}
    changes = client.post(f"{V1}/vessels/import/preview", files=files).json()
    owner = [c for c in changes if "API test owner" in json.dumps(c)]
    assert owner
    res = client.post(f"{V1}/vessels/import/apply", files=files,
                      data={"accept": json.dumps([owner[0]["id"]])}, headers=token)
    assert res.status_code == 200 and res.json()["applied"] == 1
    assert repos.reactors.load().iloc[0]["owner"] == "API test owner"


def test_upload_limits(client, temp_tables, token, monkeypatch):
    import api.routers.databases as dbr

    monkeypatch.setattr(dbr, "MAX_UPLOAD_BYTES", 10)
    files = {"file": ("p.csv", b"particle_name\n" + b"x" * 50, "text/csv")}
    assert client.put(f"{V1}/particles/import", files=files, headers=token).status_code == 413


# --- errors, media, static --------------------------------------------------
def test_unexpected_errors_hide_details(client, monkeypatch):
    def boom(_req):
        raise RuntimeError("secret internals")

    monkeypatch.setattr(sv, "evaluate", boom)
    res = client.post(f"{V1}/assessment/point", json=_json(contracts._va_request()))
    assert res.status_code == 500 and "secret" not in res.text


def test_validation_and_lookup_errors(client):
    assert client.post(f"{V1}/assessment/point",
                       json={"reactor": REACTOR, "N_rpm": -1, "V_L": 1}).status_code == 422
    assert client.post(f"{V1}/assessment/point",
                       json={"reactor": "Nope", "N_rpm": 100, "V_L": 1}).status_code == 404
    assert client.post(f"{V1}/units/convert", json={"property": "Pressure", "from_unit": "x",
                                                    "value": 1}).status_code == 404


def test_vessel_media_schematic_and_static_files(client):
    media = client.get(f"{V1}/media/vessels/{REACTOR}").json()
    assert media["kind"] in ("3d", "image")
    static = client.get(media["url"])
    assert static.status_code == 200 and "max-age" in static.headers["cache-control"]
    png = client.get(f"{V1}/media/vessels/{REACTOR}/schematic.png", params={"fill_L": 0.1})
    assert png.status_code == 200 and png.content.startswith(b"\x89PNG")
    fill = client.get(f"{V1}/media/vessels/{REACTOR}/fill", params={"fill_L": 0.1}).json()
    assert fill["total_L"] > 0 and fill["level_mm"] is not None
    for path in ("/vimages/../data/reactors.csv", "/vimages/%2e%2e/data/reactors.csv",
                 "/vassets/../app.py"):
        assert client.get(path).status_code == 404


def test_reference_endpoints(client):
    eq = client.get(f"{V1}/equations").json()
    items = [i for sec in eq["sections"] for i in sec["items"]]
    latex = [i for i in items if i["type"] == "latex"]
    assert latex and all(i["latex"] for i in latex)
    assert not any("img" in i for i in items)  # raw LaTeX for KaTeX, not pre-rendered PNGs
    assert all(isinstance(i["level"], int) for i in items if i["type"] == "header")
    assert "Pressure" in client.get(f"{V1}/units").json()["properties"]
    o = client.get(f"{V1}/options").json()
    assert REACTOR in o["reactors"] and o["enums"]["CorrSource"]
    assert client.get(f"{V1}/health").json() == {"status": "ok"}
    assert client.get("/favicon.ico").headers["content-type"] == "image/png"


def test_root_redirects_to_docs_until_the_web_app_is_built(monkeypatch, tmp_path):
    monkeypatch.setattr(api_main, "WEB_DIST", tmp_path / "missing")
    root = TestClient(api_main.create_app()).get("/", follow_redirects=False)
    assert root.status_code == 307 and root.headers["location"] == f"{V1}/docs"


def test_built_web_app_is_served_with_client_side_routes(monkeypatch, tmp_path):
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<div id=root></div>")
    (tmp_path / "assets" / "app.js").write_text("console.log(1)")
    monkeypatch.setattr(api_main, "WEB_DIST", tmp_path)
    web = TestClient(api_main.create_app())
    assert web.get("/", follow_redirects=False).headers["location"] == "/app/"
    for path in ("/app", "/app/", "/app/unit-converter", "/app/equations-reference",
                 "/app/particles", "/app/reactions", "/app/fluids", "/app/vessels",
                 "/app/recorded-results", "/app/crystallization-sensitivity",
                 "/app/vessel-assessment", "/app/vessel-comparison", "/app/heat-transfer",
                 "/app/bourne-protocol", "/app/reaction-sensitivity"):
        res = web.get(path)
        assert res.status_code == 200 and "<div id=root>" in res.text, path
    assert web.get("/app/assets/app.js").text == "console.log(1)"
    assert web.get("/app/assets/missing.js").status_code == 404


def test_icons_are_small_pngs(client):
    res = client.get(f"{V1}/media/icons/Unit_Converter", params={"px": 96})
    assert res.status_code == 200 and res.content.startswith(b"\x89PNG")
    assert len(res.content) < 50_000 and "max-age" in res.headers["cache-control"]
    assert client.get(f"{V1}/media/icons/logo", params={"px": 48}).status_code == 200
    assert client.get(f"{V1}/media/icons/Nope").status_code == 404
    assert client.get(f"{V1}/media/icons/..%2F..%2Fapp").status_code == 404
    assert client.get(f"{V1}/media/icons/logo", params={"px": 5000}).status_code == 422


def test_slow_results_are_cached_until_the_data_changes(client, monkeypatch):
    from reports import charts as charts_mod

    calls = []
    real = charts_mod.render_chart
    monkeypatch.setattr(charts_mod, "render_chart",
                        lambda kind, payload: calls.append(kind) or real(kind, payload))
    version = {"v": 1}
    monkeypatch.setattr(api_cache, "data_version", lambda: (version["v"],))
    body = {"name": "Water", "T_C": 40}
    first = client.post(f"{V1}/charts/solvent-properties", json=body).json()
    assert client.post(f"{V1}/charts/solvent-properties", json=body).json() == first
    assert calls == ["solvent-properties"]
    version["v"] = 2
    client.post(f"{V1}/charts/solvent-properties", json=body)
    assert len(calls) == 2
    assert client.post(f"{V1}/charts/solvent-properties", json={"name": "Nope"}).status_code == 404
    assert client.post(f"{V1}/charts/solvent-properties", json={"name": "Nope"}).status_code == 404
    assert len(calls) == 4, "errors must not be cached"


# --- OpenAPI snapshot -------------------------------------------------------
def test_openapi_snapshot_is_current(client):
    """api/openapi.json is what the React types are generated from; regenerate with
    ``python scripts/export_openapi.py`` after changing a route or contract."""
    current = client.get(f"{V1}/openapi.json").json()
    committed = json.loads((ROOT / "api" / "openapi.json").read_text())
    assert current == committed, "OpenAPI changed: run python scripts/export_openapi.py"


def test_cors_is_off_unless_configured(monkeypatch):
    monkeypatch.delenv(api_main.CORS_ENV, raising=False)
    plain = TestClient(api_main.create_app())
    assert "access-control-allow-origin" not in plain.get(
        f"{V1}/health", headers={"Origin": "http://evil.example"}).headers
    monkeypatch.setenv(api_main.CORS_ENV, "http://localhost:5173")
    cors = TestClient(api_main.create_app())
    res = cors.get(f"{V1}/health", headers={"Origin": "http://localhost:5173"})
    assert res.headers["access-control-allow-origin"] == "http://localhost:5173"
