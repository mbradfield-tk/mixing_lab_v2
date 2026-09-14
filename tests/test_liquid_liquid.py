"""Regression tests for liquid-liquid dispersion calculations."""

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.calculations.liquid_liquid import (
    dispersion_screen,
    liquid_liquid_capacity_ratio,
    minimum_dispersion_speed,
    n_min_van_heuven_beek,
    phase_separation_check,
    sauter_drop_diameter,
    weber_number,
)


def test_weber_and_drop_size_have_expected_trends():
    low_we = weber_number(1000.0, 2.0, 0.05, 0.01)
    high_we = weber_number(1000.0, 4.0, 0.05, 0.01)
    assert high_we > low_we
    assert sauter_drop_diameter(high_we, 0.05) < sauter_drop_diameter(low_we, 0.05)


def test_phase_separation_reports_drag_corrected_drop_state():
    result = phase_separation_check(
        N=5.0, D_imp=0.05, D_tank=1.0,
        rho_c=1000.0, rho_d=900.0, mu_c=0.001,
        sigma_LL=0.01, phi_d=0.2)
    assert result["d32 (m)"] > 0
    assert result["Drop settling velocity (m/s)"] > 0
    assert result["Drop Reynolds number"] >= 0
    assert math.isfinite(result["Separation time (s)"])


def test_capacity_ratio_and_minimum_speed_validate_inputs():
    assert liquid_liquid_capacity_ratio(0.5, 10.0) == 5.0
    assert liquid_liquid_capacity_ratio(0.0, 10.0) == 0.0
    assert minimum_dispersion_speed(0.05, 0.01, 1000.0, 0.2) > 0
    assert minimum_dispersion_speed(float("nan"), 0.01, 1000.0, 0.2) == 0.0


def test_consolidated_screen_and_van_heuven_beek_are_usable():
    result = dispersion_screen(
        N=5.0, D_imp=0.05, D_tank=1.0,
        rho_c=1000.0, rho_d=900.0, mu_c=0.001,
        sigma_LL=0.01, phi_d=0.2, D_mol=2.3e-9, epsilon_kg=1.0)
    assert result["N_min (1/s)"] > 0
    assert result["kLa (1/s)"] > 0
    assert n_min_van_heuven_beek(0.05, 0.2, 1000.0, 900.0, 0.001, 0.01) > 0
