"""Unit tests for core.envelope root finding and operating windows."""

import os
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.envelope import find_roots, operating_window, solve_root


def test_solve_root_bisects_to_tolerance():
    root = solve_root(lambda x: x**2 - 2.0, 0.0, 2.0, x_tol=1e-10)
    assert root == pytest.approx(np.sqrt(2.0), rel=1e-9)


def test_solve_root_returns_none_without_sign_change_or_on_nan():
    assert solve_root(lambda x: x**2 + 1.0, -1.0, 1.0, x_tol=1e-6) is None
    assert solve_root(lambda x: np.nan, 0.0, 1.0, x_tol=1e-6) is None


def test_find_roots_reports_every_crossing_once():
    roots, xs, ys = find_roots(lambda x: np.sin(x), 0.5, 10.0, n_pts=60)
    assert roots == pytest.approx([np.pi, 2 * np.pi, 3 * np.pi], rel=1e-9)
    assert len(xs) == len(ys) == 60


def test_find_roots_does_not_duplicate_a_grid_point_root():
    roots, _, _ = find_roots(lambda x: x - 5.0, 0.0, 10.0, n_pts=11)
    assert roots == [5.0]


def test_operating_window_uses_db_range_or_falls_back_around_operating_point():
    n_arr, v_min, v_max = operating_window(
        pd.Series({"N_rpm_min": 100, "N_rpm_max": 500, "V_L_min": 2, "V_L_max": 10}), 300, 5)
    assert (n_arr[0], n_arr[-1], v_min, v_max) == (100, 500, 2, 10)
    n_arr, v_min, v_max = operating_window(pd.Series(dtype=object), 300, 4)
    assert (n_arr[0], n_arr[-1]) == pytest.approx((30.0, 300.0))
    assert (v_min, v_max) == pytest.approx((2.0, 4.0))
