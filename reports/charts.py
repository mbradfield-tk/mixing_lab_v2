"""Request -> Plotly figure JSON: the bodies of ``POST /charts/{kind}``.

The figures are the same ``viz`` builders the Taipy pages bind, so a React page
rendering them with react-plotly.js shows the identical chart.
"""
from __future__ import annotations

from core import fluids, services
from core import repositories as repos
from core import schemas as s
from core import solvents
from core.envelope import surface_data
from core.heat_transfer import (
    SWEEP_PARAMETERS, compute_batch, compute_reaction_profile, resistance_breakdown,
    resistance_items, time_factor, ua_sweep_series,
)
from core.operating_point import evaluate_point
from reports.service import assessment_envelope, figure_json
from viz import bourne as viz_bourne
from viz import fluids as viz_fluids
from viz import heat_transfer as viz_ht
from viz import vessel as viz_vessel

SURFACE_N_PTS, SURFACE_V_PTS = 25, 15
_SWEEP_LABELS = {key: label for label, key in SWEEP_PARAMETERS.items()}


def assessment_envelope_chart(req: s.AssessmentReportRequest) -> s.ChartResult:
    fig, caption = assessment_envelope(req)
    return s.ChartResult(figures={"envelope": figure_json(fig)}, captions={"envelope": caption})


def assessment_surfaces_chart(req: s.AssessmentReportRequest) -> s.ChartResult:
    p = req.point
    inp, t_rxn, row = services.point_inputs(p, heat=False)
    params = [s.core_key(k) for k in req.envelope_parameters]
    if t_rxn <= 0 and any(k.startswith("Da_") for k in params):
        raise ValueError("Damköhler numbers need a reaction time or rate constant (> 0).")
    d = surface_data(lambda n, v: evaluate_point(inp, n / 60.0, v), row, p.N_rpm, p.V_L,
                     params, SURFACE_N_PTS, SURFACE_V_PTS)
    fig, rows = viz_vessel.assessment_surfaces(d["n_rpm"], d["v_l"], d["z"], params, p.N_rpm,
                                               p.V_L, d["op"], viz_vessel.LOG_PARAMS)
    caption = viz_vessel.assessment_surfaces_caption(d["n_rpm"], d["v_min"], d["v_max"],
                                                     SURFACE_N_PTS, SURFACE_V_PTS)
    return s.ChartResult(figures={"surfaces": figure_json(fig)}, captions={"surfaces": caption},
                         rows={"surfaces": rows})


def comparison_envelope_chart(req: s.ComparisonChartRequest) -> s.ChartResult:
    result = services.compare(req.comparison)
    wanted = [s.core_key(p) for p in req.parameters]
    chosen = [p for p in wanted if p in result["present"]] or result["present"][:1]
    fig, rows = viz_vessel.comparison_envelope(
        result["curve_data"], result["env_df"]["Reactor"].drop_duplicates().tolist(), chosen,
        viz_vessel.LOG_PARAMS)
    return s.ChartResult(figures={"envelope": figure_json(fig)}, rows={"envelope": rows})


def heat_cool_charts(req: s.HeatCoolRequest) -> s.ChartResult:
    data, htm_db, row, _labels = services.heat_cool_inputs(req)
    r = compute_batch(data, htm_db)
    f, label = time_factor(req.time_unit), req.time_unit.lower()
    ua = ua_sweep_series(data, htm_db, row, data["a_ht"])
    items = resistance_items(r.h_i, r.h_o, data["wall_k"], data["wall_thickness_mm"],
                             data["lining_k"], data["lining_thickness_mm"], data["fouling"])
    figs = {
        "temperature": viz_ht.batch_temperature(r.t_const / f, r.T_const, r.t_var / f, r.T_var,
                                                r.Tj_out, label, req.T_target_C, req.T_jacket_C),
        "duty": viz_ht.jacket_duty(r.t_const / f, r.q_const, r.t_var / f, r.q_var, label),
        "resistances": viz_ht.resistance_bars(resistance_breakdown(items)),
        "ua_vs_speed": viz_ht.ua_vs_speed(ua["rpm"], ua["ua_rpm"], data["n_rpm"], data["v_l"]),
        "ua_vs_volume": viz_ht.ua_vs_volume(ua["volume"], ua["ua_volume"], data["v_l"],
                                            data["n_rpm"]),
    }
    return s.ChartResult(figures={k: figure_json(v) for k, v in figs.items()})


def reaction_profile_chart(req: s.ReactionProfileRequest) -> s.ChartResult:
    data, htm_db, _row, _labels = services.reaction_profile_inputs(req)
    r = compute_reaction_profile(data, htm_db)
    f = time_factor(req.time_unit)
    fig = viz_ht.reaction_profile(r.t / f, r.T, r.conversion * 100.0, req.time_unit.lower(),
                                  req.T_jacket_C, r.T_adiabatic_c)
    return s.ChartResult(figures={"profile": figure_json(fig)})


def ua_surface_charts(req: s.UaSurfaceRequest) -> s.ChartResult:
    res = services.ua_surface(req)
    scale = viz_ht.sweep_colorscale(req.color_theme)
    x_name, y_name = _SWEEP_LABELS[req.x_parameter], _SWEEP_LABELS[req.y_parameter]
    figs = {
        "U": viz_ht.sweep_surface(res.x, res.y, res.U_W_m2K, x_name, y_name, res.U_limits, scale,
                                  "Overall Heat-Transfer Coefficient U", "U (W/m2.K)"),
        "UA": viz_ht.sweep_surface(res.x, res.y, res.UA_W_K, x_name, y_name, res.UA_limits,
                                   scale, "Overall Heat-Transfer Capacity UA", "UA (W/K)"),
    }
    return s.ChartResult(figures={k: figure_json(v) for k, v in figs.items()})


def bourne_speed_plan_chart(req: s.BournePlanRequest) -> s.ChartResult:
    data = services.bourne_speed_plan(req)
    if data is None:
        raise ValueError(f"'{req.reactor}' has no recorded fill-volume range.")
    return s.ChartResult(figures={"speed_plan": figure_json(viz_bourne.t1_speed_plan(data))})


def solvent_curves_chart(req: s.SolventStateRequest) -> s.ChartResult:
    fluids.solvent_state(req.name, req.P_atm, req.T_C)  # LookupError for unknown solvents
    fig = viz_fluids.property_curves(req.name, solvents.property_curves(req.name, req.P_atm),
                                     req.T_C)
    return s.ChartResult(figures={"properties": figure_json(fig)})


def blend_phases_chart(req: s.BlendRequest) -> s.ChartResult:
    res = fluids.blend({c.name: c.amount for c in req.components}, req.basis == "volume",
                       req.T_C, repos.fluids.load())
    fig = (viz_fluids.phase_stack(*res["phases"]) if res["phases"] is not None
           else viz_fluids.message("⚠️ Reactive pair — chemical reaction on mixing;<br>"
                                   "physical phase stratification does not apply."))
    return s.ChartResult(figures={"phases": figure_json(fig)})


# Endpoint table for ``POST /charts/{kind}``: request model and chart builder.
CHARTS = {
    "assessment-envelope": (s.AssessmentReportRequest, assessment_envelope_chart),
    "assessment-surfaces": (s.AssessmentReportRequest, assessment_surfaces_chart),
    "comparison-envelope": (s.ComparisonChartRequest, comparison_envelope_chart),
    "heat-cool": (s.HeatCoolRequest, heat_cool_charts),
    "reaction-profile": (s.ReactionProfileRequest, reaction_profile_chart),
    "ua-surface": (s.UaSurfaceRequest, ua_surface_charts),
    "bourne-speed-plan": (s.BournePlanRequest, bourne_speed_plan_chart),
    "solvent-properties": (s.SolventStateRequest, solvent_curves_chart),
    "blend-phases": (s.BlendRequest, blend_phases_chart),
}


def render_chart(kind: str, payload: dict) -> s.ChartResult:
    """Validate a JSON payload for ``kind`` and build its figures (KeyError for an unknown kind)."""
    model, build = CHARTS[kind]
    return build(model.model_validate(payload))
