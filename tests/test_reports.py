"""Report services: request -> snapshot/PDF must match what the pages produce."""

import json
import os
import sys

import plotly.graph_objects as go
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import test_contracts as tc  # noqa: E402  (tests/ is on sys.path under pytest)
import test_golden_outputs as g  # noqa: E402
import test_golden_reports as gr  # noqa: E402
from core import schemas as s
from core.options import CorrSource, FeedLocation
from pages import bourne_protocol as bp
from pages import heat_transfer as ht
from pages import mixing_sensitivity as ms
from pages import vessel_assessment as va
from pages import vessel_comparison as vc
from reports import service
from reports import pdf as rb

GOLDEN = json.loads(gr.GOLDEN.read_text())


def _va_report_request() -> s.AssessmentReportRequest:
    point = tc._va_request(full=True)
    point = point.model_copy(update={"gas": point.gas.model_copy(update={"present": True})})
    return s.AssessmentReportRequest(
        point=point, envelope_parameters=[s.CORE_KEYS[k] for k in va.va_env_params],
        reaction_name=va.va_reaction)


def _ms_report_request() -> s.ProtocolReportRequest:
    st = g._state(ms, ms_started=True, **{**g._MS_BASE, "ms_da_mode": "On"})
    return s.ProtocolReportRequest(protocol=tc._protocol_request(ms._protocol_inputs(st), st),
                                   reaction_name=st.ms_reaction)


def test_assessment_snapshot_matches_vessel_assessment_page():
    got = json.loads(json.dumps(gr._n(service.assessment_snapshot(_va_report_request())),
                                ensure_ascii=False))
    assert g._first_diff(got, GOLDEN["va"]["snap"]) is None


def test_protocol_snapshot_matches_mixing_sensitivity_page():
    got = json.loads(json.dumps(gr._n(service.protocol_snapshot(_ms_report_request())),
                                ensure_ascii=False))
    assert g._first_diff(got, GOLDEN["ms"]["snap"]) is None


@pytest.fixture
def no_chart_images(monkeypatch):
    def unavailable(_fig):
        raise RuntimeError("image backend unavailable in tests")
    monkeypatch.setattr(rb, "fig_to_png_bytes", unavailable)


@pytest.mark.filterwarnings("ignore:Skipping")
def test_reports_render_pdf_bytes(no_chart_images):
    for report in (service.assessment_report(_va_report_request()),
                   service.protocol_report(_ms_report_request())):
        assert report.content.startswith(b"%PDF") and report.filename.endswith(".pdf")
        assert report.media_type == "application/pdf"


def test_envelope_figure_is_strict_json_for_react_plotly():
    fig, caption = service.assessment_envelope(_va_report_request())
    def reject(c):
        raise AssertionError(f"non-JSON constant {c}")
    data = json.loads(json.dumps(service.figure_json(fig)), parse_constant=reject)
    assert data["data"] and "layout" in data and "Operating envelope" in caption


# --------------------------------------------------------------------------- VC / BP / HT
def _vc_report_request() -> s.ComparisonRequest:
    pipes = {str(r["Reactor"]): float(r["Feed pipe ID (mm)"]) for _, r in vc.vc_feed_pipe_df.iterrows()}
    return s.ComparisonRequest(
        reactors=list(vc.vc_reactors),
        fluid=s.FluidSpec(name=vc.vc_fluid, T_C=vc.vc_T, P_atm=vc.vc_P),
        reaction=s.ReactionSpec(order=vc.vc_rxn_order, k=vc.vc_rxn_k, C0_mol_L=vc.vc_rxn_c0,
                                t_rxn_s=vc.vc_rxn_trxn, dH_kJ_mol=-100.0),
        reaction_name=vc.vc_reaction, corr_source=CorrSource.from_label(vc.vc_corr_mode),
        gas=s.GasSpec(present=True, v_s_m_s=vc.vc_vs, coalescing=True),
        solids=s.SolidsSpec(rho_p_kg_m3=vc.vc_rho_p, d50_um=vc.vc_d50, sphericity=vc.vc_phi,
                            loading_g_per_100g=vc.vc_x_wt, zwietering_S=vc.vc_szw,
                            gmb_z=vc.vc_gmb_z, clearance_ratio=vc.vc_cd),
        feed=s.ComparisonFeed(location=FeedLocation.NEAR_IMPELLER, pipe_id_mm=pipes),
        T_coolant_C=vc.vc_T_cool, scale_param=vc.vc_scale_param, scale_basis_reactor=vc.vc_basis)


def _kpi(values) -> list[s.KpiResponse]:
    low, centre, high = values
    return [s.KpiResponse(name="Yield", unit="%", low=low, centre=centre, high=high)]


def _bp_report_request() -> s.BourneReportRequest:
    return s.BourneReportRequest(reactor=bp.bp_reactor, fluid=bp.bp_fluid, T_C=bp.bp_T,
                                 test1=_kpi([90.0, 100.0, 112.0]), test2=_kpi([95.0, 100.0, 108.0]),
                                 test3=_kpi([100.0, 100.0, 101.0]))


def _ht_base() -> dict:
    return dict(reactor=ht.selected_reactor, fluid=ht.selected_fluid, T_start_C=ht.t_start,
                T_jacket_C=ht.t_jacket, lining_material="None", time_unit=ht.time_unit)


def _ht_cool_request() -> s.HeatCoolRequest:
    return s.HeatCoolRequest(**_ht_base(), T_target_C=ht.t_target)


def _ht_rxn_request() -> s.ReactionProfileRequest:
    return s.ReactionProfileRequest(**_ht_base(), reaction=s.ReactionSpec(
        order=ht.rxn_order, k=0.01, C0_mol_L=1.0, dH_kJ_mol=-100.0))


@pytest.fixture
def fake_png(monkeypatch):
    monkeypatch.setattr(rb, "fig_to_png_bytes", lambda fig: gr._fig_key(fig).encode())


@pytest.mark.parametrize("golden_name, build", [
    ("vc", lambda: service.comparison_snapshot(_vc_report_request())),
    ("bp", lambda: service.bourne_snapshot(_bp_report_request())),
    ("ht_batch", lambda: service.heat_cool_snapshot(_ht_cool_request())),
    ("ht_reaction", lambda: service.reaction_profile_snapshot(_ht_rxn_request())),
])
def test_endpoint_snapshots_match_pages(golden_name, build, fake_png):
    got = json.loads(json.dumps(gr._n(build()), ensure_ascii=False))
    assert g._first_diff(got, GOLDEN[golden_name]["snap"]) is None


@pytest.fixture
def matplotlib_charts(monkeypatch):
    monkeypatch.setenv(rb.CHART_RENDERER_ENV, "matplotlib")


@pytest.mark.parametrize("kind, build", [
    ("assessment", _va_report_request), ("comparison", _vc_report_request),
    ("sensitivity", _ms_report_request), ("bourne", _bp_report_request),
    ("heat-cool", _ht_cool_request), ("reaction-profile", _ht_rxn_request),
])
def test_every_report_kind_renders_with_charts_and_no_browser(kind, build, matplotlib_charts):
    report = service.render_report(kind, build().model_dump(mode="json"))
    assert report.content.startswith(b"%PDF") and report.filename.endswith(".pdf")
    if kind != "sensitivity":  # the protocol report has no charts
        assert b"/Subtype /Image" in report.content


def test_chart_export_falls_back_to_matplotlib_when_kaleido_fails(monkeypatch):
    monkeypatch.setattr(rb, "_kaleido_ok", None)
    monkeypatch.delenv(rb.CHART_RENDERER_ENV, raising=False)
    fig = go.Figure(go.Scatter(x=[1, 2, 3], y=[1, 4, 9]))
    def no_chrome(*_a, **_k):
        raise RuntimeError("Chrome not found")
    monkeypatch.setattr(go.Figure, "to_image", no_chrome)
    with pytest.warns(UserWarning, match="using matplotlib"):
        png = rb.fig_to_png_bytes(fig)
    assert png.startswith(b"\x89PNG") and rb._kaleido_ok is False
    assert rb.fig_to_png_bytes(fig).startswith(b"\x89PNG")  # no retry, no second warning
    monkeypatch.setenv(rb.CHART_RENDERER_ENV, "kaleido")
    with pytest.raises(RuntimeError):
        rb.fig_to_png_bytes(fig)


def test_request_validation_and_lookup_errors():
    with pytest.raises(LookupError):
        service.comparison_report(_vc_report_request().model_copy(update={"reactors": ["nope"]}))
    with pytest.raises(ValueError, match="Test 2"):
        service.bourne_snapshot(_bp_report_request().model_copy(
            update={"test2": [s.KpiResponse.model_construct(name="Yield", unit="%", low=float("nan"),
                                                            centre=100.0, high=101.0)]}))
    with pytest.raises(ValueError):
        service.heat_cool_snapshot(_ht_cool_request().model_copy(update={"T_jacket_C": 30.0}))
    with pytest.raises(LookupError):
        service.heat_cool_snapshot(_ht_cool_request().model_copy(update={"htm": "nope"}))
    with pytest.raises(KeyError):
        service.render_report("unknown", {})
