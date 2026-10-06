"""Unit tests for core.operating_point — pins the VA/VC unification decisions."""

import os
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import operating_point as op
from core.options import FeedLocation
from core.records import VesselGeometry
from utils.calculations import gmb_njs, zwietering_njs

GEO = VesselGeometry(D_tank=0.3, D_imp=0.1, H_max=0.4, Np=1.27, Nq=0.79)
WATER = op.Fluid("Water", 997.0, 0.00089, 2.3e-9)
RXN = op.Reaction("1", 0.01, 1.0, 100.0, dH=-100.0)
SOLIDS = op.Solids(rho_p=1500.0, d50_um=100.0, phi=1.0, x_wt=5.0)


def _inp(**kw) -> op.PointInputs:
    base = dict(reactor="test-vessel", geometry=GEO, fluid=WATER, reaction=RXN)
    base.update(kw)
    return op.PointInputs(**base)


def test_default_geometry_power_number_is_1_27():
    assert VesselGeometry.from_row(pd.Series(dtype=object)).Np == 1.27


def test_njs_is_max_of_zwietering_and_gmb():
    s = op.solids_static(SOLIDS, WATER, GEO)
    nu = WATER.mu / WATER.rho
    drho = SOLIDS.rho_p - WATER.rho
    zw = zwietering_njs(SOLIDS.S_zw, nu, 1e-4, drho, WATER.rho, SOLIDS.x_wt, GEO.D_imp)
    gmb = gmb_njs(SOLIDS.gmb_z, GEO.Np, GEO.D_imp, 1e-4, drho, WATER.rho,
                  s["phi_s"] * 100.0, SOLIDS.cd)
    assert s["njs_rps"] == pytest.approx(max(zw, gmb))


def test_solids_fraction_is_on_a_slurry_basis():
    assert op.solids_volume_fraction(5.0, 1000.0, 2000.0) == pytest.approx(0.025 / 1.025)


def test_k_sl_uses_settling_velocity_so_is_speed_independent():
    inp = _inp(solids=SOLIDS)
    slow, fast = op.evaluate_point(inp, 1.0, 10.0), op.evaluate_point(inp, 8.0, 10.0)
    assert slow["k_SL (m/s)"] == pytest.approx(fast["k_SL (m/s)"])
    assert slow["N/N_js"] < fast["N/N_js"]


def test_signed_driving_force_gives_no_cooling_from_a_warmer_coolant():
    cooled = op.evaluate_point(_inp(heat=op.Heat(25.0, 15.0)), 3.0, 10.0)
    warm = op.evaluate_point(_inp(heat=op.Heat(25.0, 35.0)), 3.0, 10.0)
    assert cooled["Q_cool (W)"] > 0
    assert warm["Q_cool (W)"] == 0.0
    assert warm["Q_gen/Q_cool (%)"] == np.inf


def test_surface_kla_feeds_da_gl_without_a_gas_phase():
    pt = op.evaluate_point(_inp(), 3.0, 10.0)
    assert pt["kLa_surface (1/s)"] > 0
    assert pt["Da_GL"] > 0


def test_near_impeller_feed_falls_back_to_mean_dissipation():
    assert op.feed_dissipation({"P/V (W/kg)": 2.0}, FeedLocation.NEAR_IMPELLER) == 2.0
    assert op.feed_dissipation({"P/V (W/kg)": 2.0, "ε_max (W/kg)": 9.0},
                               FeedLocation.NEAR_IMPELLER) == 9.0
    assert op.feed_dissipation({"P/V (W/kg)": 2.0}, FeedLocation.SURFACE) == pytest.approx(0.4)


def test_optional_blocks_only_appear_when_requested():
    bare = op.evaluate_point(_inp(), 3.0, 10.0)
    assert "Da_meso" not in bare and "Q_gen (W)" not in bare and "N_js (RPM)" not in bare
    full = op.evaluate_point(
        _inp(solids=SOLIDS, feed=op.Feed(FeedLocation.BULK, 0.003), heat=op.Heat(25.0, 15.0)),
        3.0, 10.0)
    assert {"Da_meso", "Q_gen (W)", "N_js (RPM)", "Da_SL"} <= set(full)
