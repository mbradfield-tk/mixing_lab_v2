"""Regression tests for Heat Transfer table CSV exports."""

import os
import sys
from types import SimpleNamespace

import pandas as pd
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pages import heat_transfer
from pages.heat_transfer import _build_csv_exports


def test_heat_transfer_csv_exports_match_current_tables():
    state = SimpleNamespace(
        rxn_summary_df=pd.DataFrame({"Metric": ["Peak temperature"]}),
        kpi_df=pd.DataFrame({"Metric": ["U (W/m2.K)"]}),
        corr_df=pd.DataFrame({"Correlation": ["Dittus-Boelter"]}),
        htm_compare_df=pd.DataFrame({"Medium": ["Water"]}),
        summary_df=pd.DataFrame({"Metric": ["Time to target"]}),
    )

    _build_csv_exports(state)

    assert b"Peak temperature" in state.rxn_summary_csv
    assert b"U (W/m2.K)" in state.kpi_csv
    assert b"Dittus-Boelter" in state.corr_csv
    assert b"Water" in state.htm_compare_csv
    assert b"Time to target" in state.summary_csv


def test_parameter_sweep_uses_reactor_ranges_and_builds_u_ua_surfaces(monkeypatch):
    monkeypatch.setattr(heat_transfer, "notify", lambda *_args: None)
    state = SimpleNamespace(
        selected_reactor="TMA EasyMax-102",
        sweep_x_parameter="Stir speed (rpm)",
        sweep_y_parameter="Liquid volume (L)",
        sweep_x_min=0.0,
        sweep_x_max=1.0,
        sweep_y_min=0.0,
        sweep_y_max=1.0,
        sweep_color_theme="Cool/Warm",
        sweep_color_range_mode="Custom",
        sweep_u_color_min=120.0,
        sweep_u_color_max=180.0,
        sweep_ua_color_min=0.2,
        sweep_ua_color_max=2.0,
        rho=997.0,
        mu=0.00089,
        cp=4182.0,
        k_fluid=0.6,
        d_tank=0.05,
        d_imp=0.03,
        n_rpm=300.0,
        np_in=1.27,
        v_l=0.05,
        mu_wall=0.0,
        nusselt_correlation=heat_transfer.nusselt_options[0],
        selected_htm=heat_transfer.htm_options[0],
        v_jacket=1.0,
        d_hyd_jacket=0.05,
        m_dot_jacket=1.0,
        cp_jacket=3500.0,
        include_agitator=True,
        wall_k=16.0,
        wall_thickness_mm=5.0,
        lining_k=0.0,
        lining_thickness_mm=0.0,
        fouling=heat_transfer.FOULING_DEFAULT,
        a_ht=0.01,
    )

    heat_transfer._refresh_sweep_ranges(state)
    assert (state.sweep_x_min, state.sweep_x_max) == (50.0, 1000.0)
    assert (state.sweep_y_min, state.sweep_y_max) == (0.01, 0.1)

    heat_transfer._compute_parameter_sweep(state)

    u_surface = np.asarray(state.sweep_u_fig.data[0].z)
    ua_surface = np.asarray(state.sweep_ua_fig.data[0].z)
    assert state.sweep_result_ready
    assert u_surface.shape == (30, 30)
    assert ua_surface.shape == (30, 30)
    assert not np.isclose(u_surface[0, 0], u_surface[0, -1])
    assert not np.isclose(ua_surface[0, 0], ua_surface[-1, 0])
    assert state.sweep_u_fig.data[0].cmin == 120.0
    assert state.sweep_u_fig.data[0].cmax == 180.0
    assert state.sweep_ua_fig.data[0].cmin == 0.2
    assert state.sweep_ua_fig.data[0].cmax == 2.0
    assert [list(stop) for stop in state.sweep_u_fig.data[0].colorscale] == heat_transfer._sweep_colorscale("Cool/Warm")

    state.sweep_x_parameter = "Tank diameter (m)"
    heat_transfer._refresh_sweep_ranges(state)
    heat_transfer._compute_parameter_sweep(state)
    ua_diameter_surface = np.asarray(state.sweep_ua_fig.data[0].z)
    assert not np.isclose(ua_diameter_surface[15, 0], ua_diameter_surface[15, -1])

    state.sweep_color_range_mode = "Automatic"
    heat_transfer._compute_parameter_sweep(state)
    auto_limits = heat_transfer._surface_color_limits(np.asarray(state.sweep_u_fig.data[0].z))
    assert np.allclose((state.sweep_u_fig.data[0].cmin, state.sweep_u_fig.data[0].cmax), auto_limits)
