"""Request -> report services: the bodies of ``POST /reports/{kind}`` and the
figure endpoints. Each returns plain bytes / JSON-ready dicts; no GUI state."""
from __future__ import annotations

import json
from dataclasses import dataclass

import pandas as pd
import plotly.graph_objects as go

from core import schemas as s
from core import bourne_io
from core.records import range_midpoint, sf
from core import scale_up
from core import sensitivity_rules as rules
from core import services
from core.envelope import envelope_data
from core.operating_point import evaluate_point
from core.options import Competing, CorrSource
from core.serialize import jsonable
from reports import snapshots
from reports import bourne_tables as btables
from reports import comparison_tables as ctables
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
    if not inp.reaction.present:
        keys = [k for k in keys if not k.startswith("Da_")] or ["P/V (W/L)"]
    p = req.point
    d = envelope_data(lambda n_rpm, v_l: evaluate_point(inp, n_rpm / 60.0, v_l), row,
                      p.N_rpm, p.V_L, keys)
    fig, _rows = viz_vessel.assessment_envelope(
        d["n_rpm"], d["hi"], d["lo"], d["v_min"], d["v_max"], keys, p.N_rpm, d["op"],
        viz_vessel.LOG_PARAMS)
    return fig, viz_vessel.assessment_envelope_caption(d["v_min"], d["v_max"])


def assessment_result(req: s.PointRequest) -> s.AssessmentTables:
    """The Vessel Assessment result tables for one operating point (page / PDF formatting)."""
    inp, t_rxn, row = services.point_inputs(req)
    services.require_kinetics(req, t_rxn)
    hydro = evaluate_point(inp, req.N_rpm / 60.0, req.V_L)
    solids_on, gas_on = req.solids is not None, req.gas.present
    tables = assessment_tables(hydro, req.N_rpm, t_rxn, solids_on=solids_on, gas_on=gas_on,
                               fed_on=req.feed is not None)
    return s.AssessmentTables(
        point=services.point_result(hydro), t_rxn_s=t_rxn,
        **{k: jsonable(tables[k]) for k in ("hydro", "damkohler", "mass_transfer", "solids", "heat")},
        assessment=tables["assessment"],
        applicability=rules.correlation_applicability(hydro, inp.geometry, row, req.V_L,
                                                      gas_on=gas_on, solids_on=solids_on))


def assessment_snapshot(req: s.AssessmentReportRequest) -> dict:
    p = req.point
    inp, t_rxn, _row = services.point_inputs(p)
    services.require_kinetics(p, t_rxn)
    hydro = evaluate_point(inp, p.N_rpm / 60.0, p.V_L)
    tables = assessment_tables(hydro, p.N_rpm, t_rxn, solids_on=p.solids is not None,
                               gas_on=p.gas.present, fed_on=p.feed is not None)
    fig, caption = assessment_envelope(req)
    return snapshots.assessment_snapshot(
        reactor=p.reactor, fluid=p.fluid.name, T_C=p.fluid.T_C, P_atm=p.fluid.P_atm, N_rpm=p.N_rpm,
        V_L=p.V_L, corr_label=CorrSource(p.corr_source).label,
        reaction=req.reaction_name or ("" if p.reaction else "No reaction"),
        t_rxn=t_rxn, dH=p.reaction.dH_kJ_mol if p.reaction else 0.0, tables=tables, env_fig=fig,
        env_caption=caption,
        env_params=[k for k in (s.core_key(k) for k in req.envelope_parameters)
                    if p.reaction or not k.startswith("Da_")])


def assessment_report(req: s.AssessmentReportRequest) -> ReportFile:
    snap = assessment_snapshot(req)
    return ReportFile(rb.report_filename("Vessel_Assessment", req.point.reactor),
                      rb.build_vessel_assessment_pdf(snap))


def protocol_page(req: s.ProtocolRequest) -> s.ProtocolPage:
    """Reaction Sensitivity Protocol results as the page shows them."""
    res = services.run_protocol(req)
    md = rules.protocol_md(res)
    return s.ProtocolPage(
        ready=res["ready"], show_dh_action=res["show_dh_action"],
        steps=[md[f"step{n}"] for n in range(6)], kinetics_md=md["kinetics_md"],
        dt_ad_caption=md["dt_ad_caption"], da_caption=md["da_caption"],
        trxn_caption=md["trxn_caption"], summary_note=md["summary_note"],
        verdict=md["verdict"] if res["ready"] else "",
        verdict_kind=res["verdict"].kind,
        findings=[{"Sensitivity Type": m, "Finding": f"{st} - {d}"} for m, st, d in md["findings"]],
        next_steps=jsonable(pd.DataFrame(md["next_steps"])),
        insights=[s.FindingOut(area=f.area, kind=f.kind, status=f.status, detail=f.detail, code=f.code)
                  for f in res["findings"]],
        actions=[s.ActionOut(area=a.area, action=a.action, code=a.code) for a in res["next_steps"]],
        t_rxn_s=jsonable(res["t_rxn"]) if res["kinetics_known"] else None,
        damkohler=services.screening_damkohler_out(res["da"]))


def protocol_snapshot(req: s.ProtocolReportRequest) -> dict:
    res = services.run_protocol(req.protocol)
    competing = req.protocol.competing
    snap = snapshots.protocol_snapshot(
        res, rules.protocol_md(res), reaction=req.reaction_name,
        competing_label=Competing(competing).label if competing else "",
        bourne_meta=dict(req.bourne_meta))
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
def comparison_page(req: s.ComparisonPageRequest) -> s.ComparisonTables:
    """Every Vessel Comparison result table (page formatting) for one request."""
    c = req.comparison
    names = list(c.reactors)
    cmp = services.compare(c)
    env_df, agg_df, present, info = cmp["env_df"], cmp["agg_df"], cmp["present"], cmp["reactor_info"]
    tables = ctables.summary_tables(env_df, agg_df, present)
    heat = ctables.heat_table(env_df, info) if cmp["incl_heat"] else pd.DataFrame()

    scaling = {"scale": pd.DataFrame(), "full": pd.DataFrame(), "pct": pd.DataFrame()}
    sc = req.scale_up
    if sc is not None and len(names) >= 2:
        if sc.basis_reactor not in names:
            raise ValueError("scale_up.basis_reactor must be one of the compared vessels.")
        solve_rpm = sc.solve_for == "N_rpm"
        known = {**scale_up.target_defaults(names, sc.basis_reactor, solve_rpm), **sc.fixed}
        match = scale_up.scale_up_match(names, info, cmp["inputs"], sc.basis_reactor,
                                        s.core_key(sc.parameter), sc.basis_N_rpm, sc.basis_V_L,
                                        solve_rpm=solve_rpm, known=known)
        scaling = ctables.scaling_tables(match, sc.basis_reactor)

    feed_rows, feed_ok, feed_warning = [], True, ""
    if c.feed is not None and req.feed_schedule is not None and info:
        fs = req.feed_schedule
        feed_rows, exceeded, error = scale_up.feed_plan(info, fs.basis_reactor, fs.volume_mL,
                                                        fs.time_h)
        feed_ok = not error and not exceeded
        if exceeded:
            feed_warning = "Feed volume exceeds max volume for: " + "; ".join(exceeded)

    if feed_ok:
        status = (f"Compared {len(info)} vessel(s) across the 4-corner envelope "
                  f"({CorrSource(c.corr_source).label}).")
        if cmp["skipped"]:
            status += f" Skipped (missing geometry): {', '.join(cmp['skipped'])}."
    else:
        status = ("Fed-batch feed volume exceeds max volume for one or more vessels — "
                  "adjust the feed schedule and recompute.")
    defaults = [p for p in scale_up.DEFAULT_PLOT_PARAMS if p in present] or present[:4]
    return s.ComparisonTables(
        status=status, feed_ok=feed_ok, feed_warning=feed_warning,
        parameters=[s.ParameterOption(field=s.CORE_KEYS[k], label=k, default=k in defaults)
                    for k in present if k in s.CORE_KEYS],
        summary=jsonable(tables["summary"]), detail=jsonable(tables["detail"]),
        rpm_ref=jsonable(tables["rpm_ref"]), heat=jsonable(heat),
        scale=jsonable(scaling["scale"]), scale_full=jsonable(scaling["full"]),
        scale_pct=jsonable(scaling["pct"]),
        impact=jsonable(pd.DataFrame(scale_up.impact_ratios(env_df, present, cmp["incl_heat"]))),
        feed_plan=jsonable(pd.DataFrame(feed_rows)), skipped=list(cmp["skipped"]))


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
def bourne_defaults(name: str) -> s.BourneDefaults:
    """Working-volume / centre-RPM defaults and the reactor-limits table for a vessel."""
    row = services.bourne_reactor(name)
    return s.BourneDefaults(
        V_L=range_midpoint(row, "V_L_min", "V_L_max", sf(row.get("V_L"), 1.0)),
        centre_rpm=range_midpoint(row, "N_rpm_min", "N_rpm_max", 300.0),
        reactor_limits=jsonable(btables.reactor_limits(row)))


def bourne_plan_tables(req: s.BournePlanRequest) -> s.BournePlanTables:
    """Formatted Test 1-3 condition tables, setpoints and reactor limits (page formatting)."""
    p = services.bourne_plan(req)
    setpoints = [{"Step": sp.step, "Volume (L)": sp.V_L,
                  "Low (RPM)": (sp.low_rpm, "low" in sp.clamped),
                  "Centre (RPM)": (sp.centre_rpm, "centre" in sp.clamped),
                  "High (RPM)": (sp.high_rpm, "high" in sp.clamped)} for sp in p.setpoints]
    sp_df, caption = btables.setpoints_table(setpoints, any(sp.clamped for sp in p.setpoints))
    return s.BournePlanTables(
        centre_pm_W_kg=p.centre_pm_W_kg, centre_info=p.centre_info,
        test1_pm_span=p.test1_pm_span, has_speed_plan=p.speed_plan is not None,
        reactor_limits=jsonable(btables.reactor_limits(services.bourne_reactor(req.reactor))),
        test1=jsonable(btables.test1_table(p.test1)), setpoints=jsonable(sp_df),
        setpoints_caption=caption, test2=jsonable(btables.test2_table(p.test2)),
        test3=jsonable(btables.test3_table(
            [{**r, "Feed location": btables.T3_PAGE_LABELS.get(r["Feed location"], r["Feed location"])}
             for r in p.test3])))


def bourne_sensitivity_csv(req: s.BourneReportRequest) -> ReportFile:
    """The field/value CSV the Reaction Sensitivity Protocol imports (Step 0 pre-screen)."""
    ev = services.bourne_evaluation(req)
    meta = req.project.model_dump()
    kpis = {n: (ev["results"][n] or {}).get("sensitive_names", "") for n in (1, 2, 3)}
    rows = bourne_io.export_rows(
        ev["outcome"], {**meta, "reactor": req.reactor, "fluid": req.fluid,
                        "working_volume_L": ev["system"].V_L}, kpis)
    name = rb.report_filename(rb.report_header_label(meta) or req.reactor).replace(".pdf", ".csv")
    return ReportFile(name, bourne_io.write_csv(rows), "text/csv")


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
