"""Golden-value guards for the page compute paths (refactor safety net).

Each scenario drives a page's compute handler with a stand-in state and compares
the numeric/text outputs against tests/golden/page_outputs.json. The scenarios
read data/*.csv, so an intended DB edit or model change needs a regeneration:

    UPDATE_GOLDEN=1 pytest tests/test_golden_outputs.py
"""

import copy
import json
import math
import os
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pages import bourne_protocol as bp
from pages import heat_transfer as ht
from pages import mixing_sensitivity as ms
from pages import vessel_assessment as va
from pages import vessel_comparison as vc

GOLDEN = Path(__file__).parent / "golden" / "page_outputs.json"


@pytest.fixture(autouse=True)
def _silence_notify(monkeypatch):
    for mod in (va, vc, ht, ms, bp):
        monkeypatch.setattr(mod, "notify", lambda *_a, **_k: None)


def _state(mod, **overrides) -> SimpleNamespace:
    """Stand-in Taipy state holding a copy of every module-level GUI variable."""
    values = {k: copy.copy(v) for k, v in vars(mod).items()
              if not k.startswith("__") and not callable(v) and not isinstance(v, ModuleType)}
    st = SimpleNamespace(**values)
    for k, v in overrides.items():
        setattr(st, k, v)
    return st


def _norm(obj):
    if isinstance(obj, pd.DataFrame):
        return [_norm(r) for r in obj.to_dict("records")]
    if isinstance(obj, dict):
        return {str(k): _norm(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, np.ndarray)):
        return [_norm(v) for v in obj]
    if isinstance(obj, (bool, np.bool_)):
        return bool(obj)
    if isinstance(obj, (int, float, np.integer, np.floating)):
        f = float(obj)
        if math.isnan(f) or math.isinf(f):
            return str(f)
        return float(f"{f:.6g}")
    return obj


def _fig_y(fig) -> list:
    return [list(t.y) for t in fig.data if getattr(t, "y", None) is not None]


# --------------------------------------------------------------------------- VA
_VA_FULL = dict(va_sl_mode="On", va_gas_mode="On", va_gas_transfer="Sparging",
                va_fed_mode="On", va_feed_location="Near impeller", va_dH=-100.0)


def _va(**ov):
    st = _state(va, **ov)
    va.on_va_compute(st)
    st.va_solve_param, st.va_solve_target = "P/V (W/L)", 0.5
    va.on_va_solve(st)
    cache = st._va_cache
    return {
        "hydro": cache["hydro"], "dam": cache["dam"], "t_rxn": cache["t_rxn"],
        "hydro_df": st.va_hydro_df, "dam_df": st.va_dam_df, "assess": st.va_assess,
        "sl_df": st.va_sl_df, "heat_df": st.va_heat_df, "mt_df": st.va_mt_df,
        "env_y": _fig_y(st.va_env_fig), "solve_df": st.va_solve_df,
        "solve_status": st.va_solve_status,
    }


# --------------------------------------------------------------------------- VC
_VC_FULL = dict(vc_incl_particles="On", vc_gas_mode="On", vc_gas_transfer="Sparging",
                vc_fed_mode="On", vc_feed_location="Near impeller", vc_rxn_dh=-100.0,
                vc_incl_scaling="On")


def _vc(**ov):
    st = _state(vc, **ov)
    vc._build_targets(st)
    vc.on_vc_compute(st)
    return {
        "env_df": st._vc_cache["env_df"], "summary_df": st.vc_summary_df,
        "heat_df": st.vc_heat_df, "scale_df": st.vc_scale_df,
        "scale_full_df": st.vc_scale_full_df, "impact_df": st.vc_impact_df,
        "feed_plan_df": st.vc_feed_plan_df,
    }


# --------------------------------------------------------------------------- HT
def _ht(**ov):
    st = _state(ht, **ov)
    ht.on_compute(st)
    return {"kpi_df": st.kpi_df, "summary_df": st.summary_df, "corr_df": st.corr_df,
            "htm_compare_df": st.htm_compare_df, "agitator_text": st.agitator_text,
            "status": st.status_message, "ua_rpm_y": _fig_y(st.ua_rpm_fig),
            "ua_vol_y": _fig_y(st.ua_vol_fig), "resistance_x": list(st.res_fig.data[0].x)}


def _ht_sweep():
    st = _state(ht, ht_mode=ht.HT_MODE_SWEEP)
    ht._refresh_sweep_ranges(st)
    ht.on_compute(st)
    return {"u": [list(r) for r in st.sweep_u_fig.data[0].z],
            "ua": [list(r) for r in st.sweep_ua_fig.data[0].z]}


# --------------------------------------------------------------------------- BP
def _bp(**ov):
    st = _state(bp, **ov)
    bp._build_plan(st)
    return {"t1_info": st.bp_t1_ctr_info, "t1_pm": st.bp_t1_pm_eff, "t1": st.bp_t1_hydro_df,
            "t1_adj": st.bp_t1_adj_result_df, "t1_adj_caption": st.bp_t1_adj_caption,
            "t1_plot_y": _fig_y(st.bp_t1_plot), "t2": st.bp_t2_cond_df, "t3": st.bp_t3_cond_df,
            "t1_ratio": bp._test1_range_ratio(st), "center": bp._centerpoint_metrics(st)}


# --------------------------------------------------------------------------- MS
def _ms(**ov):
    st = _state(ms, ms_started=True, **ov)
    ms._recompute(st)
    texts = {k: getattr(st, k) for k in sorted(vars(st))
             if k.startswith("ms_step") and k.endswith("_assess")}
    captions = {k: getattr(st, k) for k in (
        "ms_kinetics_md", "ms_dt_ad_caption", "ms_trxn_caption", "ms_da_caption",
        "ms_summary_note", "ms_ready", "ms_show_dh_action")}
    cache = {k: v for k, v in st._ms_cache.items() if k != "bourne_meta"}
    return {"verdict": st.ms_verdict, "findings": st.ms_findings_df,
            "next_steps": st.ms_nextsteps_df, **texts, **captions, "cache": cache}


_MS_BASE = dict(ms_competing="No", ms_phases=["Liquid"], ms_rxn_order="1", ms_rxn_k=0.01,
                ms_rxn_c0=1.0, ms_rxn_trxn=0.0, ms_rxn_dh=-50.0)
_BOURNE_ROWS = pd.DataFrame([{"Test": "Test 1 - Impeller speed",
                              "Finding": "Mixing-sensitive (impeller speed)",
                              "Sensitive KPI(s)": "Yield (12.0%); Impurity A (qualitative)"}])


def _ms_case(**ov):
    return lambda: _ms(**{**_MS_BASE, **ov})


SCENARIOS = {
    "va_default": lambda: _va(),
    "va_full": lambda: _va(**_VA_FULL),
    "va_warm_coolant_gas_off": lambda: _va(va_sl_mode="On", va_dH=-100.0, va_T_cool=35.0),
    "vc_default": lambda: _vc(),
    "bp_default": lambda: _bp(),
    "bp_custom_rpm_fedbatch": lambda: _bp(
        bp_t1_ctr_mode="Custom RPM", bp_t1_rpm_center=900.0, bp_t1_adj_mode="On",
        bp_t1_adj_vols_df=pd.DataFrame([{"Volume (L)": 0.08}, {"Volume (L)": 0.1}]),
        bp_t2_mode="Feed time", bp_t2_time=30.0, bp_t3_impeller_ratio=5.0),
    "bp_custom_pm": lambda: _bp(bp_t1_ctr_mode="Custom P/m", bp_t1_pm_center=2.0),
    "vc_full": lambda: _vc(**_VC_FULL),
    "vc_warm_coolant": lambda: _vc(vc_rxn_dh=-100.0, vc_T_cool=35.0),
    "vc_scale_volume": lambda: _vc(vc_incl_scaling="On",
                                   vc_scale_solve_for=vc.scale_solve_options[1]),
    "ht_default": lambda: _ht(),
    "ht_agitator_off": lambda: _ht(include_agitator="Off"),
    "ht_sweep": _ht_sweep,
    "ms_default": lambda: _ms(ms_competing="No", ms_phases=["Liquid", "Solid"],
                              ms_rxn_order="1", ms_rxn_k=0.01, ms_rxn_c0=1.0,
                              ms_rxn_trxn=0.0, ms_rxn_dh=-50.0),
    "ms_inline_da": lambda: _ms(ms_competing="Yes", ms_phases=["Liquid", "Gas"],
                                ms_rxn_order="2", ms_rxn_k=5.0, ms_rxn_c0=0.5,
                                ms_rxn_trxn=0.0, ms_rxn_dh=-120.0, ms_da_mode="On"),
    "ms_bourne_confirmed_mech": _ms_case(
        ms_bourne_status=ms.ms_bourne_status_options[1], ms_bourne_mech="Mesomixing",
        ms_bourne_tests=["Test 1", "Test 2", "Test 3"], ms_bourne_findings_df=_BOURNE_ROWS),
    "ms_bourne_confirmed_unresolved": _ms_case(
        ms_bourne_status=ms.ms_bourne_status_options[1], ms_bourne_tests=["Test 1"],
        ms_bourne_findings_df=_BOURNE_ROWS, ms_competing="Not sure"),
    "ms_bourne_insensitive_fast": _ms_case(
        ms_bourne_status=ms.ms_bourne_status_options[2], ms_rxn_k=50.0),
    "ms_bourne_inconclusive_semibatch": _ms_case(
        ms_bourne_status=ms.ms_bourne_status_options[3], ms_bourne_tests=["Test 2"],
        ms_semi_batch="On", ms_rxn_k=2.0),
    "ms_kinetics_declined": _ms_case(ms_kinetics_avail=ms.ms_kinetics_options[2]),
    "ms_kinetics_missing": _ms_case(ms_rxn_k=0.0),
    "ms_proxy_kinetics_endothermic": _ms_case(
        ms_kinetics_avail=ms.ms_kinetics_options[1], ms_rxn_dh=30.0, ms_phases=["Solid"]),
    "ms_dh_estimate_similar": _ms_case(
        ms_rxn_dh=0.0, ms_dh_action=ms.ms_dh_action_options[2], ms_dh_ref=ms.dh_ref_options[0]),
    "ms_dh_calorimetry": _ms_case(ms_rxn_dh=0.0, ms_dh_action=ms.ms_dh_action_options[1]),
    "ms_dh_unresolved": _ms_case(ms_rxn_dh=0.0),
    "ms_dh_override_measured": _ms_case(ms_dh_override=-150.0, ms_dh_measured="Yes - measured",
                                        ms_rho_cp=1500.0, ms_c0_heat=2.0),
    "ms_incomplete_inputs": _ms_case(ms_phases=[], ms_competing="- select -"),
    "ms_very_fast_competing": _ms_case(ms_rxn_order="2", ms_rxn_k=500.0, ms_rxn_c0=0.5,
                                       ms_competing="Yes", ms_semi_batch="On"),
}


def _first_diff(a, b, path="$"):
    if type(a) is not type(b):
        return f"{path}: {a!r} != {b!r}"
    if isinstance(a, dict):
        for k in sorted(set(a) | set(b)):
            if k not in a or k not in b:
                return f"{path}.{k}: missing on one side"
            d = _first_diff(a[k], b[k], f"{path}.{k}")
            if d:
                return d
        return None
    if isinstance(a, list):
        if len(a) != len(b):
            return f"{path}: length {len(a)} != {len(b)}"
        for i, (x, y) in enumerate(zip(a, b)):
            d = _first_diff(x, y, f"{path}[{i}]")
            if d:
                return d
        return None
    return None if a == b else f"{path}: {a!r} != {b!r}"


@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_page_outputs_match_golden(name):
    got = json.loads(json.dumps(_norm(SCENARIOS[name]()), ensure_ascii=False))
    if os.environ.get("UPDATE_GOLDEN"):
        data = json.loads(GOLDEN.read_text()) if GOLDEN.exists() else {}
        data[name] = got
        GOLDEN.parent.mkdir(exist_ok=True)
        GOLDEN.write_text(json.dumps(data, indent=1, ensure_ascii=False, sort_keys=True))
        pytest.skip("golden updated")
    expected = json.loads(GOLDEN.read_text())[name]
    diff = _first_diff(got, expected)
    assert diff is None, diff
