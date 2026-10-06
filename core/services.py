"""Request -> result functions over the core calculations (future HTTP handler bodies).

Raise ``LookupError`` for unknown database names and ``ValueError`` for inputs
the calculations cannot use (map to HTTP 404 / 422).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from core import bourne_plan as plan
from core import envelope, kinetics, scale_up
from core import operating_point as op
from core import schemas as s
from core import sensitivity_rules as rules
from core.messages import Message
from core.options import FeedBasis, FeedLocation
from core.records import (
    DATA_DIR, VesselGeometry, fluid_props, range_midpoint, reactor_row, sf, thermal_props,
)
from core.serialize import jsonable
from core.heat_transfer import (
    LINING_CONDUCTIVITY, LINING_THICKNESS_DEFAULT, NUSSELT_CORRELATIONS, WALL_CONDUCTIVITY,
    find_best_material_key, heat_cool_setup_error, load_csvs, reactor_jacket_area,
)
from utils import bourne_kpi
from utils.rom_registry import available_modes, available_modes_multi


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
    props = fluid_props(f.name, f.T_C, f.P_atm)
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


def run_protocol(req: s.ProtocolRequest) -> dict:
    """Raw ``assess_protocol`` result (structured messages) for a request."""
    v = req.screening_vessel
    damkohler_for = None
    if v is not None:
        _reactor(v.reactor)
        damkohler_for = lambda t: op.screening_damkohler(  # noqa: E731
            v.reactor, v.N_rpm, v.V_L, v.solvent, v.T_C, t)
    return rules.assess_protocol(protocol_inputs(req), damkohler_for)


def assess(req: s.ProtocolRequest) -> s.ProtocolResult:
    res = run_protocol(req)
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


# ---------------------------------------------------------------------------
# Vessel Comparison
# ---------------------------------------------------------------------------
def comparison_context(req: s.ComparisonRequest) -> dict:
    """Shared comparison conditions (``core.scale_up.compare_vessels`` ctx) for a request."""
    for name in req.reactors:
        _reactor(name)
    if req.corr_source not in available_modes_multi(list(req.reactors)):
        raise ValueError(f"Correlation source '{req.corr_source}' is not available for every "
                         "selected vessel.")
    f, rx, sol = req.fluid, req.reaction, req.solids
    props = fluid_props(f.name, f.T_C, f.P_atm)
    fed, incl_h, incl_p = req.feed is not None, rx.dH_kJ_mol != 0.0, sol is not None
    return {
        "rho": f.rho_kg_m3 or props["rho"], "mu": f.mu_Pa_s or props["mu"],
        "D_mol": f.D_mol_m2_s or props["D_mol"],
        "v_s": req.gas.v_s_m_s if req.gas.present else 0.0, "coalescing": req.gas.coalescing,
        "t_rxn": kinetics.effective_t_rxn(rx.order, rx.k, rx.C0_mol_L, rx.t_rxn_s, fallback=1.0),
        "order": rx.order, "k": rx.k, "C0": rx.C0_mol_L, "dH": rx.dH_kJ_mol,
        "incl_heat": incl_h, "incl_particles": incl_p, "gas_on": req.gas.present, "fed": fed,
        "feed_pipe_mm": dict(req.feed.pipe_id_mm) if fed else {},
        "feed_loc": req.feed.location if fed else FeedLocation.BULK,
        "rho_p": sol.rho_p_kg_m3 if sol else 0.0, "d50": sol.d50_um if sol else 0.0,
        "phi": sol.sphericity if sol else 1.0, "x_wt": sol.loading_g_per_100g if sol else 0.0,
        "szw": sol.zwietering_S if sol else 5.5, "gmb_z": sol.gmb_z if sol else 3.0,
        "cd": sol.clearance_ratio if sol else 0.33,
        "T_process": f.T_C, "T_coolant": req.T_coolant_C, "fluid_name": f.name,
        "plot_params": scale_up.plot_params(fed, incl_h, incl_p), "corr_mode": req.corr_source,
    }


def compare(req: s.ComparisonRequest) -> dict:
    """``compare_vessels`` result plus the cache keys the comparison report reads."""
    ctx = comparison_context(req)
    cmp = scale_up.compare_vessels(list(req.reactors), ctx)
    if cmp["env_df"] is None:
        raise ValueError("None of the selected vessels has complete geometry and speed data.")
    return {**cmp, "ctx": ctx, "fluid_name": req.fluid.name, "fluid_T_C": req.fluid.T_C,
            "rxn_name": req.reaction_name, "t_rxn": ctx["t_rxn"],
            "incl_heat": ctx["incl_heat"], "incl_particles": ctx["incl_particles"]}


# ---------------------------------------------------------------------------
# Bourne Protocol
# ---------------------------------------------------------------------------
def bourne_system(req: s.BourneReportRequest) -> plan.BourneSystem:
    row = _reactor(req.reactor)
    v_l = req.V_L or range_midpoint(row, "V_L_min", "V_L_max", sf(row.get("V_L"), 1.0))
    props = fluid_props(req.fluid, req.T_C, req.P_atm)
    geo = VesselGeometry.from_row(row)
    return plan.BourneSystem(
        D_imp=req.D_imp_m or sf(row.get("D_imp_m"), 0.05), Np=req.Np or sf(row.get("Np"), 5.0),
        rho=props["rho"], mu=props["mu"], D_mol=props["D_mol"], V_L=v_l,
        n_min=sf(row.get("N_rpm_min"), 0.0), n_max=sf(row.get("N_rpm_max"), 1000.0),
        D_tank=geo.D_tank, H_liquid=geo.liquid_height(v_l))


def kpi_assessment(rows: list[s.KpiResponse], test: int) -> dict:
    """``utils.bourne_kpi.assess_kpis`` result for one test's KPI responses."""
    low, ctr, high = bourne_kpi.KPI_COLUMNS[test]
    df = pd.DataFrame([{
        "KPI": r.name, "Unit": r.unit, low: r.low, ctr: r.centre, high: r.high,
        "Std dev": np.nan if r.std_dev is None else r.std_dev,
        "Replicates": np.nan if r.replicates is None else r.replicates,
    } for r in rows])
    res = bourne_kpi.assess_kpis(df, test)
    if res is None:
        raise ValueError(f"Test {test}: every KPI needs low, centre and high responses.")
    return res


def bourne_evaluation(req: s.BourneReportRequest) -> dict:
    """Test conditions, KPI verdicts and decision-tree outcome for the Bourne report."""
    sys = bourne_system(req)
    if req.centre == "custom_rpm" and not req.centre_rpm:
        raise ValueError("centre = 'custom_rpm' needs centre_rpm.")
    pm, _info = plan.resolve_center_pm(sys, req.centre, req.centre_pm_W_kg, req.centre_rpm or 0.0)
    t1_rows = plan.test1_conditions(sys, pm)
    results = {1: kpi_assessment(req.test1, 1),
               2: kpi_assessment(req.test2, 2) if req.test2 else None,
               3: kpi_assessment(req.test3, 3) if req.test3 else None}
    status = [results[n]["status"] if results[n] else "" for n in (1, 2, 3)]
    outcome = rules.bourne_outcome(*status, plan.pm_range_ratio([r["P/m (W/kg)"] for r in t1_rows]))
    feed_time = (req.feed_volume_mL / req.feed_rate_mL_min if req.feed_basis == FeedBasis.RATE
                 else req.feed_time_min)
    ratios = plan.t3_location_ratios(req.surface_ratio, req.mid_ratio, req.impeller_ratio)
    return {
        "system": sys, "pm_center": pm, "t1_rows": t1_rows, "results": results,
        "outcome": outcome, "conclusions": rules.bourne_conclusions(outcome, results),
        "centerpoint": plan.centerpoint_metrics(sys, pm),
        "t2": ((plan.t2_report_conditions(sys, pm, req.feed_volume_mL, feed_time), results[2])
               if results[2] else None),
        "t3": ((plan.t3_report_conditions(sys, pm, ratios, feed_time), results[3])
               if results[3] else None),
    }


# ---------------------------------------------------------------------------
# Heat Transfer
# ---------------------------------------------------------------------------
LINING_OPTIONS = ["None", *LINING_CONDUCTIVITY]


def heat_transfer_inputs(req: s.HeatTransferRequest) -> tuple[dict, dict, pd.Series, dict]:
    """(``compute_batch`` / ``compute_reaction_profile`` input dict, HTM database, reactor row,
    resolved {wall_material, lining_material}) with the Heat Transfer page's defaults."""
    row = _reactor(req.reactor)
    _reactors, _fluids, htm_db = load_csvs(DATA_DIR)
    htm = req.htm or next(iter(htm_db))
    if htm not in htm_db:
        raise LookupError(f"Unknown heat-transfer medium '{htm}'.")
    nu_corr = req.nusselt_correlation or next(iter(NUSSELT_CORRELATIONS))
    if nu_corr not in NUSSELT_CORRELATIONS:
        raise LookupError(f"Unknown Nusselt correlation '{nu_corr}'.")
    wall = req.wall_material or find_best_material_key(
        str(row.get("shell_material", "stainless steel")), list(WALL_CONDUCTIVITY))
    if wall not in WALL_CONDUCTIVITY:
        raise LookupError(f"Unknown wall material '{wall}'.")
    if req.lining_material is None:
        raw = row.get("lining_material", "")
        lining = find_best_material_key(str(raw).strip() if pd.notna(raw) else "", LINING_OPTIONS)
    else:
        lining = req.lining_material
    if lining not in LINING_OPTIONS:
        raise LookupError(f"Unknown lining material '{lining}'.")

    d_tank = req.D_tank_m or sf(row.get("D_tank_m"), 0.1)
    v_l = req.V_L or range_midpoint(row, "V_L_min", "V_L_max", sf(row.get("V_L"), 1.0))
    props = thermal_props(req.fluid, req.T_start_C)
    data = {
        "rho": props["rho"], "mu": props["mu"], "cp": props["cp"], "k_fluid": props["k"],
        "d_tank": d_tank, "d_imp": req.D_imp_m or sf(row.get("D_imp_m"), 0.05),
        "n_rpm": req.N_rpm or range_midpoint(row, "N_rpm_min", "N_rpm_max", 300.0),
        "np_in": req.Np or sf(row.get("Np"), 1.27), "v_l": v_l,
        "mu_wall": req.mu_wall_Pa_s, "nusselt_correlation": nu_corr, "htm_name": htm,
        "v_jacket": req.v_jacket_m_s, "d_hyd_jacket": req.d_hyd_jacket_m,
        "m_dot_jacket": req.m_dot_jacket_kg_s,
        "cp_jacket": sf(htm_db[htm].get("Cp_J_kgK"), 3500.0),
        "include_agitator": req.include_agitator,
        "wall_k": WALL_CONDUCTIVITY.get(wall, 16.0),
        "wall_thickness_mm": req.wall_thickness_mm or sf(row.get("wall_thickness_mm"), 5.0),
        "lining_k": 0.0 if lining == "None" else LINING_CONDUCTIVITY.get(lining, 0.0),
        "lining_thickness_mm": (0.0 if lining == "None"
                                else LINING_THICKNESS_DEFAULT.get(lining, 0.002) * 1000.0),
        "fouling": req.fouling_m2K_W,
        "a_ht": req.A_ht_m2 or reactor_jacket_area(row, d_tank, v_l),
        "t_start": req.T_start_C, "t_jacket": req.T_jacket_C,
    }
    return data, htm_db, row, {"wall_material": wall, "lining_material": lining}


def heat_cool_inputs(req: s.HeatCoolRequest) -> tuple[dict, dict, pd.Series, dict]:
    error = heat_cool_setup_error(req.T_start_C, req.T_target_C, req.T_jacket_C)
    if error:
        raise ValueError(error)
    data, htm_db, row, labels = heat_transfer_inputs(req)
    data.update({"t_target": req.T_target_C, "q_rxn": req.q_rxn_W})
    return data, htm_db, row, labels


def reaction_profile_inputs(req: s.ReactionProfileRequest) -> tuple[dict, dict, pd.Series, dict]:
    rx = req.reaction
    if rx.k <= 0 or rx.C0_mol_L <= 0:
        raise ValueError("Reaction needs a rate constant k > 0 and C0 > 0.")
    data, htm_db, row, labels = heat_transfer_inputs(req)
    data.update({"rxn_order": rx.order, "rxn_k": rx.k, "rxn_c0": rx.C0_mol_L,
                 "rxn_dH": rx.dH_kJ_mol})
    return data, htm_db, row, labels
