"""Tests for the hydrodynamics engine: power-number regimes, unit contracts
and key parity between the literature and ROM/experimental compute paths."""

import math
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.calculations import (
    compute_reactor_hydro,
    kla_vant_riet,
    power_number_correlation,
    zwietering_njs,
)
from utils import rom_registry


# --- Power number -------------------------------------------------------------
def test_power_number_laminar_asymptote_is_KL_over_Re():
    assert power_number_correlation(1.0) == pytest.approx(70.0)
    assert power_number_correlation(10.0) == pytest.approx(7.0)
    assert power_number_correlation(2.0, K_L=50.0) == pytest.approx(25.0)


def test_power_number_turbulent_plateau():
    assert power_number_correlation(1e4) == 5.0
    assert power_number_correlation(1e6, Np_turb=1.27) == 1.27


def test_power_number_transition_is_monotonic_and_continuous():
    values = [power_number_correlation(re) for re in (10, 30, 100, 300, 1000, 3000, 1e4)]
    assert all(a >= b for a, b in zip(values, values[1:]))
    assert values[0] == pytest.approx(7.0)
    assert values[-1] == pytest.approx(5.0)
    # Exactly at the boundaries both branches agree.
    assert power_number_correlation(10.0 - 1e-9) == pytest.approx(power_number_correlation(10.0 + 1e-9), rel=1e-6)


def test_power_number_degenerate_reynolds_falls_back_to_turbulent():
    assert power_number_correlation(0.0) == 5.0
    assert power_number_correlation(float("nan")) == 5.0


def test_laminar_case_draws_more_power_than_turbulent_plateau():
    """A viscous fluid with no Np in the DB must not silently use Np = 5."""
    # N = 1 rps, D = 0.05 m, rho = 1000, mu = 1 Pa.s -> Re = 2.5
    h = compute_reactor_hydro(N=1.0, D_imp=0.05, D_tank=0.1, H=0.1,
                              rho=1000.0, mu=1.0, Np=None, Nq=None)
    assert h["Re"] == pytest.approx(2.5)
    assert h["Np"] == pytest.approx(70.0 / 2.5)
    assert h["Power (W)"] > 5.0 * 1000.0 * 1.0 * 0.05**5


# --- Unit contracts ---------------------------------------------------------------
def test_kla_vant_riet_uses_W_per_m3():
    # 1000 W/m^3, 0.01 m/s, coalescing: 0.026 * 1000^0.4 * 0.1
    assert kla_vant_riet(1000.0, 0.01) == pytest.approx(0.026 * 1000 ** 0.4 * 0.1)
    assert kla_vant_riet(1000.0, 0.01, coalescing=False) == pytest.approx(0.002 * 1000 ** 0.7 * 0.01 ** 0.2)
    assert kla_vant_riet(0.0, 0.01) == 0.0
    assert kla_vant_riet(1000.0, 0.0) == 0.0


def test_zwietering_uses_weight_percent():
    base = dict(S=5.5, nu=1e-6, d_p=50e-6, delta_rho=500.0, rho_L=1000.0, D_imp=0.05)
    n_10pct = zwietering_njs(X_wt_pct=10.0, **base)
    n_1pct = zwietering_njs(X_wt_pct=1.0, **base)
    assert n_10pct / n_1pct == pytest.approx(10 ** 0.13)
    assert zwietering_njs(X_wt_pct=0.0, **base) == 0.0


# --- Literature vs ROM dict parity ------------------------------------------------
def test_mode_paths_return_identical_key_sets(monkeypatch):
    kwargs = dict(N=5.0, D_imp=0.05, D_tank=0.1, H=0.1, rho=1000.0, mu=1e-3,
                  Np=5.0, Nq=0.79, v_s=0.0, coalescing=True, D_mol=2.3e-9)
    lit = compute_reactor_hydro(**kwargs)
    reactor = "__test_reactor__"
    monkeypatch.setitem(rom_registry._REGISTRY, reactor, [rom_registry.Correlation(
        name="test t_E", param="micromixing_time", corr_type="ROM",
        func=lambda **kw: 12.5 * (kw["nu"] / kw["eps_kg"]) ** 0.48, latex="", source="test")])
    modes = rom_registry.available_modes(reactor)
    alt = [m for m in modes if m != "Literature"]
    assert alt == ["ROM"]
    rom, sources = rom_registry.compute_reactor_hydro_with_mode(alt[0], reactor, **kwargs)
    assert set(rom) == set(lit)
    assert sources, "an overridden parameter should be reported as a source"
    # Non-overridden derived quantities must agree between paths.
    for key in ("Volume (L)", "Re", "Tip speed (m/s)", "Froude number", "ν (m²/s)"):
        assert rom[key] == pytest.approx(lit[key])
    assert all(math.isfinite(v) for v in rom.values())
