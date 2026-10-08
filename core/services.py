"""Request -> result functions over the core calculations (future HTTP handler bodies).

Raise ``LookupError`` for unknown database names and ``ValueError`` for inputs
the calculations cannot use (map to HTTP 404 / 422).
"""
from __future__ import annotations

from dataclasses import replace

import numpy as np
import pandas as pd

from core import batch_temperature as bt
from core import bourne_io
from core import bourne_plan as plan
from core import catalog, envelope, fluids, kinetics, scale_up, tables, units
from core import operating_point as op
from core import repositories as repos
from core import schemas as s
from core import sensitivity_rules as rules
from core.auth import ANONYMOUS
from core.messages import Message
from core.options import (
    BourneStatus, CenterMode, Coalescence, Competing, CorrSource, DhAction, DhBasis, FeedBasis,
    FeedLocation, GasTransfer, Kinetics, Mechanism, Phase,
)
from core.records import (
    DATA_DIR, VesselGeometry, bottom_dish_height, fluid_props, fluid_row, range_midpoint,
    reaction_row, reactor_row, sf, solvent_props, thermal_props,
)
from core.serialize import jsonable
from core.heat_transfer import (
    FOULING_DEFAULT, LINING_CONDUCTIVITY, LINING_THICKNESS_DEFAULT, NUSSELT_CORRELATIONS,
    SWEEP_PARAMETERS, SWEEP_ZERO_VALUE_MAX, WALL_CONDUCTIVITY,
    compute_batch, compute_reaction_profile, find_best_material_key, heat_cool_setup_error,
    jacket_side_htc, load_csvs, reactor_jacket_area, resistance_breakdown, resistance_items, surface_color_limits,
    sweep_range_defaults, u_ua_surface, ua_sweep_series,
)
from utils import bourne_kpi
from core.catalog import available_modes, available_modes_multi


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
    if rx is None:
        reaction, t_rxn = op.Reaction("1", 0.0, 0.0, 0.0, 0.0, present=False), 0.0
    else:
        t_rxn = kinetics.effective_t_rxn(rx.order, rx.k, rx.C0_mol_L, rx.t_rxn_s)
        reaction = op.Reaction(rx.order, rx.k, rx.C0_mol_L, t_rxn, rx.dH_kJ_mol)
    sol = req.solids
    inp = op.PointInputs(
        reactor=req.reactor, geometry=geometry,
        fluid=op.Fluid(f.name, f.rho_kg_m3 or props["rho"], f.mu_Pa_s or props["mu"],
                       f.D_mol_m2_s or props["D_mol"]),
        reaction=reaction,
        corr_mode=req.corr_source,
        gas=op.Gas(req.gas.v_s_m_s, req.gas.coalescing),
        solids=(op.Solids(rho_p=sol.rho_p_kg_m3, d50_um=sol.d50_um, phi=sol.sphericity,
                          x_wt=sol.loading_g_per_100g, S_zw=sol.zwietering_S,
                          gmb_z=sol.gmb_z, cd=sol.clearance_ratio) if sol else None),
        feed=_feed(req) if req.feed else None,
        heat=_heat(req.heat) if heat and req.heat else None,
    )
    return inp, t_rxn, row


def _heat(h: s.HeatSpec) -> op.Heat:
    """Process / coolant temperatures and, with an HTF, its jacket-side h_o (as on the Heat
    Transfer page: Dittus-Boelter / laminar Nu at the jacket velocity and hydraulic diameter)."""
    if not h.htm:
        return op.Heat(h.T_process_C, h.T_coolant_C)
    _reactors, _fluids, htm_db = load_csvs(DATA_DIR)
    if h.htm not in htm_db:
        raise LookupError(f"Unknown heat-transfer medium '{h.htm}'.")
    entry = htm_db[h.htm]
    lo, hi = sf(entry.get("T_min_C")), sf(entry.get("T_max_C"))
    note = (f"Coolant temperature {h.T_coolant_C:g} °C is outside the {h.htm} range "
            f"({lo:g} to {hi:g} °C)." if (lo or hi) and not lo <= h.T_coolant_C <= hi else "")
    return op.Heat(h.T_process_C, h.T_coolant_C, htm=h.htm,
                   h_jacket=jacket_side_htc(entry, h.v_jacket_m_s, h.d_hyd_jacket_m), htm_note=note)


def _feed(req: s.PointRequest) -> op.Feed:
    """Feed inputs; with a rate and temperature, the feed's sensible heat
    m·Cp·(T_feed − T_process) (W) enters the heat balance."""
    fd = req.feed
    q = 0.0
    if fd.rate_mL_min and fd.T_C is not None:
        t_process = req.heat.T_process_C if req.heat else req.fluid.T_C
        tp = thermal_props(fd.fluid or req.fluid.name, fd.T_C)
        m_dot = fd.rate_mL_min * 1e-6 / 60.0 * tp["rho"]
        q = m_dot * tp["cp"] * (fd.T_C - t_process)
    return op.Feed(fd.location, fd.d_pipe_mm / 1000.0, sensible_W=q)


def require_kinetics(req: s.PointRequest, t_rxn: float) -> None:
    """A selected reaction needs a usable t_rxn; "no reaction" (``reaction=None``) is allowed."""
    if req.reaction is not None and t_rxn <= 0:
        raise ValueError("Provide a reaction time or rate constant (> 0) to compute "
                         "Damköhler numbers, or select no reaction.")


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
    require_kinetics(req, t_rxn)
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


def envelope_parameters() -> list[s.ParameterOption]:
    return [s.ParameterOption(field=s.CORE_KEYS[k], label=k,
                              default=k in envelope.DEFAULT_ENVELOPE)
            for k in envelope.ENVELOPE_PARAMETERS]


def correlation_status(reactor: str) -> tuple[list[CorrSource], str]:
    """(correlation sources registered for the vessel, explanatory status line)."""
    modes = [CorrSource(m) for m in available_modes(reactor)]
    if len(modes) > 1:
        return modes, "Available sources for this vessel: " + ", ".join(m.label for m in modes) + "."
    return modes, ("Only empirical (literature) correlations are registered for this vessel. "
                   "Experimental and reduced-order (CFD) sources become available once fitted "
                   "via ROM Fitting.")


def vessel_defaults(reactor: str) -> s.VesselDefaults:
    """The Vessel Assessment inputs a vessel loads when selected."""
    row = _reactor(reactor)
    modes, status = correlation_status(reactor)
    n_rpm = range_midpoint(row, "N_rpm_min", "N_rpm_max", 300.0)
    v_l = range_midpoint(row, "V_L_min", "V_L_max", sf(row.get("V_L"), 1.0))
    n_arr, v_min, v_max = envelope.operating_window(row, n_rpm, v_l, n_pts=2)
    return s.VesselDefaults(
        reactor=reactor, D_tank_m=sf(row.get("D_tank_m"), 0.1), D_imp_m=sf(row.get("D_imp_m"), 0.05),
        N_rpm=n_rpm, V_L=v_l,
        Np=sf(row.get("Np"), 1.27), Nq=sf(row.get("Nq"), 0.79),
        corr_sources=[s.OptionItem(code=m.value, label=m.label) for m in modes],
        corr_status=status, N_rpm_range=(float(n_arr[0]), float(n_arr[-1])),
        V_L_range=(float(v_min), float(v_max)))


# (PointResult field, group) plotted against dosing time; series without data are dropped.
FILLING_SERIES = [
    ("Re", "hydrodynamics"), ("P_V_W_L", "hydrodynamics"), ("P_V_W_kg", "hydrodynamics"),
    ("froude", "hydrodynamics"), ("blend_time_95_s", "hydrodynamics"),
    ("circulation_time_s", "hydrodynamics"), ("t_E_s", "hydrodynamics"),
    ("kolmogorov_um", "hydrodynamics"), ("avg_shear_rate_1_s", "hydrodynamics"),
    ("max_shear_rate_1_s", "hydrodynamics"),
    ("kLa_1_s", "mass_transfer"), ("kLa_surface_1_s", "mass_transfer"),
    ("N_over_N_js", "mass_transfer"), ("kLa_SL_1_s", "mass_transfer"),
    ("Da_macro", "damkohler"), ("Da_micro", "damkohler"), ("Da_meso", "damkohler"),
    ("Da_GL", "damkohler"), ("Da_SL", "damkohler"),
    ("U_W_m2K", "heat"), ("A_ht_m2", "heat"), ("Q_gen_W", "heat"), ("Q_feed_W", "heat"),
    ("Q_load_W", "heat"), ("Q_cool_W", "heat"), ("Q_gen_over_Q_cool_pct", "heat"),
]


def _liquid(name: str, T_C: float, P_atm: float, custom: pd.DataFrame) -> dict | None:
    """Mixing-rule properties of a library solvent or custom fluid (None when unknown)."""
    resolved = (catalog.resolve_solvent_name(name) or name) if catalog.is_known_solvent(name) else name
    props = fluids.component_props(resolved, custom, T_C)
    if props is not None and catalog.is_known_solvent(resolved):
        p = fluid_props(resolved, T_C, P_atm)  # pressure-corrected where the library supports it
        props.update(rho_kg_m3=p["rho"], mu_Pa_s=p["mu"], D_mol_m2_s=p["D_mol"],
                     surface_tension_N_m=p["sigma"])
    return props


def _blend_path(p: s.PointRequest, inp: op.PointInputs, feed_fluid: str, volumes
                ) -> tuple[list[tuple[float, dict, op.PointInputs]], pd.DataFrame]:
    """(fill volume, blended liquid, point inputs with the blend) at each volume - the initial
    fluid volume-blended with the dosed fluid - and the custom-fluid table."""
    custom = repos.fluids.load()
    f = p.fluid
    base = _liquid(f.name, f.T_C, f.P_atm, custom)
    if base is None:
        pr = fluid_props(f.name, f.T_C, f.P_atm)
        base = {"rho_kg_m3": pr["rho"], "mu_Pa_s": pr["mu"], "D_mol_m2_s": pr["D_mol"],
                "surface_tension_N_m": pr["sigma"], "Cp_J_per_kgK": 4182.0, "k_W_per_mK": 0.607}
    base.update(rho_kg_m3=inp.fluid.rho, mu_Pa_s=inp.fluid.mu, D_mol_m2_s=inp.fluid.D_mol)
    feed = _liquid(feed_fluid, f.T_C, f.P_atm, custom)
    if feed is None:
        raise LookupError(f"Unknown dosed fluid '{feed_fluid}'.")
    path = []
    for v in volumes:
        mix = fluids.volume_blend([(base, p.V_L), (feed, v - p.V_L)])
        path.append((v, mix, replace(inp, fluid=replace(
            inp.fluid, rho=mix["rho_kg_m3"], mu=mix["mu_Pa_s"], D_mol=mix["D_mol_m2_s"]))))
    return path, custom


def filling(req: s.FillingRequest) -> s.FillingResult:
    """Operating point along a fed-batch fill: volume rises linearly from ``point.V_L`` by
    ``dosing_amount_L`` over ``dosing_time_h``; the liquid is a volume blend of the initial
    fluid and the dosed fluid at every step."""
    p = req.point
    inp, t_rxn, row = point_inputs(p)
    f = p.fluid
    v0, dose, n = p.V_L, req.dosing_amount_L, req.n_steps
    times = np.linspace(0.0, req.dosing_time_h * 60.0, n + 1)
    volumes = v0 + dose * times / times[-1]
    path, custom = _blend_path(p, inp, req.feed_fluid, volumes)

    warnings = []
    v_end = v0 + dose
    v_max = sf(row.get("V_L_max"))
    if v_max > 0 and v_end > v_max:
        warnings.append(f"The final fill volume ({v_end:.4g} L) exceeds the vessel maximum "
                        f"({v_max:.4g} L); results beyond it are extrapolated.")
    if req.feed_fluid != f.name:
        m = fluids.solvent_miscibility(f.name, req.feed_fluid, custom_fluids=custom)
        if m.get("reactive"):
            warnings.append(f"{f.name} and {req.feed_fluid} react on mixing - blended properties "
                            "do not apply.")
        elif m["miscible"] is False:
            warnings.append(f"{f.name} and {req.feed_fluid} are immiscible / partially miscible - "
                            "averaged properties may not apply.")
        elif m["miscible"] is None:
            warnings.append(f"Miscibility of {f.name} and {req.feed_fluid} is unknown (no HSP "
                            "data); properties assume a single-phase blend.")

    fields = [(fld, grp) for fld, grp in FILLING_SERIES
              if not (grp == "damkohler" and t_rxn <= 0)]
    fluid_keys = [("V_L", "Fill volume (L)"), ("H_m", "Liquid height (m)"),
                  ("rho_kg_m3", "Density ρ (kg/m³)"), ("mu_Pa_s", "Viscosity μ (Pa·s)"),
                  ("nu_mm2_s", "Kinematic viscosity ν (mm²/s)"),
                  ("surface_tension_N_m", "Surface tension σ (N/m)"),
                  ("D_mol_m2_s", "Diffusivity D (m²/s)")]
    fluid_cols = {k: [] for k, _ in fluid_keys}
    point_cols = {fld: [] for fld, _ in fields}
    ua_col = []
    for v, mix, step in path:
        fluid_cols["V_L"].append(v)
        fluid_cols["H_m"].append(inp.geometry.liquid_height(v))
        for k in ("rho_kg_m3", "mu_Pa_s", "surface_tension_N_m", "D_mol_m2_s"):
            fluid_cols[k].append(mix[k])
        fluid_cols["nu_mm2_s"].append(mix["mu_Pa_s"] / mix["rho_kg_m3"] * 1e6)
        res = point_result(op.evaluate_point(step, p.N_rpm / 60.0, v))
        for fld, _ in fields:
            point_cols[fld].append(getattr(res, fld))
        if p.heat is not None:
            u_val, area = op.jacket_ua(step, p.N_rpm / 60.0, v)
            ua_col.append(u_val * area)

    def present(values: list) -> bool:
        return any(x is not None and np.isfinite(x) and x != 0 for x in values)

    series = [s.FillingSeries(field=k, label=label, group="fluid", values=jsonable(fluid_cols[k]))
              for k, label in fluid_keys]
    for fld, grp in fields:
        if fld == "Q_gen_W" and present(ua_col):
            series.append(s.FillingSeries(field="UA_W_K", label="UA (W/K)", group="heat",
                                          values=jsonable(ua_col)))
        if present(point_cols[fld]):
            series.append(s.FillingSeries(field=fld, label=s.core_key(fld), group=grp,
                                          values=jsonable(point_cols[fld])))
    return s.FillingResult(time_min=jsonable(times), V_L=jsonable(volumes), V_end_L=v_end,
                           feed_rate_mL_min=dose * 1000.0 / (req.dosing_time_h * 60.0),
                           series=series, warnings=warnings)


def temperature(req: s.TemperatureRequest) -> s.TemperatureResult:
    """Batch temperature against time (core.batch_temperature): the batch scenario without
    dosing, else the dosed scenario over the dosing time with UA(t) along the fill."""
    p = req.point
    if p.heat is None:
        raise ValueError("Set the process and coolant temperatures to simulate the batch "
                         "temperature.")
    inp, t_rxn, _row = point_inputs(p)
    require_kinetics(p, t_rxn)
    rx = p.reaction
    kin = (bt.Kinetics(rx.order, rx.k, rx.C0_mol_L, rx.dH_kJ_mol) if rx is not None
           else bt.Kinetics("1", 0.0, 0.0, 0.0))
    T0, n_rps = p.heat.T_process_C, p.N_rpm / 60.0
    cp0 = thermal_props(p.fluid.name, T0)["cp"]
    dosing, T_f = None, None
    if p.feed is not None and req.dosing_time_h and req.dosing_amount_L:
        feed_fluid = p.feed.fluid or p.fluid.name
        T_f = p.feed.T_C if p.feed.T_C is not None else T0
        tpf = thermal_props(feed_fluid, T_f)
        t_dose = req.dosing_time_h * 3600.0
        times = np.linspace(0.0, t_dose, 26)
        path, _custom = _blend_path(p, inp, feed_fluid,
                                    p.V_L + req.dosing_amount_L * times / t_dose)
        ua_grid = [float(np.prod(op.jacket_ua(step, n_rps, v))) for v, _mix, step in path]
        dosing = bt.Dosing(t_dose, req.dosing_amount_L, tpf["rho"], tpf["cp"], T_f)

        def ua(t: float) -> float:
            return float(np.interp(t, times, ua_grid))
    else:
        if not kin.active:
            raise ValueError("Nothing to simulate: select a reaction, or a fed-batch dosing "
                             "(time, amount and temperature).")
        ua_const = float(np.prod(op.jacket_ua(inp, n_rps, p.V_L)))

        def ua(t: float) -> float:
            return ua_const
    res = bt.profile(T0=T0, T_cool=p.heat.T_coolant_C, V0_L=p.V_L, rho0=inp.fluid.rho, cp0=cp0,
                     kin=kin, ua=ua, dosing=dosing)
    return s.TemperatureResult.model_validate(
        {k: jsonable(v) for k, v in res.items()} | {"T_coolant_C": p.heat.T_coolant_C,
                                                    "T_feed_C": T_f})


def fluid_properties(name: str, T_C: float = 25.0, P_atm: float = 1.0) -> s.FluidProperties:
    """Liquid properties at (T, P) for a library solvent (aliases resolved) or custom fluid."""
    known = catalog.is_known_solvent(name)
    resolved = (catalog.resolve_solvent_name(name) or name) if known else name
    p = fluid_props(resolved, T_C, P_atm)
    return s.FluidProperties(
        name=resolved, found=known or not fluid_row(resolved).empty, library=known,
        T_C=T_C, P_atm=P_atm,
        rho_kg_m3=p["rho"], mu_Pa_s=p["mu"], D_mol_m2_s=p["D_mol"], surface_tension_N_m=p["sigma"],
        in_range=bool(p["in_range"]), note=p["note"])


# Recorded Results column -> evaluate_point key, for a saved assessment.
_RECORDED_HYDRO = {
    "Re": "Re", "P/V (W/L)": "P/V (W/L)", "Tip speed (m/s)": "Tip speed (m/s)",
    "Blend time (s)": "Blend time 95% (s)", "Circulation time (s)": "Circulation time (s)",
    "Micromix t_E (s)": "Micromix time t_E (s)",
    "Micromix t_E_local (s)": "Micromix time t_E_local (s)",
    "Kolmogorov η (µm)": "Kolmogorov η (µm)", "EDCF (W/kg/s)": "EDCF (W/kg/s)",
    "Torque (N·m)": "Torque (N·m)", "Froude number": "Froude number",
    "Avg shear rate (1/s)": "Avg shear rate (1/s)", "Max shear rate (1/s)": "Max shear rate (1/s)",
    "Avg shear stress (Pa)": "Avg shear stress (Pa)", "kLa (1/s)": "kLa (1/s)",
    "kLa_surface (1/s)": "kLa_surface (1/s)",
    "Da_macro": "Da_macro", "Da_micro": "Da_micro", "Da_GL": "Da_GL", "Da_SL": "Da_SL",
    "Assessment": "Assessment",
}


def recorded_result_row(hydro: dict, *, reactor: str, reaction: str, fluid: str, T_C: float,
                        N_rpm: float, V_L: float, t_rxn: float) -> dict:
    """One Recorded Results row for an assessed operating point."""
    return {"reactor": reactor, "reaction": reaction, "fluid": fluid, "fluid_T_C": T_C,
            "RPM": N_rpm, "Volume (L)": V_L, "t_rxn (s)": t_rxn,
            **{col: hydro.get(key, "") for col, key in _RECORDED_HYDRO.items()}}


def save_assessment(req: s.AssessmentReportRequest) -> int:
    """Evaluate the point and append it to Recorded Results; returns the record count."""
    p = req.point
    inp, t_rxn, _row = point_inputs(p)
    require_kinetics(p, t_rxn)
    hydro = op.evaluate_point(inp, p.N_rpm / 60.0, p.V_L)
    row = recorded_result_row(hydro, reactor=p.reactor, reaction=req.reaction_name,
                              fluid=p.fluid.name, T_C=p.fluid.T_C, N_rpm=p.N_rpm, V_L=p.V_L,
                              t_rxn=t_rxn)
    return repos.results.append([row], ANONYMOUS)


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


def screening_damkohler_out(da: dict | None) -> s.ScreeningDamkohler | None:
    if not da:
        return None
    return s.ScreeningDamkohler(
        reactor=da["reactor"], N_rpm=da["N_rpm"], V_L=da["V_L"], fluid=da["fluid"],
        t_blend_s=jsonable(da["t_blend"]), t_E_s=jsonable(da["t_E"]), Re=jsonable(da["Re"]),
        P_V_W_L=jsonable(da["P_V_W_L"]), Da_macro=jsonable(da["Da_macro"]),
        Da_micro=jsonable(da["Da_micro"]))


def assess(req: s.ProtocolRequest) -> s.ProtocolResult:
    res = run_protocol(req)
    kin = res["kinetics"]
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
        damkohler=screening_damkohler_out(res["da"]),
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


def comparison_setup(req: s.ComparisonSetupRequest) -> s.ComparisonSetup:
    """Inputs the Vessel Comparison page loads for a vessel selection."""
    names = list(req.reactors)
    for name in names:
        _reactor(name)
    modes = [CorrSource(m) for m in available_modes_multi(names)]
    status = ("Sources available for every selected vessel: "
              + ", ".join(m.label for m in modes) + "." if len(modes) > 1 else
              "Only empirical (literature) correlations are shared by all selected vessels. "
              "Experimental and reduced-order (CFD) sources appear once fitted for every "
              "vessel in the selection.")
    basis = req.basis_reactor if req.basis_reactor in names else names[0]
    rpm, vol = scale_up.basis_defaults(basis)
    return s.ComparisonSetup(
        corr_sources=[s.OptionItem(code=m.value, label=m.label) for m in modes],
        corr_status=status, feed_pipe_mm=scale_up.feed_pipe_defaults(names),
        basis_reactor=basis, basis_N_rpm=rpm, basis_V_L=vol,
        fixed=scale_up.target_defaults(names, basis, req.solve_for == "N_rpm"),
        scalable=[s.ParameterOption(field=s.CORE_KEYS[k], label=k)
                  for k in scale_up.SCALABLE_PARAMS])


def sensitivity_options() -> s.SensitivityOptions:
    return s.SensitivityOptions(
        reaction_orders=list(kinetics.ORDER_OPTIONS),
        dh_references={n: sf(reaction_row(n).get("delta_H_kJ_mol"))
                       for n in catalog.reactions_with_enthalpy()},
        unit_operations=UNIT_OPERATIONS)


def sensitivity_reaction_defaults(reaction: str, T_C: float | None = None
                                  ) -> s.SensitivityReactionDefaults:
    """Database kinetics of a reaction plus its solvent's ρ·Cp (page auto-fill)."""
    row = reaction_row(reaction)
    if row.empty:
        raise LookupError(f"Unknown reaction '{reaction}'.")
    kd = kinetics.kinetics_defaults(reaction)
    solvent = str(row.get("solvent", "") or "")
    p = solvent_props(solvent, kd["T"] if T_C is None else T_C)
    return s.SensitivityReactionDefaults(
        order=kd["order"], k=kd["k"], C0_mol_L=kd["C0"], t_rxn_s=kd["t_rxn"], T_C=kd["T"],
        dH_kJ_mol=kd["dH"], reaction_type=str(row.get("type", "") or ""), solvent=solvent,
        rho_cp_kJ_m3K=round(p["rho_kg_m3"] * p["Cp_J_per_kgK"] / 1000.0, 1) if p else None)


def bourne_import(raw: bytes) -> s.BourneImport:
    """Parse a Bourne Protocol results export (the Sensitivity CSV)."""
    try:
        df = tables.read_upload_csv(raw, dtype=str, keep_default_na=False)
    except Exception as exc:  # noqa: BLE001 - any parse failure is a bad upload
        raise ValueError(f"Could not read the file: {exc}") from None
    imp = bourne_io.parse(df)
    return s.BourneImport(
        status=imp["status"], mechanism=imp["mechanism"] or None, tests_done=imp["tests_done"],
        findings=[s.BourneTestRow(**r) for r in imp["findings"]], meta=imp["meta"],
        meta_caption=imp["meta_caption"], fields=imp["fields"])


def kinetics_defaults(reaction: str) -> s.KineticsDefaults:
    """Database kinetics for a reaction, plus its solvent when that is a known fluid."""
    if reaction_row(reaction).empty:
        raise LookupError(f"Unknown reaction '{reaction}'.")
    kd = kinetics.kinetics_defaults(reaction)
    resolved = catalog.resolve_solvent_name(kd["solvent"]) if kd["solvent"] else None
    return s.KineticsDefaults(
        order=kd["order"], k=kd["k"], C0_mol_L=kd["C0"], t_rxn_s=kd["t_rxn"], T_C=kd["T"],
        dH_kJ_mol=kd["dH"],
        fluid=resolved if resolved and resolved in catalog.fluid_names_grouped() else None)


def save_comparison(req: s.ComparisonRequest) -> tuple[int, int]:
    """Append each vessel's max-RPM / max-volume corner to Recorded Results: (saved, total)."""
    cmp = compare(req)
    rows = scale_up.recorded_rows(cmp["env_df"], reaction=req.reaction_name,
                                  fluid=req.fluid.name, T_C=req.fluid.T_C, t_rxn=cmp["t_rxn"])
    if not rows:
        raise ValueError("Nothing to save.")
    return len(rows), repos.results.append(rows, ANONYMOUS)


def comparison_summary(req: s.ComparisonRequest) -> s.ComparisonResult:
    """Tables of the Vessel Comparison page (corner points, ranges, heat, impact ratios)."""
    cmp = compare(req)
    env_df, present = cmp["env_df"], cmp["present"]
    return s.ComparisonResult(
        parameters=present, corners=jsonable(env_df), ranges=jsonable(cmp["agg_df"]),
        heat=(jsonable(scale_up.heat_summary_data(env_df, cmp["reactor_info"]))
              if cmp["incl_heat"] else []),
        impact_ratios=jsonable(scale_up.impact_ratio_data(env_df, present, cmp["incl_heat"])),
        skipped=list(cmp["skipped"]))


# ---------------------------------------------------------------------------
# Bourne Protocol
# ---------------------------------------------------------------------------
def bourne_reactor(name: str) -> pd.Series:
    return _reactor(name)


def bourne_options() -> s.BourneOptions:
    return s.BourneOptions(
        kpi_columns={str(n): list(cols) for n, cols in bourne_kpi.KPI_COLUMNS.items()},
        response_metrics=list(bourne_kpi.RESPONSE_METRICS), units=list(bourne_kpi.KPI_UNITS),
        unit_operations=UNIT_OPERATIONS)


def bourne_system(req: s.BournePlanRequest) -> plan.BourneSystem:
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


def centre_pm(req: s.BournePlanRequest, sys: plan.BourneSystem) -> tuple[float, str]:
    """(Test 1 centre-point P/m in W/kg, Markdown caption of how it was chosen)."""
    if req.centre == "custom_rpm" and not req.centre_rpm:
        raise ValueError("centre = 'custom_rpm' needs centre_rpm.")
    return plan.resolve_center_pm(sys, req.centre, req.centre_pm_W_kg, req.centre_rpm or 0.0)


def bourne_speed_plan(req: s.BournePlanRequest) -> dict | None:
    """Raw ``plan.t1_speed_plan`` (iso-P/m speed lines over the fill range); None without one."""
    sys = bourne_system(req)
    row = _reactor(req.reactor)
    return plan.t1_speed_plan(sys, centre_pm(req, sys)[0], sf(row.get("V_L_min"), 0.0),
                              sf(row.get("V_L_max"), sf(row.get("V_L"), sys.V_L)),
                              req.fed_batch_volumes_L)


def bourne_plan(req: s.BournePlanRequest) -> s.BournePlanResult:
    """Test 1-3 operating conditions (before any KPI is measured)."""
    sys = bourne_system(req)
    pm, info = centre_pm(req, sys)
    t1 = plan.test1_conditions(sys, pm)
    steps = [("Initial", sys.V_L)] + [(f"Adj. {i + 1}", v) for i, v in
                                      enumerate(req.fed_batch_volumes_L) if v > 0]
    setpoints, _ = plan.speed_setpoints(sys, pm, steps)
    ratios = plan.t3_location_ratios(req.surface_ratio, req.mid_ratio, req.impeller_ratio)
    return s.BournePlanResult(
        centre_pm_W_kg=pm, centre_info=info, centerpoint=jsonable(plan.centerpoint_metrics(sys, pm)),
        test1=jsonable(t1), test1_pm_span=plan.pm_range_ratio([r["P/m (W/kg)"] for r in t1]),
        speed_plan=jsonable(bourne_speed_plan(req)),
        setpoints=[s.SpeedSetpoint(
            step=sp["Step"], V_L=sp["Volume (L)"], low_rpm=sp["Low (RPM)"][0],
            centre_rpm=sp["Centre (RPM)"][0], high_rpm=sp["High (RPM)"][0],
            clamped=[c for c in ("low", "centre", "high")
                     if sp[f"{c.capitalize()} (RPM)"][1]]) for sp in setpoints],
        test2=jsonable(plan.test2_conditions(req.feed_volume_mL, req.feed_basis == FeedBasis.RATE,
                                             req.feed_rate_mL_min, req.feed_time_min)),
        test3=jsonable(plan.test3_conditions(sys, pm, ratios)))


def bourne_assess(req: s.BourneAssessRequest) -> s.BourneAssessResult:
    """Per-test KPI verdicts and the decision-tree outcome."""
    ev = bourne_evaluation(req)
    ratio = ev["outcome"]["ratio"]
    tests = []
    for n, res in ev["results"].items():
        if res is None:
            continue
        verdict, run_next = rules.bourne_test_verdict(n, res, ratio)
        tests.append(s.BourneTestOut(
            test=n, status=res["status"], verdict=verdict, run_next_test=run_next,
            kpis=jsonable(res["table"]),
            kpi_details=[s.BourneKpiDetail(
                name=r["name"], unit=r["unit"], low=r["low"], centre=r["ctr"], high=r["high"],
                max_change_pct=r["max_pct"], threshold_pct=r["threshold"],
                sensitive=r["sensitive"], noise_limited=r["noise_limited"],
                critical=r["criticality"] == "critical") for r in res["results"]]))
    o = ev["outcome"]
    return s.BourneAssessResult(tests=tests, dominant=o["dominant"], tentative=o["tentative"],
                                next_test=o["next_test"], summary=rules.bourne_summary_md(o),
                                test_lines=[ln.removeprefix("- ") for ln in rules.bourne_test_lines(o)],
                                conclusion="\n".join(rules.bourne_conclusion_lines(o)),
                                pm_span=jsonable(ratio))


def bourne_evaluation(req: s.BourneAssessRequest) -> dict:
    """Test conditions, KPI verdicts and decision-tree outcome for the Bourne report."""
    sys = bourne_system(req)
    pm, _info = centre_pm(req, sys)
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
    lining_k = 0.0 if lining == "None" else LINING_CONDUCTIVITY.get(lining, 0.0)
    lining_mm = 0.0 if lining == "None" else LINING_THICKNESS_DEFAULT.get(lining, 0.002) * 1000.0

    def pick(override, default):
        return default if override is None else override

    data = {
        "rho": pick(req.rho_kg_m3, props["rho"]), "mu": pick(req.mu_Pa_s, props["mu"]),
        "cp": pick(req.cp_J_kgK, props["cp"]), "k_fluid": pick(req.k_W_mK, props["k"]),
        "d_tank": d_tank, "d_imp": req.D_imp_m or sf(row.get("D_imp_m"), 0.05),
        "n_rpm": req.N_rpm or range_midpoint(row, "N_rpm_min", "N_rpm_max", 300.0),
        "np_in": req.Np or sf(row.get("Np"), 1.27), "v_l": v_l,
        "mu_wall": req.mu_wall_Pa_s, "nusselt_correlation": nu_corr, "htm_name": htm,
        "v_jacket": req.v_jacket_m_s, "d_hyd_jacket": req.d_hyd_jacket_m,
        "m_dot_jacket": req.m_dot_jacket_kg_s,
        "cp_jacket": pick(req.cp_jacket_J_kgK, sf(htm_db[htm].get("Cp_J_kgK"), 3500.0)),
        "include_agitator": req.include_agitator,
        "wall_k": pick(req.wall_k_W_mK, WALL_CONDUCTIVITY.get(wall, 16.0)),
        "wall_thickness_mm": req.wall_thickness_mm or sf(row.get("wall_thickness_mm"), 5.0),
        "lining_k": pick(req.lining_k_W_mK, lining_k),
        "lining_thickness_mm": pick(req.lining_thickness_mm, lining_mm),
        "fouling": req.fouling_m2K_W,
        "a_ht": req.A_ht_m2 or reactor_jacket_area(row, d_tank, v_l),
        "t_start": req.T_start_C, "t_jacket": req.T_jacket_C,
    }
    return data, htm_db, row, {"wall_material": wall, "lining_material": lining}


UNIT_OPERATIONS = ["Reaction", "Quench", "Crystallization", "Liquid-Liquid Extraction",
                   "Distillation", "Filtration", "Drying", "Other"]


def heat_transfer_options() -> s.HeatTransferOptions:
    _reactors, _fluids, htm_db = load_csvs(DATA_DIR)
    return s.HeatTransferOptions(
        media={name: sf(entry.get("Cp_J_kgK"), 3500.0) for name, entry in htm_db.items()},
        nusselt_correlations=list(NUSSELT_CORRELATIONS), wall_materials=dict(WALL_CONDUCTIVITY),
        linings={name: (LINING_CONDUCTIVITY[name], LINING_THICKNESS_DEFAULT.get(name, 0.002) * 1000.0)
                 for name in LINING_CONDUCTIVITY},
        sweep_parameters=[s.ParameterOption(field=key, label=label)
                          for label, key in SWEEP_PARAMETERS.items()],
        sweep_zero_max=dict(SWEEP_ZERO_VALUE_MAX), unit_operations=UNIT_OPERATIONS,
        fouling_default=FOULING_DEFAULT)


def heat_transfer_defaults(reactor: str) -> s.HeatTransferDefaults:
    """Vessel geometry, operating point and materials the Heat Transfer page loads."""
    data, _htm_db, row, labels = heat_transfer_inputs(
        s.HeatTransferRequest(reactor=reactor, T_jacket_C=0.0))

    def rng(lo_key: str, hi_key: str):
        lo, hi = sf(row.get(lo_key)), sf(row.get(hi_key))
        return (lo, hi) if hi > lo >= 0 else None

    return s.HeatTransferDefaults(
        D_tank_m=data["d_tank"], D_imp_m=data["d_imp"], N_rpm=data["n_rpm"], Np=data["np_in"],
        V_L=data["v_l"], A_ht_m2=data["a_ht"], wall_material=labels["wall_material"],
        wall_k_W_mK=data["wall_k"], wall_thickness_mm=data["wall_thickness_mm"],
        lining_material=labels["lining_material"], lining_k_W_mK=data["lining_k"],
        lining_thickness_mm=data["lining_thickness_mm"],
        N_rpm_range=rng("N_rpm_min", "N_rpm_max"), V_L_range=rng("V_L_min", "V_L_max"))


def jacket_area(reactor: str, D_tank_m: float, V_L: float) -> float:
    return reactor_jacket_area(_reactor(reactor), D_tank_m, V_L)


def thermal_properties(name: str, T_C: float) -> s.ThermalProperties:
    p = thermal_props(name, T_C)
    return s.ThermalProperties(rho_kg_m3=p["rho"], mu_Pa_s=p["mu"], cp_J_kgK=p["cp"], k_W_mK=p["k"])


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


def _resolved(data: dict, labels: dict) -> s.HeatTransferResolved:
    return s.HeatTransferResolved(
        N_rpm=data["n_rpm"], V_L=data["v_l"], D_tank_m=data["d_tank"], D_imp_m=data["d_imp"],
        A_ht_m2=data["a_ht"], htm=data["htm_name"],
        nusselt_correlation=data["nusselt_correlation"], **labels)


def _coefficients(r, a_ht: float) -> s.Coefficients:
    return s.Coefficients(
        Re=jsonable(r.re), Pr=jsonable(r.pr), Nu=jsonable(r.nu), h_i_W_m2K=jsonable(r.h_i),
        h_o_W_m2K=jsonable(r.h_o), U_W_m2K=jsonable(r.u), A_ht_m2=jsonable(a_ht),
        UA_W_K=jsonable(r.u * a_ht), agitator_power_W=jsonable(r.p_agitator_w))


def heat_cool(req: s.HeatCoolRequest) -> s.HeatCoolResult:
    """Batch heat-up / cool-down: coefficients, temperature profiles, comparisons, UA sweeps."""
    data, htm_db, row, labels = heat_cool_inputs(req)
    r = compute_batch(data, htm_db)
    items = resistance_items(r.h_i, r.h_o, data["wall_k"], data["wall_thickness_mm"],
                             data["lining_k"], data["lining_thickness_mm"], data["fouling"])
    ua = ua_sweep_series(data, htm_db, row, data["a_ht"])
    return s.HeatCoolResult(
        resolved=_resolved(data, labels), coefficients=_coefficients(r, data["a_ht"]),
        q_max_W=jsonable(r.q_max_w), dT_dt_C_per_min=jsonable(r.dt_dt_c_per_min),
        time_analytical_s=jsonable(r.time_analytical_s),
        time_constant_jacket_s=jsonable(r.time_const_jacket_s),
        time_variable_jacket_s=jsonable(r.time_variable_jacket_s),
        constant_jacket={"t_s": jsonable(r.t_const), "T_C": jsonable(r.T_const),
                         "q_W": jsonable(r.q_const)},
        variable_jacket={"t_s": jsonable(r.t_var), "T_C": jsonable(r.T_var),
                         "q_W": jsonable(r.q_var), "T_jacket_out_C": jsonable(r.Tj_out)},
        correlations=jsonable(r.corr_comparison), media=jsonable(r.htm_comparison),
        summary=jsonable(r.summary),
        resistances=[s.Resistance(name=n, R_m2K_W=jsonable(rv), share_pct=jsonable(p))
                     for n, rv, p in resistance_breakdown(items)],
        ua_vs_speed={"N_rpm": jsonable(ua["rpm"]), "UA_W_K": jsonable(ua["ua_rpm"])},
        ua_vs_volume={"V_L": jsonable(ua["volume"]), "UA_W_K": jsonable(ua["ua_volume"])})


def reaction_profile(req: s.ReactionProfileRequest) -> s.ReactionProfileResult:
    """Batch temperature driven by an exo-/endothermic reaction against the jacket."""
    data, htm_db, _row, labels = reaction_profile_inputs(req)
    r = compute_reaction_profile(data, htm_db)
    return s.ReactionProfileResult(
        resolved=_resolved(data, labels), coefficients=_coefficients(r, data["a_ht"]),
        profile={"t_s": jsonable(r.t), "T_C": jsonable(r.T), "conversion": jsonable(r.conversion),
                 "q_rxn_W": jsonable(r.q_rxn), "q_jacket_W": jsonable(r.q_jacket)},
        T_peak_C=jsonable(r.T_peak_c), t_peak_s=jsonable(r.t_peak_s),
        T_adiabatic_C=jsonable(r.T_adiabatic_c), t_complete_s=jsonable(r.t_complete_s),
        q_rxn_max_W=jsonable(r.q_rxn_max_w), final_conversion=jsonable(r.final_conversion),
        summary=jsonable(r.summary))


def ua_surface(req: s.UaSurfaceRequest) -> s.UaSurfaceResult:
    """U and UA over a grid of two swept heat-transfer inputs."""
    data, htm_db, row, _labels = heat_transfer_inputs(req)
    ranges = []
    for key, rng in ((req.x_parameter, req.x_range), (req.y_parameter, req.y_range)):
        ranges.append(rng or sweep_range_defaults(row, key, data[key]))
    x = np.linspace(*ranges[0], req.n_points)
    y = np.linspace(*ranges[1], req.n_points)
    u, ua = u_ua_surface(
        data, htm_db, req.x_parameter, x, req.y_parameter, y, data["a_ht"],
        h_max=sf(row.get("H_max_m"), sf(row.get("H_m"), 0.2)),
        bottom_dish=str(row.get("bottom_dish", "")), dish_height=bottom_dish_height(row))
    return s.UaSurfaceResult(
        x_parameter=req.x_parameter, y_parameter=req.y_parameter, x=jsonable(x), y=jsonable(y),
        U_W_m2K=jsonable(u), UA_W_K=jsonable(ua), U_limits=jsonable(surface_color_limits(u)),
        UA_limits=jsonable(surface_color_limits(ua)))


# ---------------------------------------------------------------------------
# Scale-up matching (Vessel Comparison)
# ---------------------------------------------------------------------------
def scale_up_match(req: s.ScaleUpRequest) -> s.ScaleUpResult:
    """Operating point on every compared vessel that reproduces the basis vessel's parameter."""
    names = list(req.comparison.reactors)
    if req.basis_reactor not in names:
        raise ValueError("basis_reactor must be one of comparison.reactors.")
    ctx = comparison_context(req.comparison)
    cmp = scale_up.compare_vessels(names, ctx, n_interp=2)
    solve_rpm = req.solve_for == "N_rpm"
    fixed = {}
    for name in names:
        row = _reactor(name)
        default = (range_midpoint(row, "V_L_min", "V_L_max", sf(row.get("V_L"), 0.0)) if solve_rpm
                   else range_midpoint(row, "N_rpm_min", "N_rpm_max", 0.0))
        fixed[name] = req.fixed.get(name, default)
    key = s.core_key(req.parameter)
    match = scale_up.scale_up_match(names, cmp["reactor_info"], cmp["inputs"], req.basis_reactor,
                                    key, req.basis_N_rpm, req.basis_V_L, solve_rpm=solve_rpm,
                                    known=fixed)
    if match is None:
        raise ValueError(f"'{req.basis_reactor}' has no usable geometry and speed range.")
    rows = []
    for res, full in zip(match["results"], match["full"]):
        hydro = {s.CORE_KEYS.get(k, k): jsonable(v) for k, v in full.items()
                 if k not in ("Reactor", "Role", "RPM")}
        rows.append(s.ScaleUpRow(
            reactor=res["Reactor"], role=res["Role"].lower(), N_rpm=jsonable(res["RPM"]),
            V_L=jsonable(res["Volume (L)"]), value=jsonable(res[key]), status=res["Status"],
            hydro=hydro))
    return s.ScaleUpResult(parameter=req.parameter, target=jsonable(match["target"]), rows=rows)


# ---------------------------------------------------------------------------
# Fluids
# ---------------------------------------------------------------------------
def solvent_state(req: s.SolventStateRequest) -> dict:
    return jsonable(fluids.solvent_state(req.name, req.P_atm, req.T_C))


def blend(req: s.BlendRequest) -> s.BlendResult:
    amounts = {c.name: c.amount for c in req.components}
    res = fluids.blend(amounts, req.basis == "volume", req.T_C, repos.fluids.load(),
                       req.dispersion_speed_1_s, req.dispersion_D_imp_m, req.dispersion_H_m,
                       req.interfacial_tension_N_m)
    phases = res["phases"]
    return s.BlendResult(
        status=res["status"],
        components=[jsonable({k: v for k, v in cp.items() if k != "input"})
                    for cp in res["components"]],
        blend=jsonable(res["blend"]),
        pairs=[s.BlendPair(label=p["label"], a=p["a"], b=p["b"], classification=p["class"],
                           assessment=str(p["misc"]["assessment"]),
                           Ra_MPa05=jsonable(p["misc"].get("Ra")), source=str(p["misc"]["source"]))
               for p in res["pairs"]],
        phases=jsonable(phases[0]) if phases else None,
        phases_unknown_split=bool(phases[1]) if phases else False,
        dispersion=jsonable(res["dispersion"]))


# ---------------------------------------------------------------------------
# Units
# ---------------------------------------------------------------------------
def convert_units(req: s.UnitConversionRequest) -> s.UnitConversionResult:
    converted = units.convert(req.property, req.from_unit, req.value, req.gas_T_C, req.gas_P_atm)
    return s.UnitConversionResult(property=req.property, from_unit=req.from_unit, value=req.value,
                                  converted=jsonable(converted))


# ---------------------------------------------------------------------------
# Option lists
# ---------------------------------------------------------------------------
OPTION_ENUMS = {e.__name__: e for e in (
    CorrSource, FeedLocation, GasTransfer, Coalescence, CenterMode, FeedBasis, Mechanism,
    BourneStatus, Kinetics, Phase, Competing, DhAction, DhBasis)}


def options() -> s.OptionsResult:
    return s.OptionsResult(
        reactors=catalog.reactor_names(), reactions_measured=catalog.reaction_names("no"),
        reaction_classes=catalog.reaction_names("yes"), fluids=catalog.fluid_names(),
        particles=catalog.particle_names(),
        enums={name: [s.OptionItem(code=m.value, label=m.label) for m in enum]
               for name, enum in OPTION_ENUMS.items()})
