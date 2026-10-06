"""Single operating-point evaluation shared by the vessel pages.

``evaluate_point`` returns the hydrodynamic dictionary plus Damköhler numbers and,
when the matching options are supplied, solid suspension / mass transfer,
mesomixing (fed-batch) and jacket heat-balance values. All result keys match the
labels the pages display, so callers can index the dict directly.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache

import numpy as np

from core.options import CorrSource, FeedLocation
from core.records import VesselGeometry, reactor_row, sf, solvent_props
from utils.calculations import (
    compute_damkohler_numbers,
    compute_reactor_hydro,
    estimate_U_detailed,
    estimate_jacket_area,
    gmb_njs,
    heat_generation_rate,
    heat_removal_capacity,
    mesomixing_time,
    particle_reynolds,
    reaction_rate_mol_per_s,
    settling_velocity,
    solid_liquid_kla,
    solid_liquid_mass_transfer,
    zwietering_njs,
)
from utils.rom_registry import compute_reactor_hydro_with_mode
from utils.solvent_properties import resolve_solvent_name

# Display label -> correlation-registry mode key.
CORR_SOURCES = {m.label: m.value for m in CorrSource}
CORR_LABELS = {v: k for k, v in CORR_SOURCES.items()}


@dataclass(frozen=True)
class Fluid:
    name: str
    rho: float
    mu: float
    D_mol: float


@dataclass(frozen=True)
class Reaction:
    order: str
    k: float
    C0: float
    t_rxn: float
    dH: float = 0.0  # kJ/mol


@dataclass(frozen=True)
class Gas:
    v_s: float = 0.0
    coalescing: bool = True


@dataclass(frozen=True)
class Solids:
    rho_p: float
    d50_um: float
    phi: float = 1.0
    x_wt: float = 5.0
    S_zw: float = 5.5
    gmb_z: float = 3.0
    cd: float = 0.33


@dataclass(frozen=True)
class Feed:
    location: FeedLocation
    d_pipe_m: float


@dataclass(frozen=True)
class Heat:
    T_process: float
    T_coolant: float


@dataclass(frozen=True)
class PointInputs:
    reactor: str
    geometry: VesselGeometry
    fluid: Fluid
    reaction: Reaction
    corr_mode: CorrSource = CorrSource.LITERATURE
    gas: Gas = field(default_factory=Gas)
    solids: Solids | None = None
    feed: Feed | None = None
    heat: Heat | None = None


def solids_volume_fraction(x_wt: float, rho: float, rho_p: float) -> float:
    """Solids volume fraction of the slurry (V_p / (V_p + V_L)).

    ``x_wt`` follows the Zwietering convention: g solid per 100 g liquid.
    """
    if rho_p <= 0:
        return 0.0
    r = max(x_wt, 0.0) / 100.0 * rho / rho_p
    return r / (1.0 + r)


@lru_cache(maxsize=256)
def solids_static(solids: Solids, fluid: Fluid, geometry: VesselGeometry) -> dict:
    """Speed-independent particle quantities (N_js, settling, k_SL, kLa_SL)."""
    d_p = solids.d50_um * 1e-6
    rho, mu = fluid.rho, fluid.mu
    nu = mu / rho if rho > 0 else 0.0
    drho = abs(solids.rho_p - rho)
    v_t = settling_velocity(d_p, solids.rho_p, rho, mu, solids.phi)
    phi_s = solids_volume_fraction(solids.x_wt, rho, solids.rho_p)
    njs_zw = zwietering_njs(solids.S_zw, nu, d_p, drho, rho, solids.x_wt, geometry.D_imp)
    # GMB defines X_v as a volume percentage (particles / slurry, %).
    njs_gmb = gmb_njs(solids.gmb_z, geometry.Np, geometry.D_imp, d_p, drho, rho,
                      phi_s * 100.0, solids.cd)
    k_sl = solid_liquid_mass_transfer(d_p, v_t, rho, mu, fluid.D_mol)
    return {
        "njs_rps": max(njs_zw, njs_gmb), "njs_zw_rps": njs_zw, "njs_gmb_rps": njs_gmb,
        "v_t": v_t, "Re_p": particle_reynolds(d_p, v_t, rho, mu), "phi_s": phi_s,
        "k_SL": k_sl, "kLa_SL": solid_liquid_kla(k_sl, d_p, phi_s),
    }


def hydro(inp: PointInputs, N_rps: float, V_L: float) -> dict:
    """Hydrodynamic dictionary at (N, V) for the selected correlation source."""
    g = inp.geometry
    h, _sources = compute_reactor_hydro_with_mode(
        inp.corr_mode, inp.reactor, N=N_rps, D_imp=g.D_imp, D_tank=g.D_tank,
        H=g.liquid_height(V_L), rho=inp.fluid.rho, mu=inp.fluid.mu, Np=g.Np, Nq=g.Nq,
        v_s=inp.gas.v_s, coalescing=inp.gas.coalescing, D_mol=inp.fluid.D_mol)
    return h


def feed_dissipation(h: dict, location: FeedLocation) -> float:
    """Local energy dissipation (W/kg) at the feed point."""
    pv = h.get("P/V (W/kg)", 0.0)
    if location == FeedLocation.NEAR_IMPELLER:
        return h.get("ε_max (W/kg)", pv)
    if location == FeedLocation.SURFACE:
        return 0.2 * pv
    return pv


def evaluate_point(inp: PointInputs, N_rps: float, V_L: float) -> dict:
    """Hydro + Damköhler (+ solids, mesomixing, heat balance) at one (N, V) point."""
    h = hydro(inp, N_rps, V_L)
    out = dict(h)
    t_rxn = inp.reaction.t_rxn

    kla_sl = 0.0
    if inp.solids is not None and inp.solids.d50_um > 0:
        s = solids_static(inp.solids, inp.fluid, inp.geometry)
        kla_sl = s["kLa_SL"]
        out.update({
            "N_js (RPM)": s["njs_rps"] * 60.0,
            "N/N_js": N_rps / s["njs_rps"] if s["njs_rps"] > 0 else 0.0,
            "v_t (m/s)": s["v_t"], "Re_p": s["Re_p"],
            "k_SL (m/s)": s["k_SL"], "kLa_SL (1/s)": kla_sl,
        })

    out.update(compute_damkohler_numbers(
        h["Blend time 95% (s)"], h["Micromix time t_E (s)"], t_rxn,
        kLa=h.get("kLa (1/s)", 0.0), kLa_surface=h.get("kLa_surface (1/s)", 0.0),
        kLa_SL=kla_sl))

    if inp.feed is not None:
        t_meso = mesomixing_time(feed_dissipation(h, inp.feed.location), inp.feed.d_pipe_m)
        out["Da_meso"] = t_meso / t_rxn if t_rxn > 0 and np.isfinite(t_meso) else 0.0

    if inp.heat is not None and inp.reaction.dH != 0.0:
        g, rx = inp.geometry, inp.reaction
        q_gen = heat_generation_rate(rx.dH, reaction_rate_mol_per_s(rx.order, rx.k, rx.C0, V_L))
        area = estimate_jacket_area(g.D_tank, g.liquid_height(V_L), g.bottom_dish,
                                    g.bottom_dish_height)
        u_val, _warn = estimate_U_detailed(
            N_rps=N_rps, D_imp=g.D_imp, D_tank=g.D_tank, rho=inp.fluid.rho, mu=inp.fluid.mu,
            material=g.shell_material, lining_material=g.lining_material,
            wall_thickness_mm=g.wall_thickness_mm, fluid_name=inp.fluid.name)
        # Signed driving force: a coolant warmer than the batch provides no cooling.
        q_cool = heat_removal_capacity(u_val, area, inp.heat.T_process - inp.heat.T_coolant)
        out.update({
            "Q_gen (W)": q_gen, "Q_cool (W)": q_cool, "U (W/m²·K)": u_val, "A_ht (m²)": area,
            "Q_gen/Q_cool (%)": q_gen / q_cool * 100.0 if q_cool > 0 else np.inf,
        })
    return out


def screening_damkohler(reactor: str, n_rpm: float, v_l: float, solvent: str, T_C: float,
                        t_rxn: float) -> dict | None:
    """Da_macro / Da_micro for a vessel at (N, V) with literature correlations and the
    reaction solvent (water when unknown). None when the vessel geometry is incomplete."""
    row = reactor_row(reactor)
    d_tank, d_imp = sf(row.get("D_tank_m")), sf(row.get("D_imp_m"))
    if row.empty or d_tank <= 0 or d_imp <= 0 or n_rpm <= 0 or v_l <= 0:
        return None
    props = solvent_props(solvent, T_C) or solvent_props("Water", T_C)
    rho = props["rho_kg_m3"] if props else 1000.0
    mu = props["mu_Pa_s"] if props else 1e-3
    h_liq = VesselGeometry.from_row(row, H_max_fallback=d_tank).liquid_height(v_l)
    h = compute_reactor_hydro(N=n_rpm / 60.0, D_imp=d_imp, D_tank=d_tank, H=h_liq,
                              rho=rho, mu=mu, Np=sf(row.get("Np")) or None,
                              Nq=sf(row.get("Nq")) or None)
    t_blend, t_e = h["Blend time 95% (s)"], h["Micromix time t_E (s)"]
    return {
        "reactor": reactor, "N_rpm": n_rpm, "V_L": v_l,
        "fluid": (resolve_solvent_name(solvent) or solvent) if props and solvent else "Water",
        "t_blend": t_blend, "t_E": t_e, "Re": h["Re"], "P_V_W_L": h["P/V (W/L)"],
        "Da_macro": t_blend / t_rxn if t_rxn > 0 else 0.0,
        "Da_micro": t_e / t_rxn if t_rxn > 0 else 0.0,
    }
