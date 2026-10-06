"""Request -> result functions over the core calculations (future HTTP handler bodies).

Raise ``LookupError`` for unknown database names and ``ValueError`` for inputs
the calculations cannot use (map to HTTP 404 / 422).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from core import envelope, kinetics
from core import operating_point as op
from core import schemas as s
from core import sensitivity_rules as rules
from core.messages import Message
from core.records import VesselGeometry, fluid_props, reactor_row, sf
from core.serialize import jsonable
from utils.rom_registry import available_modes


def _reactor(name: str) -> pd.Series:
    row = reactor_row(name)
    if row.empty:
        raise LookupError(f"Unknown reactor '{name}'.")
    return row


def point_inputs(req: s.PointRequest, *, heat: bool = True
                 ) -> tuple[op.PointInputs, float, pd.Series]:
    """(core inputs, characteristic t_rxn in s, reactor row) for a point request."""
    row = _reactor(req.reactor)
    if req.corr_source not in available_modes(req.reactor):
        raise ValueError(f"Correlation source '{req.corr_source}' is not available for "
                         f"'{req.reactor}'.")
    g = req.geometry
    overrides = {k: v for k, v in (("D_tank", g.D_tank_m), ("D_imp", g.D_imp_m),
                                   ("Np", g.Np), ("Nq", g.Nq)) if v is not None}
    geometry = VesselGeometry.from_row(
        row, H_max_fallback=g.D_tank_m or sf(row.get("D_tank_m"))).with_overrides(**overrides)
    if geometry.D_tank <= 0 or geometry.D_imp <= 0:
        raise ValueError(f"Geometry of '{req.reactor}' is incomplete; supply "
                         "geometry.D_tank_m and geometry.D_imp_m.")

    f, rx = req.fluid, req.reaction
    props = fluid_props(f.name, f.T_C)
    t_rxn = kinetics.effective_t_rxn(rx.order, rx.k, rx.C0_mol_L, rx.t_rxn_s)
    sol = req.solids
    inp = op.PointInputs(
        reactor=req.reactor, geometry=geometry,
        fluid=op.Fluid(f.name, f.rho_kg_m3 or props["rho"], f.mu_Pa_s or props["mu"],
                       f.D_mol_m2_s or props["D_mol"]),
        reaction=op.Reaction(rx.order, rx.k, rx.C0_mol_L, t_rxn, rx.dH_kJ_mol),
        corr_mode=req.corr_source,
        gas=op.Gas(req.gas.v_s_m_s, req.gas.coalescing),
        solids=(op.Solids(rho_p=sol.rho_p_kg_m3, d50_um=sol.d50_um, phi=sol.sphericity,
                          x_wt=sol.loading_g_per_100g, S_zw=sol.zwietering_S,
                          gmb_z=sol.gmb_z, cd=sol.clearance_ratio) if sol else None),
        feed=op.Feed(req.feed.location, req.feed.d_pipe_mm / 1000.0) if req.feed else None,
        heat=(op.Heat(req.heat.T_process_C, req.heat.T_coolant_C)
              if heat and req.heat else None),
    )
    return inp, t_rxn, row


def _require_t_rxn(t_rxn: float, fields: list[str]) -> None:
    if t_rxn <= 0 and any(p.startswith("Da_") for p in fields):
        raise ValueError("Damköhler numbers need a reaction time or rate constant (> 0).")


def _evaluator(inp: op.PointInputs):
    return lambda n_rpm, v_l: op.evaluate_point(inp, n_rpm / 60.0, v_l)


def point_result(values: dict) -> s.PointResult:
    known = {k: jsonable(v) for k, v in values.items() if k in s.CORE_KEYS}
    extra = {str(k): v for k, v in ((k, jsonable(v)) for k, v in values.items()
                                    if k not in s.CORE_KEYS)
             if v is None or isinstance(v, (int, float, str))}
    return s.PointResult.model_validate({**known, "extra": extra})


def evaluate(req: s.PointRequest) -> s.PointResult:
    inp, t_rxn, _row = point_inputs(req)
    if t_rxn <= 0:
        raise ValueError("Provide a reaction time or rate constant (> 0) to compute "
                         "Damköhler numbers.")
    return point_result(op.evaluate_point(inp, req.N_rpm / 60.0, req.V_L))


def solve(req: s.SolveRequest) -> s.SolveResult:
    inp, t_rxn, row = point_inputs(req.point, heat=False)
    _require_t_rxn(t_rxn, [req.parameter])
    res = envelope.solve_operating_point(
        _evaluator(inp), row, s.core_key(req.parameter), req.target, req.solve_for,
        req.point.N_rpm, req.point.V_L)
    best = res["first_in_window"]
    status = "unreachable" if not res["roots"] else (
        "outside_vessel_range" if best is None else "solved")
    return s.SolveResult(
        parameter=req.parameter, target=req.target, solve_for=req.solve_for, status=status,
        best=best,
        solutions=[s.SolveRoot(value=x, achieved=jsonable(a), in_vessel_range=ok)
                   for x, a, ok in zip(res["roots"], res["achieved"], res["in_window"])],
        search_range=res["search"], vessel_range=res["window"],
        achievable_span=jsonable(res["span"]))


def sweep(req: s.SweepRequest) -> s.SweepResult:
    inp, t_rxn, row = point_inputs(req.point, heat=False)
    _require_t_rxn(t_rxn, req.parameters)
    n_arr, v_min, v_max = envelope.operating_window(row, req.point.N_rpm, req.point.V_L,
                                                    n_pts=req.n_points)
    volumes = req.volumes_L or [v_min, v_max]
    keys = {p: s.core_key(p) for p in req.parameters}
    curves = envelope.sweep(_evaluator(inp), n_arr, volumes, list(keys.values()))
    return s.SweepResult(
        N_rpm=jsonable(n_arr), vessel_V_range_L=(v_min, v_max),
        curves=[s.SweepCurve(V_L=v, parameter=p, values=jsonable(curves[v][k]))
                for v in curves for p, k in keys.items()])


def surface(req: s.SurfaceRequest) -> s.SurfaceResult:
    inp, t_rxn, row = point_inputs(req.point, heat=False)
    _require_t_rxn(t_rxn, req.parameters)
    n_full, v_min, v_max = envelope.operating_window(row, req.point.N_rpm, req.point.V_L)
    n_arr = np.linspace(n_full[0], n_full[-1], req.n_points)
    v_arr = np.linspace(v_min, v_max, req.v_points)
    keys = {p: s.core_key(p) for p in req.parameters}
    z = envelope.surface_grid(_evaluator(inp), n_arr, v_arr, list(keys.values()))
    return s.SurfaceResult(N_rpm=jsonable(n_arr), V_L=jsonable(v_arr),
                           z={p: jsonable(z[k]) for p, k in keys.items()})


# ---------------------------------------------------------------------------
# Reaction Sensitivity Protocol
# ---------------------------------------------------------------------------
def protocol_inputs(req: s.ProtocolRequest) -> rules.ProtocolInputs:
    rx = req.reaction
    return rules.ProtocolInputs(
        order=rx.order, k=rx.k, C0=rx.C0_mol_L, t_specified=rx.t_rxn_s, dH=rx.dH_kJ_mol,
        rxn_type=req.reaction_type, kinetics=req.kinetics, bourne=req.bourne,
        bourne_mech=req.bourne_mechanism or "", bourne_tests_done=list(req.bourne_tests_done),
        bourne_rows=[{"Test": r.test, "Finding": r.finding, "Sensitive KPI(s)": r.sensitive_kpis}
                     for r in req.bourne_results],
        semi_batch=req.semi_batch, phases=list(req.phases), competing=req.competing or "",
        dh_override=req.dh_override_kJ_mol, dh_override_measured=req.dh_override_measured,
        dh_action=req.dh_action or "",
        dh_ref_value=req.dh_reference_kJ_mol if req.dh_action == "estimate" else 0.0,
        c0_heat=req.c0_heat_mol_L, rho_cp=req.rho_cp_kJ_m3K)


def _message(m: Message) -> s.MessageOut:
    return s.MessageOut(kind=m.kind, code=m.code, text=m.text)


def assess(req: s.ProtocolRequest) -> s.ProtocolResult:
    v = req.screening_vessel
    damkohler_for = None
    if v is not None:
        _reactor(v.reactor)
        damkohler_for = lambda t: op.screening_damkohler(  # noqa: E731
            v.reactor, v.N_rpm, v.V_L, v.solvent, v.T_C, t)
    res = rules.assess_protocol(protocol_inputs(req), damkohler_for)
    kin, da = res["kinetics"], res["da"]
    return s.ProtocolResult(
        ready=res["ready"], verdict=_message(res["verdict"]),
        steps=[_message(m) if m else None for m in res["steps"]],
        findings=[s.FindingOut(area=f.area, kind=f.kind, status=f.status, detail=f.detail,
                               code=f.code) for f in res["findings"]],
        next_steps=[s.ActionOut(area=a.area, action=a.action, code=a.code)
                    for a in res["next_steps"]],
        kinetics=s.KineticsOut(order=kin["order"], rate_law=kin["law"],
                               t_rxn_s=jsonable(kin["t_rxn"]), t_90_s=jsonable(kin["t_90"]),
                               basis=kin["basis"]),
        heat=s.HeatOut(has_enthalpy=res["has_enthalpy"], resolved=res["heat_resolved"],
                       dH_eff_kJ_mol=jsonable(res["dH_eff"]), dT_ad_K=jsonable(res["dt_ad"]),
                       estimated=res["dh_estimated"], summary=res["heat_summary"]),
        damkohler=(s.ScreeningDamkohler(
            reactor=da["reactor"], N_rpm=da["N_rpm"], V_L=da["V_L"], fluid=da["fluid"],
            t_blend_s=jsonable(da["t_blend"]), t_E_s=jsonable(da["t_E"]), Re=jsonable(da["Re"]),
            P_V_W_L=jsonable(da["P_V_W_L"]), Da_macro=jsonable(da["Da_macro"]),
            Da_micro=jsonable(da["Da_micro"])) if da else None),
        bourne_sensitive=res["b_sensitive"], bourne_mechanisms=list(res["b_mechs"]),
    )
