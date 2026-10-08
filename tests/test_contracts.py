"""Contract tests: the JSON services reproduce the golden page results, and every
response serialises to strict JSON (no NaN/inf)."""

import json
import os
import sys

import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import kinetics
from core import schemas as s
from core import services as svc
from core.messages import icon
from core.serialize import jsonable

from golden_helpers import PAGE_OUTPUTS as GOLDEN, REQUESTS  # noqa: E402


def _strict(model) -> dict:
    def _reject(c):
        raise AssertionError(f"non-JSON constant {c}")
    return json.loads(model.model_dump_json(), parse_constant=_reject)


def _close(a, b, rel=1e-5):
    return a == pytest.approx(b, rel=rel)


# --------------------------------------------------------------------------- VA
def _va_request(full: bool = False) -> s.PointRequest:
    """The Vessel Assessment defaults (and the golden 'va_full' options) as a request."""
    return s.PointRequest.model_validate(REQUESTS["va_full" if full else "va_default"])


@pytest.mark.parametrize("scenario, full", [("va_default", False), ("va_full", True)])
def test_evaluate_matches_vessel_assessment(scenario, full):
    got = _strict(svc.evaluate(_va_request(full)))
    want = GOLDEN[scenario]["hydro"]
    for key, value in want.items():
        field = s.CORE_KEYS[key]
        if isinstance(value, str) and field != "assessment":
            assert got[field] is None, key            # golden stores non-finite as text
        elif isinstance(value, str):
            assert got[field] == value
        else:
            assert _close(got[field], value), key
    assert got["extra"] == {}


@pytest.mark.parametrize("scenario, full", [("va_default", False), ("va_full", True)])
def test_solve_matches_vessel_assessment(scenario, full):
    res = svc.solve(s.SolveRequest(point=_va_request(full), parameter="P_V_W_L", target=0.5))
    rows = GOLDEN[scenario]["solve_df"]
    assert [f"{r.value:,.4g}" for r in res.solutions] == [r["Value"] for r in rows]
    assert [("Yes" if r.in_vessel_range else "No") for r in res.solutions] == \
        [r["Within vessel range"] for r in rows]
    assert res.status == "solved" and _strict(res)["best"] == pytest.approx(res.solutions[0].value)


def test_sweep_matches_vessel_assessment_envelope():
    params = ["Da_macro", "Da_micro", "P_V_W_L", "blend_time_95_s", "tip_speed_m_s", "Re"]
    assert [s.core_key(p) for p in params] == REQUESTS["va_env_params"]
    res = svc.sweep(s.SweepRequest(point=_va_request(), parameters=params))
    v_min, v_max = res.vessel_V_range_L
    env_y = GOLDEN["va_default"]["env_y"]
    for i, p in enumerate(params):   # traces per panel: band, V_max, V_min, operating point
        hi = next(c for c in res.curves if c.V_L == v_max and c.parameter == p)
        lo = next(c for c in res.curves if c.V_L == v_min and c.parameter == p)
        assert np.allclose(hi.values, env_y[4 * i + 1], rtol=1e-5)
        assert np.allclose(lo.values, env_y[4 * i + 2], rtol=1e-5)
    _strict(res)


def test_surface_shape_and_json():
    res = svc.surface(s.SurfaceRequest(point=_va_request(), parameters=["Re", "Da_micro"],
                                       n_points=4, v_points=3))
    assert len(res.N_rpm) == 4 and len(res.V_L) == 3
    assert [len(r) for r in res.z["Re"]] == [4, 4, 4]
    _strict(res)


# --------------------------------------------------------------------------- MS
MS_SCENARIOS = sorted(REQUESTS["ms_scenarios"])


@pytest.mark.parametrize("name", MS_SCENARIOS)
def test_assess_matches_mixing_sensitivity_page(name):
    res = svc.assess(s.ProtocolRequest.model_validate(REQUESTS["ms_scenarios"][name]))
    want = GOLDEN[name]
    out = _strict(res)

    def md(m):
        return f"{icon(m['kind'])} {m['text']}" if m else ""

    assert out["ready"] == want["ms_ready"]
    assert (md(out["verdict"]) if out["ready"] else "") == want["verdict"]
    assert [md(m) for m in out["steps"]] == [want[f"ms_step{i}_assess"] for i in range(6)]
    assert [{"Sensitivity Type": f["area"],
             "Finding": f"{icon(f['kind'])} {f['status']} - {f['detail']}"}
            for f in out["findings"]] == want["findings"]
    assert [{"Area": a["area"], "Recommended action": a["action"]}
            for a in out["next_steps"]] == want["next_steps"]
    assert all(f["code"] for f in out["findings"]) and out["verdict"]["code"]


# --------------------------------------------------------------------------- misc
def test_validation_rejects_bad_requests():
    with pytest.raises(ValidationError):
        s.PointRequest(reactor="R", N_rpm=-5, V_L=1)
    with pytest.raises(ValidationError):
        s.SolveRequest(point=_va_request(), parameter="P/V (W/L)", target=1)
    with pytest.raises(ValidationError):
        s.PointRequest(reactor="R", N_rpm=100, V_L=1, unexpected=1)
    with pytest.raises(LookupError):
        svc.evaluate(_va_request().model_copy(update={"reactor": "__no_such_vessel__"}))


def test_reaction_orders_match_core_options():
    assert set(s.ReactionOrder.__args__) == set(kinetics.ORDER_OPTIONS)


def test_option_sets_round_trip_labels_and_accept_ui_wording():
    from core import options as o
    for enum in (o.Toggle, o.CorrSource, o.FeedLocation, o.GasTransfer, o.Coalescence,
                 o.CenterMode, o.FeedBasis, o.Mechanism, o.BourneStatus, o.Kinetics, o.Phase,
                 o.Competing, o.DhAction, o.DhBasis):
        labels = enum.labels()
        assert len(set(labels)) == len(labels) == len(enum)
        assert [enum.from_label(lbl) for lbl in labels] == list(enum)
    assert o.Competing.from_label("- select -") is None
    custom = {o.Coalescence.COALESCING: "Coalescing (pure liquid)"}
    assert o.Coalescence.from_label("Coalescing (pure liquid)", labels=custom) \
        is o.Coalescence.COALESCING
    assert o.is_on("On") and o.is_on(True) and not o.is_on("Off")
    # The API speaks codes, not labels.
    assert s.ProtocolRequest(reaction=s.ReactionSpec(), phases=["gas"]).phases == [o.Phase.GAS]
    with pytest.raises(ValidationError):
        s.ProtocolRequest(reaction=s.ReactionSpec(), phases=["Gas"])


def test_json_schemas_generate():
    for model in (s.PointRequest, s.PointResult, s.SolveRequest, s.SolveResult,
                  s.SweepRequest, s.SurfaceRequest, s.ProtocolRequest, s.ProtocolResult):
        assert model.model_json_schema()["type"] == "object"


def test_jsonable_handles_numpy_pandas_and_non_finite():
    data = {"a": np.float64("nan"), "b": np.array([1.0, np.inf]), "c": (np.int64(2), True),
            "d": pd.DataFrame([{"x": 1.5}]), 3: pd.Series({"y": np.bool_(False)})}
    assert jsonable(data) == {"a": None, "b": [1.0, None], "c": [2, True],
                              "d": [{"x": 1.5}], "3": {"y": False}}
    json.dumps(jsonable(data), allow_nan=False)
