"""Unit tests for core modules extracted from the database, vessel and heat-transfer pages."""

import os
import sys

import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import scale_up, vessel_import as vi
from core import sensitivity_rules as rules
from core.miscibility import settled_phases
from core.records import VesselGeometry
from heat_transfer_core import heat_cool_setup_error, sweep_range_defaults


# --- vessel import ---------------------------------------------------------------
def test_missing_reactor_ids_continue_the_rx_sequence():
    df = pd.DataFrame({"reactor_id": ["RX-004", "", None], "reactor_name": ["a", "b", "c"]})
    out, n = vi.assign_missing_reactor_ids(df)
    assert n == 2 and list(out["reactor_id"]) == ["RX-004", "RX-005", "RX-006"]


def test_import_diff_matches_by_id_then_name_and_blanks_never_wipe():
    existing = pd.DataFrame({"reactor_id": ["RX-001", "RX-002"],
                             "reactor_name": ["Alpha", "Beta"], "V_L_max": [10.0, 20.0]})
    upload = pd.DataFrame({"reactor_id": ["rx-001", "", ""],
                           "reactor_name": ["Alpha renamed", "Beta", "Gamma"],
                           "V_L_max": [10.0, None, 5.0]})
    changes = vi.build_import_changes(existing, upload)
    kinds = [(c["kind"], c.get("col"), c["reactor_name"]) for c in changes]
    assert kinds == [("update", "reactor_name", "Alpha"), ("add", None, "Gamma")]


def test_apply_import_change_updates_and_adds_rows():
    df = pd.DataFrame({"reactor_id": ["RX-001"], "reactor_name": ["Alpha"], "V_L_max": [10.0]})
    up = {"kind": "update", "match_by": ("reactor_id", "rx-001"), "col": "V_L_max", "new": "12"}
    add = {"kind": "add", "row": {"reactor_name": "Gamma", "V_L_max": 5.0}}
    out = vi.apply_import_change(vi.apply_import_change(df, up), add)
    assert out.loc[0, "V_L_max"] == 12.0 and out.loc[1, "reactor_name"] == "Gamma"


# --- miscibility -----------------------------------------------------------------
def _cp(name, rho):
    return {"name": name, "vol_frac": 0.25, "mass_frac": 0.25, "rho_kg_m3": rho}


def test_bridging_solvent_does_not_merge_immiscible_phases():
    comps = [_cp("Toluene", 867), _cp("Hexane", 655), _cp("Water", 997), _cp("Methanol", 791)]
    m = lambda v: {"miscible": v}  # noqa: E731
    pair = {("Toluene", "Hexane"): m(True), ("Toluene", "Water"): m(False),
            ("Toluene", "Methanol"): m(True), ("Hexane", "Water"): m(False),
            ("Hexane", "Methanol"): m(False), ("Water", "Methanol"): m(True)}
    phases, unknown = settled_phases(comps, pair)
    assert len(phases) == 2 and not unknown
    assert phases[0]["rho"] > phases[1]["rho"]  # densest phase listed first


# --- applicability / mass-transfer / regimes ------------------------------------
def test_correlation_applicability_flags_laminar_and_missing_baffles():
    geo = VesselGeometry(D_tank=0.3, D_imp=0.1, H_max=0.4, Np=1.27, Nq=0.79)
    text = rules.correlation_applicability({"Re": 5.0}, geo, pd.Series(dtype=object), 10.0,
                                           gas_on=False, solids_on=False)
    assert "laminar regime" in text and "baffling is not recorded" in text
    assert "impeller/tank diameter ratio = 0.333" in text


def test_mass_transfer_screen_bands():
    rows = rules.mass_transfer_screen([("G", 0.005), ("S", 0.05), ("X", 0.5), ("Z", 0.0)], 100.0)
    assert [r["Screening"] for r in rows] == [
        "Potentially transfer-limited", "Capacity comparable to demand",
        "Capacity exceeds kinetic demand", "Unknown — kLa unavailable"]


def test_regime_label_thresholds():
    assert [rules.regime_label(x) for x in (0, 0.05, 0.5, 2)] == [
        "—", "🟢 Mixing-insensitive", "🟡 Transitional", "🔴 Mixing-limited"]
    assert [rules.regime(x)[0] for x in (0, 0.05, 0.5, 2)] == ["unknown", "ok", "warning", "critical"]


def test_structured_screens_carry_codes_not_labels():
    rows = rules.mass_transfer_data([("G", 0.005), ("Z", 0.0)], 100.0)
    assert [r["screening"] for r in rows] == ["limited", "unknown"]
    assert rows[0]["ratio"] == pytest.approx(0.5)
    geo = VesselGeometry(D_tank=0.3, D_imp=0.1, H_max=0.4, Np=1.27, Nq=0.79)
    res = rules.applicability_checks({"Re": 5e4}, geo, pd.Series({"baffles": "4"}), 10.0,
                                     gas_on=True, solids_on=False)
    assert "gas loading included" in res["checks"] and not any("**" in c for c in res["checks"])


# --- heat transfer ---------------------------------------------------------------
@pytest.mark.parametrize("t0, tt, tj, ok", [
    (25, 5, -10, True), (25, 5, 30, False), (25, 5, 10, False),
    (25, 60, 80, True), (25, 60, 20, False), (25, 60, 50, False)])
def test_heat_cool_setup_error(t0, tt, tj, ok):
    assert (heat_cool_setup_error(t0, tt, tj) is None) == ok


def test_sweep_range_defaults_prefers_db_bounds():
    row = pd.Series({"N_rpm_min": 50, "N_rpm_max": 500})
    assert sweep_range_defaults(row, "n_rpm", 300) == (50, 500)
    assert sweep_range_defaults(row, "rho", 1000) == (500, 1500)
    assert sweep_range_defaults(row, "mu", 0) == (0.0, 0.1)


# --- scale-up --------------------------------------------------------------------
def test_feed_plan_scales_by_max_volume_and_flags_overflow():
    info = {"Small": {"V_max_L": 1.0, "V_min_L": 0.5},
            "Big": {"V_max_L": 10.0, "V_min_L": 9.8}}
    rows, exceeded, err = scale_up.feed_plan(info, "Small", 100.0, 1.0)
    assert err is None
    assert rows[0]["Feed volume (mL)"] == "100.0" and rows[0]["Feed rate (mL/min)"] == "1.67"
    assert exceeded and exceeded[0].startswith("Big")
    assert scale_up.feed_plan(info, "Missing", 100.0, 1.0)[2] == "basis"
    data, err = scale_up.feed_plan_data(info, "Small", 100.0, 1.0)
    assert err is None and [d["exceeds_max"] for d in data] == [False, True]
    assert data[0]["feed_rate_mL_min"] == pytest.approx(100.0 / 60.0)


def test_impact_ratio_data_is_numeric():
    env = pd.DataFrame({"Reactor": ["A", "A", "B", "B"], "Volume (L)": [1, 1, 10, 10],
                        "P/V (W/L)": [1, 1, 2, 2], "Q_gen/Q_cool (%)": [50, 50, 40, 40]})
    (d,) = scale_up.impact_ratio_data(env, ["P/V (W/L)", "Q_gen/Q_cool (%)"], incl_heat=True)
    assert d["volume"] == 10 and d["P_V"] == 2 and d["cooling_delta_pp"] == -10
    assert scale_up.impact_ratios(env, ["P/V (W/L)", "Q_gen/Q_cool (%)"], True)[0]["Cooling"] \
        .startswith("✅ Improves")


def _linear_hydro(n_rps, v_l):
    # P/V rises with speed and falls with volume: P/V = 10 * N / V
    return {"P/V (W/L)": 10.0 * n_rps / v_l}


def test_match_parameter_solves_rpm_at_known_volume():
    m = scale_up.match_parameter(_linear_hydro, "P/V (W/L)", 2.0, solve_rpm=True, known=5.0,
                                 rpm_window=(10, 600), vol_window=(1, 10))
    assert m["RPM"] == pytest.approx(60.0, abs=0.02) and m["status"] == "Matched"


def test_match_parameter_solves_volume_and_reports_out_of_window():
    m = scale_up.match_parameter(_linear_hydro, "P/V (W/L)", 2.0, solve_rpm=False, known=120.0,
                                 rpm_window=(10, 600), vol_window=(5, 9))
    assert m["Volume (L)"] == pytest.approx(10.0, abs=0.01)
    assert m["status"].startswith("Matched (outside")


def test_match_parameter_returns_closest_bound_when_unreachable():
    m = scale_up.match_parameter(_linear_hydro, "P/V (W/L)", 1e6, solve_rpm=True, known=5.0,
                                 rpm_window=(10, 600), vol_window=(1, 10))
    assert m["status"].startswith("Not achievable") and m["RPM"] == pytest.approx(900.0)


def test_vessel_window_defaults_minimum_speed_to_10pct():
    geo = VesselGeometry(D_tank=0.3, D_imp=0.1, H_max=0.4, Np=1.27, Nq=0.79)
    w = scale_up.vessel_window(pd.Series({"N_rpm_max": 600, "V_L_max": 20}), geo)
    assert w["N_lo"] == pytest.approx(1.0) and w["V_min_L"] == 20
    assert scale_up.vessel_window(pd.Series({"N_rpm_max": 600}),
                                  VesselGeometry(0, 0.1, 0.4, 1.27, 0.79)) is None


# --- envelope data helpers -------------------------------------------------------
def test_sweep_surface_and_solve_target():
    from core.envelope import solve_target, surface_grid, sweep
    evaluate = lambda n, v: {"y": n * v}  # noqa: E731
    curves = sweep(evaluate, [1, 2, 3], [10, 20], ["y"])
    assert list(curves[20]["y"]) == [20, 40, 60]
    z = surface_grid(evaluate, [1, 2, 3], [10, 20], ["y"])["y"]
    assert z.shape == (2, 3) and z[1, 2] == 60
    res = solve_target(lambda x: x * 2.0, 10.0, 0.0, 20.0, window=(0.0, 4.0))
    assert res["roots"] == pytest.approx([5.0]) and res["first_in_window"] is None
    assert res["span"] == pytest.approx((0.0, 40.0))
