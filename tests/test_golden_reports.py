"""Golden guards for the PDF report snapshots and the Plotly figures.

Each scenario drives a page, captures the snapshot dict handed to the PDF builder
(the builder itself is stubbed) and fingerprints every figure by the SHA-256 of its
full JSON, so moving figure/snapshot code must reproduce them exactly.

    UPDATE_GOLDEN=1 pytest tests/test_golden_reports.py
"""

import hashlib
import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import test_golden_outputs as g  # noqa: E402  (tests/ is on sys.path under pytest)
from pages import bourne_protocol as bp
from pages import fluid_database as fdb
from pages import heat_transfer as ht
from pages import mixing_sensitivity as ms
from pages import vessel_assessment as va
from pages import vessel_comparison as vc
from utils import bourne_kpi as kpi
from utils import report_builder as rb

GOLDEN = Path(__file__).parent / "golden" / "report_outputs.json"
_PDF_BUILDERS = ("build_vessel_assessment_pdf", "build_reactor_comparison_pdf",
                 "build_protocol_pdf", "build_bourne_protocol_pdf", "build_heat_transfer_pdf")
_PAGES = (va, vc, ht, ms, bp, fdb)


def _fig_key(fig) -> str:
    return "fig:" + hashlib.sha256(fig.to_json().encode()).hexdigest()[:20]


def _n(obj):
    if isinstance(obj, go.Figure):
        return _fig_key(obj)
    if isinstance(obj, (bytes, bytearray)):
        return obj.decode() if obj.startswith(b"fig:") else f"bytes[{len(obj)}]"
    if isinstance(obj, pd.DataFrame):
        return [_n(r) for r in obj.to_dict("records")]
    if isinstance(obj, dict):
        return {str(k): _n(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, np.ndarray)):
        return [_n(v) for v in obj]
    return g._norm(obj)


@pytest.fixture
def captured(monkeypatch):
    got = {}

    def fake_png(fig):
        return _fig_key(fig).encode()

    for mod in (rb, *_PAGES):
        monkeypatch.setattr(mod, "fig_to_png_bytes", fake_png, raising=False)
        monkeypatch.setattr(mod, "notify", lambda *_a, **_k: None, raising=False)
        for name in _PDF_BUILDERS:
            def fake(snap, _name=name):
                got[_name] = snap
                return b"%PDF-stub"
            monkeypatch.setattr(mod, name, fake, raising=False)
    monkeypatch.setattr(rb, "notify", lambda *_a, **_k: None, raising=False)
    return got


def _va(got):
    st = g._state(va, **g._VA_FULL)
    va.on_va_compute(st)
    va.on_va_surface(st)
    va.on_va_export_pdf(st)
    return {"snap": got["build_vessel_assessment_pdf"], "env_fig": st.va_env_fig,
            "surf_fig": st.va_surf_fig, "env_class": st.va_env_class,
            "surf_class": st.va_surf_class, "env_caption": st.va_env_caption,
            "surf_caption": st.va_surf_caption}


def _vc(got):
    st = g._state(vc, **g._VC_FULL)
    vc._build_targets(st)
    vc.on_vc_compute(st)
    st.vc_ready = True  # the full scenario's feed plan overflows, which blocks export
    vc.on_vc_export_pdf(st)
    return {"snap": got["build_reactor_comparison_pdf"], "env_fig": st.vc_env_fig,
            "env_class": st.vc_env_class}


def _ms(got):
    st = g._state(ms, ms_started=True, **{**g._MS_BASE, "ms_da_mode": "On"})
    ms._recompute(st)
    ms.on_ms_export_pdf(st)
    snap = dict(got["build_protocol_pdf"])
    return {"snap": snap}


def _ht_batch(got):
    st = g._state(ht)
    ht.on_compute(st)
    ht.on_ht_export_pdf(st)
    return {"snap": got["build_heat_transfer_pdf"], "figs": [
        st.temp_fig, st.duty_fig, st.res_fig, st.ua_rpm_fig, st.ua_vol_fig],
        "agitator_text": st.agitator_text}


def _ht_reaction(got):
    st = g._state(ht, ht_mode=ht.HT_MODE_RXN, rxn_k=0.01, rxn_c0=1.0, rxn_dH=-100.0)
    ht.on_compute(st)
    ht.on_ht_export_pdf(st)
    return {"snap": got["build_heat_transfer_pdf"], "rxn_fig": st.rxn_fig}


def _ht_sweep(got):
    st = g._state(ht, ht_mode=ht.HT_MODE_SWEEP)
    ht._refresh_sweep_ranges(st)
    ht.on_compute(st)
    return {"figs": [st.sweep_u_fig, st.sweep_ua_fig]}


def _kpi_result(test: int, values):
    df = kpi.new_kpi_df(test)
    df.loc[0, list(kpi.KPI_COLUMNS[test])] = values
    return kpi.assess_kpis(df, test)


def _bp(got):
    st = g._state(bp, bp_t1_adj_mode="On",
                  bp_t1_adj_vols_df=pd.DataFrame([{"Volume (L)": 0.08}, {"Volume (L)": 0.1}]))
    bp._build_plan(st)
    st.bp_t1_assessed, st.bp_t1_result = True, _kpi_result(1, [90.0, 100.0, 112.0])
    st.bp_t2_assessed, st.bp_t2_result = True, _kpi_result(2, [95.0, 100.0, 108.0])
    st.bp_t3_assessed, st.bp_t3_result = True, _kpi_result(3, [100.0, 100.0, 101.0])
    bp.on_bp_export_pdf(st)
    return {"snap": got["build_bourne_protocol_pdf"], "t1_plot": st.bp_t1_plot}


def _fluids(_got):
    props_df, msg, fig = fdb._compute_solvent_props("Toluene", 1.0, 60.0)
    st = g._state(fdb, blend_input_df=pd.DataFrame(
        [{"Component": "Water", "Amount": 50.0}, {"Component": "Toluene", "Amount": 30.0},
         {"Component": "Methanol", "Amount": 20.0}]))
    fdb.on_blend_compute(st)
    return {"props_df": props_df, "msg": msg, "prop_fig": fig,
            "phase_fig": st.blend_phase_fig, "placeholder": fdb.blend_phase_fig,
            "initial_prop_fig": fdb.solvent_prop_fig}


SCENARIOS = {"va": _va, "vc": _vc, "ms": _ms, "ht_batch": _ht_batch,
             "ht_reaction": _ht_reaction, "ht_sweep": _ht_sweep, "bp": _bp, "fluids": _fluids}


@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_report_snapshots_and_figures_match_golden(name, captured):
    got = json.loads(json.dumps(_n(SCENARIOS[name](captured)), ensure_ascii=False))
    if os.environ.get("UPDATE_GOLDEN"):
        data = json.loads(GOLDEN.read_text()) if GOLDEN.exists() else {}
        data[name] = got
        GOLDEN.write_text(json.dumps(data, indent=1, sort_keys=True, ensure_ascii=False))
        pytest.skip("golden updated")
    want = json.loads(GOLDEN.read_text())[name]
    diff = g._first_diff(got, want)
    assert diff is None, diff
