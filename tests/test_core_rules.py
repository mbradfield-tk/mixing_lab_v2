"""Unit tests for core.sensitivity_rules (Bourne decision tree) and core.kinetics."""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import kinetics
from core import sensitivity_rules as rules


def test_insensitive_test1_over_a_short_pm_span_is_inconclusive():
    o = rules.bourne_outcome("not_sensitive", None, None, ratio=20.0)
    assert o["s1_eff"] == "inconclusive"
    assert o["dominant"] == "Incomplete" and o["next_test"] == 2


def test_full_span_insensitive_test1_is_mixing_insensitive():
    assert rules.bourne_outcome("not_sensitive", None, None, ratio=150.0)["dominant"] == "Mixing-insensitive"


@pytest.mark.parametrize("s2, s3, dominant", [
    ("not_sensitive", None, "Micromixing"),
    ("sensitive", "sensitive", "Mesomixing"),
    ("sensitive", "not_sensitive", "Macromixing"),
    ("sensitive", "inconclusive", "Inconclusive"),
])
def test_confirmed_mechanisms(s2, s3, dominant):
    o = rules.bourne_outcome("sensitive", s2, s3, ratio=120.0)
    assert o["dominant"] == dominant and o["confirmed"]


def test_mechanism_after_inconclusive_test2_is_tentative():
    o = rules.bourne_outcome("sensitive", "inconclusive", "sensitive", ratio=120.0)
    assert o["dominant"] == "Mesomixing" and o["tentative"]


def test_effective_t_rxn_derives_from_k_and_applies_fallback():
    assert kinetics.effective_t_rxn("1", 0.5, 1.0, 0.0) == pytest.approx(2.0)
    assert kinetics.effective_t_rxn("2", 0.5, 2.0, 0.0) == pytest.approx(1.0)
    assert kinetics.effective_t_rxn("1", 0.0, 1.0, 0.0) == 0.0
    assert kinetics.effective_t_rxn("1", 0.0, 1.0, 0.0, fallback=1.0) == 1.0
    assert kinetics.effective_t_rxn("1", 0.5, 1.0, 7.0) == 7.0


def test_unknown_reaction_gets_first_order_defaults():
    kd = kinetics.kinetics_defaults("__no_such_reaction__")
    assert kd["order"] == "1" and kd["k"] == 0.0 and kd["T"] == 25.0 and kd["solvent"] == ""


# ---- Reaction Sensitivity Protocol ----------------------------------------
def _inputs(**kw):
    base = dict(order="1", k=1.0, C0=1.0, t_specified=0.0, dH=-80.0, competing="no",
                phases=["liquid"], c0_heat=1.0, rho_cp=1800.0)
    base.update(kw)
    return rules.ProtocolInputs(**base)


@pytest.mark.parametrize("status, mech, done, expected", [
    ("confirmed", "Mesomixing", [3, 1], (True, ["Mesomixing"], [1, 3])),
    ("confirmed", "Unresolved", [1], (True, [], [1])),
    ("insensitive", "Micromixing", [1], (False, [], [1])),
    ("inconclusive", "", [2], (None, [], [2])),
    ("skip", "Micromixing", [1, 2], (None, [], [])),
])
def test_bourne_prescreen(status, mech, done, expected):
    assert rules.bourne_prescreen(status, mech, done) == expected


def test_complete_answers_give_a_verdict_and_adiabatic_rise():
    r = rules.assess_protocol(_inputs())
    assert r["ready"] and r["verdict"].text and rules.protocol_md(r)["summary_note"] == ""
    assert r["t_rxn"] == pytest.approx(1.0)
    assert r["dt_ad"] == pytest.approx(80.0 * 1000.0 / 1800.0)
    assert r["findings"] and r["next_steps"]


@pytest.mark.parametrize("override", [
    dict(competing=""),
    dict(phases=[]),
    dict(dH=0.0),                       # ΔH unresolved: no action chosen
    dict(k=0.0, kinetics="available"),  # no usable t_rxn and not declined
])
def test_missing_answers_block_the_verdict(override):
    r = rules.assess_protocol(_inputs(**override))
    assert not r["ready"] and rules.protocol_md(r)["summary_note"]


def test_declined_kinetics_and_calorimetry_still_resolve():
    r = rules.assess_protocol(_inputs(k=0.0, kinetics="declined", dH=0.0, dh_action="calorimetry"))
    assert r["ready"] and r["show_dh_action"] and r["dt_ad"] is None


def test_dh_estimate_from_similar_reaction_is_flagged_estimated():
    r = rules.assess_protocol(_inputs(dH=0.0, dh_action="estimate", dh_ref_value=-120.0))
    assert r["ready"] and r["dH_eff"] == -120.0 and r["dh_estimated"]
    assert "estimated" in r["steps"][4].text


def test_measured_override_wins_over_database_dh():
    r = rules.assess_protocol(_inputs(dh_override=-30.0, dh_override_measured=True,
                                      kinetics="approximate"))
    assert r["dH_eff"] == -30.0 and not r["dh_estimated"]


def test_damkohler_callback_only_called_with_known_kinetics():
    calls = []
    rules.assess_protocol(_inputs(k=0.0, kinetics="declined"), damkohler_for=calls.append)
    assert calls == []
    rules.assess_protocol(_inputs(), damkohler_for=lambda t: calls.append(t))
    assert calls == [pytest.approx(1.0)]


# Slow reaction (t_rxn = 100 s), single liquid phase, batch, no competing reactions.
_QUIET = dict(k=0.01, bourne="insensitive", bourne_tests_done=[1])


def test_heat_flag_is_not_reported_as_a_mixing_sensitivity():
    r = rules.assess_protocol(_inputs(**_QUIET, dH=-200.0))
    v = r["verdict"]
    assert any(f.code == "heat.limiting" for f in r["findings"])
    assert v.code == "low" and v.kind == "warning"
    assert "heat transfer needs review" in v.text and "not a mixing sensitivity" in v.text
    assert "Damköhler" not in v.text and "scale-dependent" not in v.text
    assert any(a.code == "heat.balance" for a in r["next_steps"])


def test_no_heat_flag_gives_a_plain_low_verdict():
    v = rules.assess_protocol(_inputs(**_QUIET, dH=-10.0))["verdict"]
    assert v.code == "low" and v.kind == "ok" and "heat" not in v.text.lower()


def test_scale_dependent_verdict_names_the_right_confirmation():
    r = rules.assess_protocol(_inputs(**_QUIET, dH=-10.0, competing="yes"))
    v = r["verdict"]
    assert v.code == "scale_dependent" and "micro/mesomixing" in v.text
    assert "Bourne Tests 2 and 3" in v.text and "Damköhler" not in v.text
    assert [a.code for a in r["next_steps"]].count("selectivity.bourne") == 1


def test_theory_only_counts_mixing_mechanisms_only():
    # One mixing mechanism (very fast reaction) plus a heat flag is moderate, not "multiple mechanisms".
    v = rules.assess_protocol(_inputs(k=100.0, dH=-200.0))["verdict"]
    assert v.code == "moderate" and "Separately, heat transfer" in v.text


def test_fast_reaction_finding_matches_step_severity():
    r = rules.assess_protocol(_inputs(k=2.0, dH=-10.0))  # t_rxn = 0.5 s
    micro = next(f for f in r["findings"] if f.code == "micromixing.fast_reaction")
    assert r["steps"][5].kind == micro.kind == "warning"


def test_semi_batch_has_one_feed_zone_finding_and_action():
    r = rules.assess_protocol(_inputs(dH=-10.0, competing="yes", semi_batch=True))
    assert not any(f.area.startswith("Semi-batch") for f in r["findings"])
    assert [a.code for a in r["next_steps"]].count("selectivity.bourne") == 1


def test_computed_damkohler_asks_for_a_recheck_not_a_new_calculation():
    da = dict(reactor="R", N_rpm=300.0, V_L=1.0, fluid="Water", Re=1e4, P_V_W_L=0.1,
              t_blend=5.0, t_E=0.01, Da_macro=5.0, Da_micro=0.01)
    r = rules.assess_protocol(_inputs(dH=-10.0), damkohler_for=lambda t: da)
    codes = [a.code for a in r["next_steps"]]
    assert "damkohler.recheck" in codes and "damkohler.compute" not in codes
