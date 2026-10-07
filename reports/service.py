"""Request -> report services: the bodies of ``POST /reports/{kind}`` and the
figure endpoints. Each returns plain bytes / JSON-ready dicts; no GUI state."""
from __future__ import annotations

import json
from dataclasses import dataclass

import plotly.graph_objects as go

from core import schemas as s
from core import sensitivity_rules as rules
from core import services
from core.envelope import envelope_data
from core.operating_point import evaluate_point
from core.options import Competing, CorrSource
from reports import snapshots
from reports.tables import assessment_tables
from reports import pdf as rb
from viz import vessel as viz_vessel


@dataclass(frozen=True)
class ReportFile:
    filename: str
    content: bytes
    media_type: str = "application/pdf"


def figure_json(fig: go.Figure) -> dict:
    """Plain-JSON Plotly figure (``{"data": [...], "layout": {...}}``) for react-plotly.js."""
    return json.loads(fig.to_json())


def assessment_envelope(req: s.AssessmentReportRequest) -> tuple[go.Figure, str]:
    """(operating-envelope figure, caption) for the requested parameters."""
    inp, _t_rxn, row = services.point_inputs(req.point, heat=False)
    keys = [s.core_key(p) for p in req.envelope_parameters]
    p = req.point
    d = envelope_data(lambda n_rpm, v_l: evaluate_point(inp, n_rpm / 60.0, v_l), row,
                      p.N_rpm, p.V_L, keys)
    fig, _rows = viz_vessel.assessment_envelope(
        d["n_rpm"], d["hi"], d["lo"], d["v_min"], d["v_max"], keys, p.N_rpm, d["op"],
        viz_vessel.LOG_PARAMS)
    return fig, viz_vessel.assessment_envelope_caption(d["v_min"], d["v_max"])


def assessment_snapshot(req: s.AssessmentReportRequest) -> dict:
    p = req.point
    inp, t_rxn, _row = services.point_inputs(p)
    if t_rxn <= 0:
        raise ValueError("Provide a reaction time or rate constant (> 0) to compute "
                         "Damköhler numbers.")
    hydro = evaluate_point(inp, p.N_rpm / 60.0, p.V_L)
    tables = assessment_tables(hydro, p.N_rpm, t_rxn, solids_on=p.solids is not None,
                               gas_on=p.gas.present, fed_on=p.feed is not None)
    fig, caption = assessment_envelope(req)
    return snapshots.assessment_snapshot(
        reactor=p.reactor, fluid=p.fluid.name, T_C=p.fluid.T_C, P_atm=1.0, N_rpm=p.N_rpm,
        V_L=p.V_L, corr_label=CorrSource(p.corr_source).label, reaction=req.reaction_name,
        t_rxn=t_rxn, dH=p.reaction.dH_kJ_mol, tables=tables, env_fig=fig, env_caption=caption,
        env_params=[s.core_key(k) for k in req.envelope_parameters])


def assessment_report(req: s.AssessmentReportRequest) -> ReportFile:
    snap = assessment_snapshot(req)
    return ReportFile(rb.report_filename("Vessel_Assessment", req.point.reactor),
                      rb.build_vessel_assessment_pdf(snap))


def protocol_snapshot(req: s.ProtocolReportRequest) -> dict:
    res = services.run_protocol(req.protocol)
    competing = req.protocol.competing
    snap = snapshots.protocol_snapshot(
        res, rules.protocol_md(res), reaction=req.reaction_name,
        competing_label=Competing(competing).label if competing else "")
    snap.update(snapshots.project_meta(**req.project.model_dump()))
    return snap


def protocol_report(req: s.ProtocolReportRequest) -> ReportFile:
    snap = protocol_snapshot(req)
    return ReportFile(
        rb.report_filename("RxnSens", rb.report_header_label(snap) or req.reaction_name),
        rb.build_protocol_pdf(snap))


# ---------------------------------------------------------------------------
# Vessel Comparison
# ---------------------------------------------------------------------------
def comparison_snapshot(req: s.ComparisonRequest) -> dict:
    return snapshots.comparison_snapshot(services.compare(req), scale_param=req.scale_param,
                                         scale_basis_reactor=req.scale_basis_reactor)


def comparison_envelope(req: s.ComparisonRequest, params: list[str] | None = None) -> go.Figure:
    """Multi-vessel envelope figure (``params`` are result-dict keys; default: first present)."""
    result = services.compare(req)
    chosen = [p for p in (params or []) if p in result["present"]] or result["present"][:1]
    fig, _rows = viz_vessel.comparison_envelope(
        result["curve_data"], result["env_df"]["Reactor"].drop_duplicates().tolist(), chosen,
        viz_vessel.LOG_PARAMS)
    return fig


def comparison_report(req: s.ComparisonRequest) -> ReportFile:
    snap = comparison_snapshot(req)
    names = snap["selected_names"]
    return ReportFile(rb.report_filename("Vessel_Comparison", names[0] if names else ""),
                      rb.build_reactor_comparison_pdf(snap))


# ---------------------------------------------------------------------------
# Bourne Protocol
# ---------------------------------------------------------------------------
def bourne_snapshot(req: s.BourneReportRequest) -> dict:
    ev = services.bourne_evaluation(req)
    return snapshots.bourne_snapshot(
        reactor=req.reactor, fluid=req.fluid, V_L=ev["system"].V_L,
        dominant=ev["outcome"]["dominant"], conclusions=ev["conclusions"],
        t1_rows=ev["t1_rows"], t1_result=ev["results"][1], centerpoint=ev["centerpoint"],
        t2=ev["t2"], t3=ev["t3"], project=snapshots.project_meta(**req.project.model_dump()))


def bourne_report(req: s.BourneReportRequest) -> ReportFile:
    snap = bourne_snapshot(req)
    return ReportFile(rb.report_filename("Bourne", rb.report_header_label(snap) or req.reactor),
                      rb.build_bourne_protocol_pdf(snap))


# ---------------------------------------------------------------------------
# Heat Transfer
# ---------------------------------------------------------------------------
def heat_cool_snapshot(req: s.HeatCoolRequest) -> dict:
    data, htm_db, row, labels = services.heat_cool_inputs(req)
    return snapshots.heat_cool_snapshot(
        data, htm_db, row, reactor=req.reactor, fluid=req.fluid,
        wall_material=labels["wall_material"], lining_material=labels["lining_material"],
        time_unit=req.time_unit, project=snapshots.project_meta(**req.project.model_dump()))


def reaction_profile_snapshot(req: s.ReactionProfileRequest) -> dict:
    data, htm_db, _row, _labels = services.reaction_profile_inputs(req)
    return snapshots.reaction_snapshot(
        data, htm_db, reactor=req.reactor, fluid=req.fluid, time_unit=req.time_unit,
        project=snapshots.project_meta(**req.project.model_dump()))


def _heat_report(snap: dict, reactor: str) -> ReportFile:
    return ReportFile(rb.report_filename("HeatTransfer", rb.report_header_label(snap) or reactor),
                      rb.build_heat_transfer_pdf(snap))


def heat_cool_report(req: s.HeatCoolRequest) -> ReportFile:
    return _heat_report(heat_cool_snapshot(req), req.reactor)


def reaction_profile_report(req: s.ReactionProfileRequest) -> ReportFile:
    return _heat_report(reaction_profile_snapshot(req), req.reactor)


# Endpoint table for ``POST /reports/{kind}``: request model and report builder.
REPORTS = {
    "assessment": (s.AssessmentReportRequest, assessment_report),
    "comparison": (s.ComparisonRequest, comparison_report),
    "sensitivity": (s.ProtocolReportRequest, protocol_report),
    "bourne": (s.BourneReportRequest, bourne_report),
    "heat-cool": (s.HeatCoolRequest, heat_cool_report),
    "reaction-profile": (s.ReactionProfileRequest, reaction_profile_report),
}


def render_report(kind: str, payload: dict) -> ReportFile:
    """Validate a JSON payload for ``kind`` and build the PDF (KeyError for an unknown kind)."""
    model, build = REPORTS[kind]
    return build(model.model_validate(payload))
