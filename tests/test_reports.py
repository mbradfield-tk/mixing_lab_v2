"""Report services: request -> snapshot/PDF must match the golden page snapshots."""

import json
import os
import sys

import plotly.graph_objects as go
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import golden_helpers as gh  # noqa: E402  (tests/ is on sys.path under pytest)
from core import schemas as s
from reports import service
from reports import pdf as rb

GOLDEN = gh.REPORT_OUTPUTS
REQ = gh.REQUESTS


def _va_report_request() -> s.AssessmentReportRequest:
    return s.AssessmentReportRequest.model_validate(REQ["va_report"])


def _ms_report_request() -> s.ProtocolReportRequest:
    return s.ProtocolReportRequest.model_validate(REQ["ms_report"])


def test_assessment_snapshot_matches_vessel_assessment_page():
    got = json.loads(json.dumps(gh.snapshot_norm(service.assessment_snapshot(_va_report_request())),
                                ensure_ascii=False))
    assert gh.first_diff(got, GOLDEN["va"]["snap"]) is None


def test_protocol_snapshot_matches_mixing_sensitivity_page():
    got = json.loads(json.dumps(gh.snapshot_norm(service.protocol_snapshot(_ms_report_request())),
                                ensure_ascii=False))
    assert gh.first_diff(got, GOLDEN["ms"]["snap"]) is None


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
    return s.ComparisonRequest.model_validate(REQ["vc_report"])


def _bp_report_request() -> s.BourneReportRequest:
    return s.BourneReportRequest.model_validate(REQ["bp_report"])


def _ht_cool_request() -> s.HeatCoolRequest:
    return s.HeatCoolRequest.model_validate(REQ["ht_cool"])


def _ht_rxn_request() -> s.ReactionProfileRequest:
    return s.ReactionProfileRequest.model_validate(REQ["ht_rxn"])


@pytest.fixture
def fake_png(monkeypatch):
    monkeypatch.setattr(rb, "fig_to_png_bytes", lambda fig: gh.fig_key(fig).encode())


@pytest.mark.parametrize("golden_name, build", [
    ("vc", lambda: service.comparison_snapshot(_vc_report_request())),
    ("bp", lambda: service.bourne_snapshot(_bp_report_request())),
    ("ht_batch", lambda: service.heat_cool_snapshot(_ht_cool_request())),
    ("ht_reaction", lambda: service.reaction_profile_snapshot(_ht_rxn_request())),
])
def test_endpoint_snapshots_match_pages(golden_name, build, fake_png):
    got = json.loads(json.dumps(gh.snapshot_norm(build()), ensure_ascii=False))
    if golden_name == "bp":  # report-only additions (not in the page snapshot)
        assert got.pop("T_C") == REQ["bp_report"]["T_C"]
        info = dict(got.pop("vessel_info"))
        assert {"Impeller type", "Impeller diameter", "Working volume range"} <= set(info)
    assert gh.first_diff(got, GOLDEN[golden_name]["snap"]) is None


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
