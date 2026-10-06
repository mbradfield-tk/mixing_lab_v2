"""Mixing-sensitivity decision rules: the Reaction Sensitivity Protocol findings,
verdict and next steps, Damköhler bands, and the Bourne Protocol decision tree.

Every function is a pure function of its arguments (no GUI state).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable

import numpy as np

from utils.calculations import characteristic_reaction_time

TEST_PURPOSE = {1: "impeller speed", 2: "feed rate/time", 3: "feed location"}

KNOWN_HOT = ["grignard", "nitration", "sulfonation", "diazotization",
             "polymerization", "hydrogenation", "oxidation"]


# ---------------------------------------------------------------------------
# Text helpers
# ---------------------------------------------------------------------------
def amd(kind: str, text: str) -> str:
    """Traffic-light assessment line: emoji + markdown text."""
    icon = {"critical": "🔴", "warning": "🟡", "caution": "🟡",
            "ok": "🟢", "unknown": "⚪"}.get(kind, "⚪")
    return f"{icon} {text}"


def strip_md(text: str) -> str:
    return text.replace("**", "").replace("🔴", "").replace("🟡", "").replace("🟢", "").strip()


def remaining_tests(done_tests, needed=(2, 3)) -> list[int]:
    if done_tests is None:
        return list(needed)
    if isinstance(done_tests, bool):
        done_tests = [] if not done_tests else list(needed)
    if not isinstance(done_tests, (list, tuple, set)):
        done_tests = []
    return [t for t in needed if t not in set(done_tests)]


def fmt_tests(nums) -> str:
    if not nums:
        return ""
    if len(nums) == 1:
        return f"Test {nums[0]}"
    return "Tests " + " and ".join(str(n) for n in nums)


def fmt_test_purposes(nums) -> str:
    return " and ".join(TEST_PURPOSE[n] for n in nums if n in TEST_PURPOSE)


def join_mechs(names: list[str]) -> str:
    clean = [n.split("(")[0].strip().lower() for n in names]
    if len(clean) == 1:
        return clean[0]
    if len(clean) == 2:
        return f"{clean[0]} and {clean[1]}"
    return ", ".join(clean[:-1]) + f", and {clean[-1]}"


def sensitive_kpi_phrase(test_rows) -> str:
    names, seen = [], set()
    for r in (test_rows or []):
        for entry in str(r.get("Sensitive KPI(s)", "")).split(";"):
            entry = entry.strip()
            if not entry or entry.lower().startswith("none"):
                continue
            name = re.sub(r"\s*\((?:[\d.]+%|qualitative)\)\s*$", "", entry).strip()
            if name and name not in seen:
                seen.add(name)
                names.append(name)
    return ", ".join(names) if names else "the tracked response(s)"


# ---------------------------------------------------------------------------
# Screening rules
# ---------------------------------------------------------------------------
def mesomixing_risk(competing: str, is_semi_batch: bool) -> tuple[bool, bool]:
    """Return (mesomixing-sensitive, requires-feed-zone-assessment).

    Semi-batch operation is a feed-zone risk, but not automatically a confirmed
    mesomixing sensitivity. The user must still assess the feed conditions and
    test data before the sensitivity is elevated.
    """
    meso_sensitive = competing in ("Yes", "Not sure")
    require_feed_zone = is_semi_batch and not meso_sensitive
    return meso_sensitive, require_feed_zone


def damkohler_screening_note(t_rxn: float) -> str:
    """Return the preliminary screening note for reaction-time heuristics.

    The legacy time bands are retained as a quick screen only; the engineering
    decision should be confirmed with reactor-specific Damköhler numbers.
    """
    if not np.isfinite(t_rxn) or t_rxn <= 0:
        return ("Reaction time is unavailable, so this is only a qualitative screening. "
                "Compute reactor-specific Da_macro / Da_micro on the Vessel Assessment page to "
                "resolve the actual mixing sensitivity.")
    if t_rxn < 0.1:
        basis = "very fast"
    elif t_rxn < 1.0:
        basis = "fast"
    elif t_rxn < 10.0:
        basis = "moderate"
    else:
        basis = "slow"
    return (
        f"This {basis}-reaction classification is only a preliminary screening heuristic; "
        "the actual mechanism should be checked with reactor-specific Damköhler numbers "
        "(Da_macro and Da_micro) on the Vessel Assessment page."
    )


def heat_transfer_summary(abs_dH: float, dt_ad: float | None = None, *,
                          dH_eff: float | None = None) -> str:
    """Return a narrative that separates thermal severity from heat-transfer fit.

    Thermal severity asks whether the reaction can generate a dangerous
    temperature excursion; heat-transfer capability asks whether the jacket/heat
    removal system can remove or supply the heat. The message distinguishes
    exothermic and endothermic outcomes.
    """
    signed = abs_dH
    if dH_eff is not None:
        signed = dH_eff
    if signed < 0:
        sign = "exothermic"
        mag = abs(signed)
    else:
        sign = "endothermic"
        mag = abs(signed)

    if dt_ad is None:
        if mag < 20:
            return ("Thermal severity: low; heat-transfer capability is likely manageable. "
                    f"This is a mild {sign} reaction and the system should be checked with a "
                    "heat balance, but no severe thermal excursion is indicated.")
        if mag < 50:
            return ("Thermal severity: moderate; heat-transfer capability should be confirmed. "
                    f"The {sign} profile is not trivial and should be checked with a heat balance "
                    "and cooling/heating duty analysis.")
        return ("Thermal severity: high; heat-transfer capability requires explicit review. "
                f"This {sign} reaction warrants a detailed heat-balance check for cooling or "
                "heat input adequacy.")

    if sign == "exothermic":
        if dt_ad >= 200:
            return ("Thermal severity: very high; runaway potential is significant. "
                    "Cooling capacity and emergency relief / quench strategy must be reviewed. "
                    "This is separate from the heat-transfer capability check: the issue is the "
                    "ability to reject heat, not merely whether the jacket is sized for average duty.")
        if dt_ad >= 50:
            return ("Thermal severity: high; runaway risk is material and cooling/heat-removal "
                "capacity must be reviewed. The exothermic load is large enough that cooling "
                "duty and upset response are critical, separate from the nominal heat-transfer "
                "capability calculation.")
        if dt_ad >= 20:
            return ("Thermal severity: moderate; exothermic load is manageable but must be "
                    "checked against cooling capacity. Separate the thermal severity from the "
                    "heat-transfer capability calculation for the final design review.")
        return ("Thermal severity: low; the exothermic profile is modest and heat-transfer "
                "capability is likely adequate, though a heat balance should still be checked.")

    if dt_ad >= 50:
        return ("Thermal severity: significant endothermic demand; review heat input and temperature "
                "stability, not just the cooling duty. Heat-transfer capability is distinct from "
                "the required heating capacity, and an endothermic process may need extra heat input "
                "to avoid temperature collapse.")
    if dt_ad >= 20:
        return ("Thermal severity: moderate endothermic load; confirm heat input and circulation "
                "capacity. This is separate from heat-transfer capability: the key question is "
                "whether the system can supply enough heat to maintain temperature.")
    return ("Thermal severity: low; endothermic loading is modest and heat-transfer capability "
            "is likely adequate, although the heating system should still be reviewed for duty.")


# ---------------------------------------------------------------------------
# Reactor-specific Damköhler bands
# ---------------------------------------------------------------------------
def regime_label(da: float) -> str:
    """Traffic-light regime for a single Damköhler number (0 = not evaluated)."""
    if da <= 0:
        return "—"
    if da < 0.1:
        return "🟢 Mixing-insensitive"
    if da < 1.0:
        return "🟡 Transitional"
    return "🔴 Mixing-limited"


def mass_transfer_screen(paths: list[tuple[str, float]], t_rxn: float) -> list[dict]:
    """Preliminary kLa capacity vs kinetic demand (1/t_rxn) per transfer path.

    A full mass-transfer demand still needs solubility, driving-force and
    phase-composition data; this only flags paths worth checking.
    """
    demand_rate = 1.0 / t_rxn if t_rxn > 0 else 0.0
    rows = []
    for path, kla_value in paths:
        ratio = kla_value / demand_rate if demand_rate > 0 else 0.0
        if kla_value <= 0:
            screening = "Unknown — kLa unavailable"
        elif ratio < 1.0:
            screening = "Potentially transfer-limited"
        elif ratio < 10.0:
            screening = "Capacity comparable to demand"
        else:
            screening = "Capacity exceeds kinetic demand"
        rows.append({"Transfer path": path, "kLa (1/s)": f"{kla_value:.3g}",
                     "Demand 1/t_rxn (1/s)": f"{demand_rate:.3g}",
                     "Capacity / demand": f"{ratio:.3g}", "Screening": screening})
    return rows


def correlation_applicability(hydro: dict, geometry, row, v_l: float,
                              gas_on: bool, solids_on: bool) -> str:
    """Markdown summary of applicability checks for the stirred-tank correlations.

    ``geometry`` is a :class:`core.records.VesselGeometry`; ``row`` is the reactor
    database row (baffles, impeller clearance and count are read from it).
    """
    def _num(value, default=0.0) -> float:
        try:
            f = float(value)
            return default if np.isnan(f) else f
        except (TypeError, ValueError):
            return default

    checks, warnings = [], []
    reynolds = _num(hydro.get("Re"))
    if reynolds <= 0:
        warnings.append("Reynolds regime unavailable")
    elif reynolds < 10:
        warnings.append(f"laminar regime (Re = {reynolds:.3g}); turbulent correlations are not applicable")
    elif reynolds < 1e4:
        warnings.append(f"transitional regime (Re = {reynolds:.3g}); correlation uncertainty is elevated")
    else:
        checks.append(f"turbulent regime (Re = {reynolds:,.0f})")

    tank_d, imp_d = geometry.D_tank, geometry.D_imp
    d_ratio = imp_d / tank_d if tank_d > 0 else 0.0
    if 0.2 <= d_ratio <= 0.7:
        checks.append(f"impeller/tank diameter ratio = {d_ratio:.3f}")
    else:
        warnings.append(f"impeller/tank diameter ratio = {d_ratio:.3f} is outside the typical 0.2–0.7 range")

    submergence = geometry.liquid_height(v_l) / imp_d if imp_d > 0 else 0.0
    if submergence >= 1.0:
        checks.append(f"liquid height/impeller diameter = {submergence:.2f}")
    else:
        warnings.append(f"liquid height/impeller diameter = {submergence:.2f}; impeller submergence is limited")

    baffles = str(row.get("baffles", "") or "").strip()
    if baffles:
        checks.append(f"baffling recorded ({baffles})")
    else:
        warnings.append("baffling is not recorded; confirm the vessel configuration")

    clearance = _num(row.get("imp1_clearance_m"))
    if clearance > 0:
        checks.append(f"impeller clearance/tank diameter = {clearance / tank_d if tank_d > 0 else 0.0:.3f}")
    else:
        warnings.append("impeller clearance is not recorded")

    impeller_count = _num(row.get("impeller_count"), 1.0)
    if impeller_count > 1:
        warnings.append(f"multiple impellers ({impeller_count:.0f}); single-impeller correlations need review")
    else:
        checks.append("single impeller")

    warnings.append("Newtonian-fluid assumption applies; non-Newtonian rheology requires a dedicated correlation")
    checks.append("gas loading included" if gas_on else "no gas loading")
    checks.append("solids loading enabled; verify particle-concentration range" if solids_on
                  else "no solids loading")

    lines = ["**Correlation applicability:** " + "; ".join(checks) + "."]
    if warnings:
        lines.append("**Review required:** " + "; ".join(warnings) + ".")
    return "\n\n".join(lines)


def da_band(da: float) -> str:
    if da >= 1.0:
        return "mixing-limited"
    if da >= 0.1:
        return "transitional"
    return "insensitive"


def da_caption(da: dict | None) -> str:
    if not da:
        return ""
    return (f"**{da['reactor']}** at {da['N_rpm']:.0f} RPM, {da['V_L']:.3g} L, {da['fluid']} — "
            f"Re = {da['Re']:,.0f}, P/V = {da['P_V_W_L']:.3g} W/L, θ₉₅ = {da['t_blend']:.3g} s, "
            f"t_E = {da['t_E']:.3g} s  →  **Da_macro = {da['Da_macro']:.3g}** ({da_band(da['Da_macro'])}), "
            f"**Da_micro = {da['Da_micro']:.3g}** ({da_band(da['Da_micro'])}).")


def da_assessment(da: dict) -> tuple[str, str, bool]:
    """(traffic-light kind, text, micro_likely) from reactor-specific Da numbers."""
    dmi, dma = da["Da_micro"], da["Da_macro"]
    micro_likely = dmi >= 0.1
    worst = max(dmi, dma)
    if worst >= 1.0:
        kind, head = "critical", "**Mixing-limited in this vessel**"
    elif worst >= 0.1:
        kind, head = "warning", "**Transitional in this vessel**"
    else:
        kind, head = "ok", "**Mixing-insensitive in this vessel**"
    parts = [f"{head} - Da_micro = {dmi:.3g} ({da_band(dmi)}), Da_macro = {dma:.3g} ({da_band(dma)})."]
    if dmi >= 0.1:
        parts.append("Micromixing competes with the reaction: hold local ε at the feed point on "
                     "scale-up and keep the feed near the impeller.")
    if dma >= 0.1:
        parts.append("Bulk blending is comparable to the reaction time: blend time grows as "
                     "T^(2/3) at constant P/V, so re-check Da_macro at the next scale.")
    if worst < 0.1:
        parts.append("Both timescales are well below t_rxn; re-run this screen for the "
                     "larger vessel before scale-up.")
    return kind, " ".join(parts), micro_likely


# ---------------------------------------------------------------------------
# Findings / verdict / next-steps builders (faithful to the Streamlit logic)
# ---------------------------------------------------------------------------
def build_findings(b_sensitive, b_mechs, b_done, test_rows, t_rxn, micro_likely,
                   meso_sensitive, competing, is_semi_batch, multiphase, phases,
                   has_enthalpy, heat_limiting, dH_eff, dt_ad, kinetics_known,
                   using_approx=False, dh_estimated=False, da=None):
    findings: list[tuple[str, str, str]] = []
    kpi_phrase = sensitive_kpi_phrase(test_rows)
    rem = remaining_tests(b_done)
    rem_action = (f"complete {fmt_tests(rem)} of the Bourne Protocol" if rem
                  else "re-run the Bourne Protocol decision tree")
    proxy_tag = " (proxy kinetics)" if using_approx else ""
    proxy_note = " Based on proxy kinetics - verify with measured data." if using_approx else ""

    # Bourne pre-screen
    if b_sensitive is True:
        if b_mechs:
            findings.append(("Bourne pre-screen", "🔴 Mixing sensitivity confirmed",
                             f"Experimental pre-screen showed {kpi_phrase} changed with mixing "
                             f"conditions. Controlling scale(s): {', '.join(b_mechs)}."))
        else:
            findings.append(("Bourne pre-screen", "🔴 Mixing sensitivity confirmed",
                             f"Experimental pre-screen showed {kpi_phrase} changed with mixing "
                             f"conditions. Controlling scale not yet identified - {rem_action}."))
    elif b_sensitive is False:
        findings.append(("Bourne pre-screen", "🟢 No sensitivity observed",
                         "Experimental pre-screen showed no mixing sensitivity at lab scale."))
    elif b_done:
        findings.append(("Bourne pre-screen", "⚪ Inconclusive",
                         "Bourne tests were started but Test 1 was not completed - finish "
                         "Test 1 for a direct experimental answer."))
    else:
        findings.append(("Bourne pre-screen", "⚪ Not performed",
                         "Run Bourne Protocol Part 1 for a direct experimental answer."))

    # Kinetics basis - proxy kinetics make every timescale conclusion provisional
    if kinetics_known and using_approx:
        findings.append(("Kinetics basis", "🟡 Approximate (proxy reaction)",
                         "t_rxn comes from a proxy reaction class - the micro-, meso- and "
                         "macromixing conclusions below are provisional. Measure the actual "
                         "kinetics to confirm them."))

    # Micromixing
    if not kinetics_known:
        findings.append(("Micromixing", "⚪ Unknown",
                         "Reaction kinetics not available - micromixing cannot be assessed from "
                         "t_rxn. A Bourne pre-screen (Test 1) gives a direct experimental answer."))
    elif da:
        dmi = da["Da_micro"]
        icon = "🔴 Likely sensitive" if dmi >= 1.0 else ("🟡 Transitional" if dmi >= 0.1 else "🟢 Unlikely")
        findings.append(("Micromixing", icon + proxy_tag,
                         f"Da_micro = {dmi:.3g} in {da['reactor']} ({da['N_rpm']:.0f} RPM, "
                         f"{da['V_L']:.3g} L): t_E = {da['t_E']:.3g} s vs t_rxn = {t_rxn:.4g} s."
                         + proxy_note))
    elif micro_likely:
        findings.append(("Micromixing", "🔴 Likely sensitive",
                         f"t_rxn = {t_rxn:.4g} s - fast enough that local energy dissipation "
                         "controls the mixing rate."))
    elif using_approx:
        findings.append(("Micromixing", "🟡 Unlikely (proxy kinetics)",
                         f"t_rxn = {t_rxn:.4g} s - slow relative to typical micromixing times, "
                         "but this is based on proxy kinetics. Verify with measured data."))
    else:
        findings.append(("Micromixing", "🟢 Unlikely",
                         f"t_rxn = {t_rxn:.4g} s - slow relative to typical micromixing times."))

    # Micro/mesomixing (selectivity)
    if meso_sensitive or is_semi_batch:
        if is_semi_batch and competing == "No":
            findings.append(("Mesomixing (feed-plume)", "🟡 Semi-batch - check experimentally",
                             "No competing reactions, but feed-plume dispersion controls local "
                             "concentration. Vary feed rate and location (Bourne Tests 2 & 3)."))
        else:
            findings.append(("Micro/mesomixing (selectivity)",
                             "🟡 Potentially sensitive" if competing == "Not sure" else "🔴 Likely sensitive",
                             "Competing reactions present - both micromixing (local ε) and "
                             "mesomixing (feed dispersion) may affect selectivity."))
    else:
        findings.append(("Micro/mesomixing (selectivity)", "🟢 Not a factor",
                         "No competing reactions; batch process (no feed addition)."))

    # Macromixing
    if not kinetics_known:
        findings.append(("Macromixing (blend time)", "⚪ Unknown",
                         "Reaction kinetics not available - t_rxn cannot be compared to the "
                         "vessel blend time."))
    elif da:
        dma = da["Da_macro"]
        icon = "🔴 Likely sensitive" if dma >= 1.0 else ("🟡 Transitional" if dma >= 0.1 else "🟢 Unlikely")
        findings.append(("Macromixing (blend time)", icon + proxy_tag,
                         f"Da_macro = {dma:.3g} in {da['reactor']}: θ₉₅ = {da['t_blend']:.3g} s vs "
                         f"t_rxn = {t_rxn:.4g} s. Blend time grows ~T^(2/3) at constant P/V - "
                         "re-check at the next scale." + proxy_note))
    elif t_rxn < 60:
        findings.append(("Macromixing (blend time)", "🟡 Check at scale",
                         f"t_rxn = {t_rxn:.4g} s is within the range of blend times in larger "
                         "vessels (10–120 s). Compute Da_macro for your reactor."))
    elif using_approx:
        findings.append(("Macromixing (blend time)", "🟡 Unlikely (proxy kinetics)",
                         f"t_rxn = {t_rxn:.4g} s is much longer than typical blend times, but "
                         "this is based on proxy kinetics. Verify with measured data."))
    else:
        findings.append(("Macromixing (blend time)", "🟢 Unlikely",
                         f"t_rxn = {t_rxn:.4g} s is much longer than typical blend times."))

    # Mass transfer
    if multiphase:
        findings.append((f"Mass transfer ({' + '.join(phases)})", "🟡 System-dependent",
                         "Multi-phase system - interphase transport may limit the observed rate. "
                         "Characterise gas–liquid kLa and liquid–solid transport, including "
                         "dissolution, adsorption, or desorption, for each reactor."))
    else:
        phase_lbl = phases[0] if phases else "Liquid"
        findings.append(("Mass transfer", "🟢 Not applicable",
                         f"Single phase ({phase_lbl}) - no interphase transport."))

    # Heat transfer
    if has_enthalpy and heat_limiting:
        detail = f"|ΔH| = {abs(dH_eff):.1f} kJ/mol"
        if dt_ad is not None:
            detail += f", ΔT_ad ≈ {dt_ad:.0f} K"
        duty = "cooling" if dH_eff < 0 else "heating"
        status = ("🔴 Likely heat-transfer-limited (estimated ΔH)" if dh_estimated
              else "🔴 Likely heat-transfer-limited")
        note = " ΔH is estimated - confirm it by reaction calorimetry." if dh_estimated else ""
        findings.append(("Heat transfer", status,
                         f"{detail} - run a heat balance to confirm adequate {duty} capacity.{note}"))
    elif has_enthalpy and not heat_limiting and dh_estimated:
        detail = f"|ΔH| = {abs(dH_eff):.1f} kJ/mol"
        if dt_ad is not None:
            detail += f", ΔT_ad ≈ {dt_ad:.0f} K"
        findings.append(("Heat transfer", "🟡 Manageable (estimated ΔH)",
                         f"{detail} - modest thermal load, but the ΔH is estimated. Measure it "
                         "by reaction calorimetry to confirm."))
    elif has_enthalpy and not heat_limiting:
        detail = f"|ΔH| = {abs(dH_eff):.1f} kJ/mol"
        if dt_ad is not None:
            detail += f", ΔT_ad ≈ {dt_ad:.0f} K"
        findings.append(("Heat transfer", "🟢 Manageable",
                         f"{detail} - modest thermal load, unlikely to be limiting in most "
                         "configurations."))
    else:
        findings.append(("Heat transfer", "⚪ Unknown",
                         "No ΔH data available - measure ΔH by reaction calorimetry (RC1 / µRC)."))

    # Semi-batch
    if is_semi_batch:
        findings.append(("Semi-batch (fed-batch)", "🟡 Feed-point sensitive",
                         "Mesomixing (feed-plume dispersion) controls local concentration, heat "
                         "release and supersaturation at the feed point."))
    return findings


def build_verdict(b_sensitive, b_mechs, b_done, findings, competing):
    mech_findings = [f for f in findings if f[0] != "Bourne pre-screen"]
    n_red = sum(1 for _, s, _ in mech_findings if "🔴" in s)
    n_yellow = sum(1 for _, s, _ in mech_findings if "🟡" in s)
    n_unknown = sum(1 for _, s, _ in mech_findings if "⚪" in s)
    red_mechs = [m for m, s, _ in mech_findings if "🔴" in s]
    rem = remaining_tests(b_done)
    rem_action = (f"complete {fmt_tests(rem)} of the Bourne Protocol" if rem
                  else "re-run the Bourne Protocol decision tree")

    if b_sensitive is True:
        if b_mechs:
            return (f"🔴 **Mixing sensitivity confirmed** - the Bourne Protocol identified "
                    f"**{join_mechs(b_mechs)}** as the controlling scale(s). Focus scale-up "
                    "efforts on this mechanism (see recommendations below)."), "critical"
        if red_mechs:
            return (f"🔴 **Mixing sensitivity confirmed** - the reaction may be "
                    f"**{join_mechs(red_mechs)} limited**, and the Bourne pre-screen confirms a "
                    "sensitivity is present. Characterise the reaction in detail to identify "
                    "the controlling mechanism."), "critical"
        if n_yellow >= 1:
            return ("🔴 **Mixing sensitivity confirmed** - the Bourne pre-screen shows a "
                    "sensitivity is present. The theory did not flag a specific mechanism as "
                    f"likely, but some items require verification at scale. To pinpoint the "
                    f"controlling scale, {rem_action}."), "critical"
        return ("🔴 **Mixing sensitivity confirmed** - the Bourne pre-screen shows an experimental "
                "sensitivity even though the theory flagged no mechanism. Revisit the inputs "
                f"(kinetics, phases, feed strategy) and {rem_action}."), "critical"

    if b_sensitive is False:
        if n_unknown >= 1:
            return (f"🟡 **Incomplete assessment** - {n_unknown} item(s) could not be evaluated "
                    "(e.g. missing kinetics or ΔH), so a low-risk verdict cannot be confirmed. "
                    "Resolve the unknowns or run a Bourne pre-screen for a direct experimental "
                    "answer."), "warning"
        if red_mechs:
            return (f"🟡 **Possible scale-dependent sensitivity** - the Bourne pre-screen showed "
                    f"no sensitivity at lab scale, but the assessment flags **{join_mechs(red_mechs)}** "
                    "as likely to become limiting at larger scale. Confirm with Damköhler analysis "
                    "before scale-up."), "warning"
        if n_yellow >= 1:
            return ("🟢 **Low mixing sensitivity risk** - the Bourne pre-screen showed no "
                    "sensitivity and no mechanism is flagged as likely, though a few items warrant "
                    "a check at scale."), "ok"
        return ("🟢 **Low mixing sensitivity risk** - the Bourne pre-screen showed no sensitivity "
                "and no mixing mechanism is expected to limit this reaction."), "ok"

    # Bourne not performed - theory only
    if n_red >= 2:
        return (f"🔴 **High mixing sensitivity risk** - multiple mechanisms "
                f"(**{join_mechs(red_mechs)}**) are likely to limit this reaction at scale. "
                "Characterise them in detail and run a Bourne pre-screen for direct "
                "experimental confirmation."), "critical"
    if n_red == 1:
        return (f"🟡 **Moderate mixing sensitivity risk** - **{join_mechs(red_mechs)}** is likely "
                "to be sensitive. Investigate this mechanism and run a Bourne pre-screen to "
                "confirm whether a sensitivity is present experimentally."), "warning"
    if n_unknown >= 1:
        return (f"🟡 **Incomplete assessment** - {n_unknown} item(s) could not be evaluated "
                "(e.g. missing kinetics or ΔH), so a low-risk verdict cannot be confirmed. "
                "Resolve the unknowns or run a Bourne pre-screen for a direct experimental "
                "answer."), "warning"
    if n_yellow >= 1:
        return ("🟡 **Low-to-moderate mixing sensitivity risk** - no mechanisms are flagged as "
                "likely sensitive, but some require verification at scale. Run a Bourne "
                "pre-screen for a direct experimental answer."), "warning"
    return ("🟢 **Low mixing sensitivity risk** - no mixing mechanisms are expected to limit this "
            "reaction under typical operating conditions."), "ok"


def build_next_steps(b_sensitive, b_mechs, using_approx, micro_likely, t_rxn,
                     meso_sensitive, multiphase, has_enthalpy, heat_limiting, is_semi_batch,
                     kinetics_known, kinetics_declined, dh_estimated=False):
    steps: list[dict] = []
    if b_sensitive is None:
        steps.append({"Area": "Bourne pre-screen",
                      "Recommended action": "Run Bourne Protocol Part 1 (quick screen) to confirm "
                      "whether mixing sensitivity exists experimentally."})
    if b_sensitive is True and b_mechs:
        mech_actions = {
            "Micromixing": "Hold local ε (P/V) constant on scale-up and keep the feed point near "
                           "the impeller; confirm with Da_micro on the Vessel Assessment page.",
            "Mesomixing": "Control feed-plume dispersion: hold local ε constant, cut feed rate, "
                          "extend addition time, and/or add feed points.",
            "Macromixing": "Reduce bulk blend time: high-efficiency / multiple impellers, optimise "
                           "baffling, or use in-line / static mixers.",
        }
        for m in b_mechs:
            if m in mech_actions:
                steps.append({"Area": f"{m} (Bourne-confirmed)", "Recommended action": mech_actions[m]})
    if using_approx:
        steps.append({"Area": "Kinetics",
                      "Recommended action": "Measure actual kinetics to replace the approximate values."})
    if kinetics_declined:
        steps.append({"Area": "Kinetics",
                      "Recommended action": "Measure the reaction kinetics (e.g. reaction "
                      "calorimetry / in-situ monitoring) and add them to the database to enable "
                      "the Damköhler-based mixing assessment."})
    if kinetics_known and (micro_likely or t_rxn < 60):
        steps.append({"Area": "Damköhler analysis",
                      "Recommended action": "Compute Da_macro / Da_micro for your reactor on the "
                      "Vessel Assessment page."})
    if meso_sensitive:
        steps.append({"Area": "Micro/mesomixing",
                      "Recommended action": "Run the Bourne Protocol to screen micro/meso effects."})
    if multiphase:
        steps.append({"Area": "Mass transfer",
                      "Recommended action": "Assess Da_GL / Da_SL on the Vessel Assessment page."})
    if has_enthalpy and heat_limiting:
        steps.append({"Area": "Heat transfer",
                      "Recommended action": "Run a heat balance (Vessel Assessment) to quantify "
                      "Q_gen vs Q_cool."})
    if has_enthalpy and dh_estimated:
        steps.append({"Area": "Heat of reaction",
                      "Recommended action": "Measure ΔH by reaction calorimetry (RC1 / µRC) to "
                      "replace the estimated value used in this screening."})
    if is_semi_batch:
        steps.append({"Area": "Semi-batch",
                      "Recommended action": "Run the full Bourne Protocol: vary impeller speed, "
                      "feed rate/time, and feed location."})
    if not steps:
        steps.append({"Area": "General",
                      "Recommended action": "Low risk; standard scale-up practices are sufficient."})
    return steps


# ---------------------------------------------------------------------------
# Bourne Protocol decision tree
# ---------------------------------------------------------------------------
MECH_CONCLUSION = {
    "Mixing-insensitive": (
        "**🟢 Dominant regime: mixing is NOT rate-limiting.** Scale up on geometric "
        "similarity; no special mixing constraints."),
    "Micromixing": (
        "**🔬 Dominant regime: MICROMIXING.** Scale-up rule: **hold local ε constant** "
        "(match P/V near the feed) — the reaction competes with engulfment-scale mixing."),
    "Mesomixing": (
        "**Dominant regime: MESOMIXING.** Scale-up rule: **match P/V, extend feed "
        "time, and add feed points** to control feed-plume dispersion."),
    "Macromixing": (
        "**Dominant regime: MACROMIXING.** Scale-up rule: **keep blend/circulation "
        "times short** — bulk homogeneity governs the outcome."),
}


def bourne_outcome(s1: str | None, s2: str | None, s3: str | None, ratio: float) -> dict:
    """Bourne decision tree from the three test statuses and the Test 1 P/m span.

    A Test 1 "not sensitive" result over an inadequate P/m span (< 100×) is treated
    as inconclusive. A mechanism is only *confirmed* when Test 1 itself was
    sensitive and the intermediate tests were not mixed.
    """
    range_ok = ratio >= 100.0
    s1_eff = "inconclusive" if (s1 == "not_sensitive" and not range_ok) else s1
    confirmed = s1_eff == "sensitive"

    if not s1:
        dominant, next_test = "Incomplete", 1
    elif s1_eff == "not_sensitive":
        dominant, next_test = "Mixing-insensitive", 0
    elif not s2:
        dominant, next_test = "Incomplete", 2
    elif s2 == "not_sensitive":
        dominant, next_test = ("Micromixing" if confirmed else "Inconclusive"), 0
    elif not s3:
        dominant, next_test = "Incomplete", 3
    elif s3 == "sensitive":
        dominant, next_test = "Mesomixing", 0
    elif s3 == "not_sensitive":
        dominant, next_test = "Macromixing", 0
    else:
        dominant, next_test = "Inconclusive", 0

    tentative = (dominant in ("Micromixing", "Mesomixing", "Macromixing")
                 and (not confirmed or s2 == "inconclusive"))
    return {"s1": s1, "s1_eff": s1_eff, "s2": s2, "s3": s3, "ratio": ratio,
            "range_ok": range_ok, "confirmed": confirmed, "dominant": dominant,
            "tentative": tentative, "next_test": next_test}


def bourne_test_lines(o: dict) -> list[str]:
    """Human-readable per-test bullets reflecting the actual statuses."""
    lines = []
    if o["s1"] == "sensitive":
        lines.append("- **Test 1:** sensitive to impeller speed → mixing matters.")
    elif o["s1"] == "inconclusive":
        lines.append("- **Test 1:** mixed KPI response to impeller speed (inconclusive).")
    elif o["s1"] == "not_sensitive" and not o["range_ok"]:
        lines.append(f"- **Test 1:** no response, but only a {o['ratio']:.1f}× P/m span was "
                     "achieved (100× intended) — treated as inconclusive.")
    elif o["s1"] == "not_sensitive":
        lines.append("- **Test 1:** response insensitive to impeller speed.")
    if o["s2"]:
        lines.append({"sensitive": "- **Test 2:** sensitive to feed rate.",
                      "not_sensitive": "- **Test 2:** insensitive to feed rate.",
                      }.get(o["s2"], "- **Test 2:** mixed response to feed rate (inconclusive)."))
    if o["s3"]:
        lines.append({"sensitive": "- **Test 3:** sensitive to feed location.",
                      "not_sensitive": "- **Test 3:** insensitive to feed location.",
                      }.get(o["s3"], "- **Test 3:** mixed response to feed location (inconclusive)."))
    return lines


# ---------------------------------------------------------------------------
# Reaction Sensitivity Protocol — full step-by-step assessment
# ---------------------------------------------------------------------------
@dataclass
class ProtocolInputs:
    """User answers for the Reaction Sensitivity Protocol, as plain values.

    ``bourne``: "skip" | "confirmed" | "insensitive" | "inconclusive".
    ``kinetics``: "available" | "approximate" | "declined".
    ``dh_action`` (used only when no ΔH is known): "estimate" | "calorimetry" | "".
    """
    order: str
    k: float
    C0: float
    t_specified: float
    dH: float
    rxn_type: str = ""
    kinetics: str = "available"
    bourne: str = "skip"
    bourne_mech: str = ""
    bourne_tests_done: list[int] = field(default_factory=list)
    bourne_rows: list[dict] = field(default_factory=list)
    semi_batch: bool = False
    phases: list[str] = field(default_factory=lambda: ["Liquid"])
    competing: str = ""
    dh_override: float = 0.0
    dh_override_measured: bool = False
    dh_action: str = ""
    dh_ref_value: float = 0.0
    c0_heat: float = 1.0
    rho_cp: float = 1800.0


def bourne_prescreen(status: str, mech: str, done: list[int]):
    """(sensitive True/False/None, confirmed mechanisms, completed tests) from the pre-screen."""
    done = sorted(done)
    if status == "confirmed":
        return True, ([mech] if mech in ("Micromixing", "Mesomixing", "Macromixing") else []), done
    if status == "insensitive":
        return False, [], done
    if status == "inconclusive":
        return None, [], done
    return None, [], []


def _kinetics_text(order: str, t_rxn: float, t_90: float, t_basis: str) -> str:
    n_sym = "k'" if order.startswith("pseudo") else "k"
    conc = {"0": "", "1": "·C", "2": "·C²"}.get(order.split("-")[-1] if order else "1", f"·C^{order}")
    law = f"−dC/dt = {n_sym}{conc}"
    if t_rxn <= 0:
        return ("⚠️ Cannot determine a characteristic reaction time - "
                "check k, C₀ and t_rxn in the Reaction Database.")
    return (
        f"**Kinetic model** (order {order}): {law}\n\n"
        f"Characteristic reaction time **t_rxn = {t_rxn:.4g} s** ({t_basis}). This is the "
        "initial-rate time constant used in every Damköhler comparison below — the shortest "
        "(most conservative) estimate for mixing sensitivity."
        + (f" For process-window planning, 90% conversion takes about **{t_90:.4g} s**; "
           "that longer figure is *not* used for the Damköhler screen."
           if t_90 != t_rxn else ""))


def assess_protocol(inp: ProtocolInputs,
                    damkohler_for: Callable[[float], dict | None] | None = None) -> dict:
    """Run every step of the Reaction Sensitivity Protocol.

    ``damkohler_for(t_rxn)`` optionally returns reactor-specific Da numbers (see
    ``da_caption``) for Step 5. Returns the per-step assessment texts, captions,
    findings, verdict, next steps, ``ready`` and the values cached for the PDF.
    """
    out: dict = {}

    # ---- Step 0: Bourne pre-screen -------------------------------------
    b_sensitive, b_mechs, b_done = bourne_prescreen(
        inp.bourne, inp.bourne_mech, inp.bourne_tests_done)
    test_rows = list(inp.bourne_rows)
    if inp.bourne == "skip":
        out["step0"] = amd(
            "caution", "**Bourne pre-screen skipped** - proceeding with the theoretical "
            "assessment. Running the Bourne Protocol gives a direct experimental answer.")
    elif b_sensitive is True:
        if b_mechs:
            out["step0"] = amd(
                "critical", f"Bourne Protocol confirmed **mixing sensitivity** - the "
                f"controlling scale is **{b_mechs[0].lower()}**. Carried into the summary "
                "as an experimentally confirmed result.")
        else:
            rem = remaining_tests(b_done)
            add = (f" Complete **{fmt_tests(rem)}** ({fmt_test_purposes(rem)}) to pinpoint "
                   "the controlling scale." if rem else "")
            out["step0"] = amd(
                "critical", "Bourne Protocol confirmed **mixing sensitivity**, but the "
                "controlling scale is not yet resolved." + add)
    elif b_sensitive is False:
        out["step0"] = amd(
            "ok", "Bourne Protocol showed **no mixing sensitivity** at lab scale (Test 1 "
            "response insensitive to impeller speed). The remaining steps check for latent "
            "risks at larger scale.")
    else:
        out["step0"] = amd(
            "caution", "Bourne results **inconclusive** - Test 1 was not completed, so "
            "experimental mixing sensitivity is undetermined. Complete at least Test 1.")

    # ---- Step 1: kinetics ----------------------------------------------
    order = inp.order or "1"
    t_rxn, t_90, t_basis = characteristic_reaction_time(order, inp.k, inp.C0, inp.t_specified)
    using_approx = inp.kinetics == "approximate"
    kinetics_declined = inp.kinetics == "declined"
    kinetics_known = (t_rxn > 0) and not kinetics_declined
    kinetics_resolved = kinetics_known or kinetics_declined
    out["kinetics_md"] = _kinetics_text(order, t_rxn, t_90, t_basis)
    if kinetics_declined:
        out["step1"] = amd(
            "warning", "**Kinetics not yet available.** Measure them (e.g. by calorimetry / "
            "reaction monitoring), add the reaction to the database, and return here. A "
            "Bourne pre-screen can still give a direct experimental answer in the meantime.")
    elif not kinetics_known:
        out["step1"] = amd(
            "critical", "Cannot determine a characteristic reaction time from the selected "
            "reaction data.")
    elif using_approx:
        out["step1"] = amd(
            "warning", "**Approximate kinetics** - t_rxn is based on a proxy reaction. All "
            "downstream conclusions are only valid if the proxy kinetics match the true "
            "reaction. Confirm with measured data.")
    else:
        out["step1"] = amd("ok", "**Kinetics available** - characteristic reaction "
                           "time shown above.")
    is_semi_batch = inp.semi_batch

    # ---- Step 2: phases -------------------------------------------------
    phases = list(inp.phases or [])
    multiphase = len(phases) > 1
    if not phases:
        out["step2"] = amd("caution", "Select at least one phase to continue.")
    elif multiphase:
        out["step2"] = amd(
            "warning", "**Multi-phase system** (" + " + ".join(phases) + ") - interphase mass "
            "transfer may limit the observed rate. Characterise kLa (gas–liquid) and/or "
            "solid–liquid transport, including dissolution, adsorption, or desorption, "
            "and compute Da_GL / Da_SL for your reactor on the Vessel Assessment page.")
    elif phases == ["Liquid"]:
        out["step2"] = amd(
            "ok", "**Single liquid phase** - interphase mass transfer is not a factor. Micro-, "
            "meso- and macromixing may still affect the reaction.")
    else:
        out["step2"] = amd(
            "caution", f"**Single phase selected ({phases[0]})** - a lone "
            f"{phases[0].lower()} phase has no interphase transport, but check that the "
            "liquid phase is not missing from the selection.")

    # ---- Step 3: competing reactions -----------------------------------
    competing = inp.competing
    competing_set = competing in ("Yes", "No", "Not sure")
    meso_sensitive, require_feed_zone = mesomixing_risk(competing, is_semi_batch)
    if not competing_set:
        out["step3"] = amd("caution", "Select an option to continue.")
    elif competing == "Yes":
        out["step3"] = amd(
            "critical", "**Competing reactions present** - both micromixing (local ε) and "
            "mesomixing (feed dispersion) can shift selectivity; likely mixing-sensitive.")
    elif competing == "Not sure":
        out["step3"] = amd(
            "warning", "Treat as **potentially sensitive** until confirmed - a Bourne Protocol "
            "screen resolves whether micro/mesomixing affects selectivity.")
    elif require_feed_zone:
        out["step3"] = amd(
            "warning", "No competing reactions, but this is a **semi-batch** process - "
            "run a feed-zone assessment (feed rate/time and location) before assuming "
            "mesomixing is controlling.")
    else:
        out["step3"] = amd(
            "ok", "**No competing reactions** in a batch process - micro/mesomixing unlikely "
            "to affect selectivity.")

    # ---- Step 4: heat transfer -----------------------------------------
    dh_from_override = inp.dh_override != 0.0
    has_enthalpy = inp.dH != 0.0 or dh_from_override
    dH_eff = inp.dh_override if dh_from_override else inp.dH
    out["show_dh_action"] = not has_enthalpy
    heat_resolved = True
    dt_ad = None
    if not has_enthalpy:
        if inp.dh_action == "estimate":
            dH_eff = inp.dh_ref_value
            has_enthalpy = dH_eff != 0.0
        elif inp.dh_action != "calorimetry":
            heat_resolved = False

    # An override is measured only if declared so; otherwise ΔH inherits the
    # kinetics basis (proxy kinetics ==> proxy ΔH).
    if dh_from_override:
        dh_estimated = not inp.dh_override_measured
    elif inp.dH == 0.0 and inp.dh_action == "estimate":
        dh_estimated = True
    else:
        dh_estimated = using_approx

    abs_dH = abs(dH_eff)
    heat_limiting = False
    heat_flagged_type = any(t in inp.rxn_type.lower() for t in KNOWN_HOT)
    if has_enthalpy:
        if inp.c0_heat > 0 and inp.rho_cp > 0:
            dt_ad = abs_dH * inp.c0_heat * 1000.0 / inp.rho_cp
        heat_flag = abs_dH >= 50 or (dt_ad is not None and dt_ad >= 50)
        heat_limiting = heat_flag or heat_flagged_type
        sign = "exothermic" if dH_eff < 0 else "endothermic"
        if abs_dH >= 100:
            intensity, heat_kind = "Highly", "critical"
        elif abs_dH >= 50:
            intensity, heat_kind = "Moderately", "warning"
        elif abs_dH >= 20:
            intensity, heat_kind = "Mildly", "caution"
        else:
            intensity, heat_kind = "Weakly", "ok"
        parts = [f"**{intensity} {sign}** reaction - |ΔH| = {abs_dH:.1f} kJ/mol"]
        if dt_ad is not None:
            drop = " (adiabatic temperature drop)" if dH_eff > 0 else ""
            parts.append(f"ΔT_ad ≈ {dt_ad:.0f} K{drop}")
        msg = ", ".join(parts) + "."
        if heat_flag:
            duty = "cooling" if dH_eff < 0 else "heating"
            msg += (" Heat transfer is **likely limiting** - run a heat balance (Vessel "
                    f"Assessment) to confirm adequate {duty} capacity (Q_rxn vs Q_jacket).")
        if heat_flagged_type:
            msg += (f" Reaction type **{inp.rxn_type}** is commonly strongly exothermic - heat "
                    "assessment recommended regardless of the reported ΔH.")
        if dh_estimated:
            msg += (" The ΔH used here is **estimated** (proxy/similar reaction) - measure it "
                    "by reaction calorimetry to confirm this screening.")
        out["step4"] = amd("critical" if heat_limiting else heat_kind, msg)
        out["dt_ad_caption"] = (
            f"ΔT_ad = |ΔH|·C₀·1000/(ρ·Cp) ≈ **{dt_ad:.0f} K**  -  "
            f"{heat_transfer_summary(abs_dH, dt_ad, dH_eff=dH_eff)}"
            if dt_ad is not None else "Enter C₀ and ρ·Cp above to estimate ΔT_ad.")
    else:
        if inp.dh_action == "calorimetry":
            out["step4"] = amd(
                "caution", "Heat-transfer limitation **cannot be evaluated without ΔH** - measure it "
                "by reaction calorimetry (RC1 / µRC), add it to the Reaction Database, and "
                "return here.")
        elif not heat_resolved:
            out["step4"] = amd(
                "unknown", "No ΔH data for this reaction - choose how to proceed above "
                "(measure by calorimetry, or estimate from a similar reaction).")
        else:
            out["step4"] = amd("unknown", "No ΔH data available - measure ΔH by reaction calorimetry.")
        out["dt_ad_caption"] = ""

    # ---- Step 5: mixing time vs reaction time --------------------------
    da = damkohler_for(t_rxn) if (damkohler_for and kinetics_known and t_rxn > 0) else None
    out["da_caption"] = da_caption(da)
    if kinetics_known and t_rxn > 0:
        out["trxn_caption"] = f"Your reaction time: **t_rxn = {t_rxn:.4g} s**."
        if da:
            kind, text, micro_likely = da_assessment(da)
            out["step5"] = amd(kind, text)
        elif t_rxn < 0.1:
            out["step5"] = amd(
                "critical", "**Very fast reaction** - micromixing-sensitive in most reactor "
                "configurations. Local turbulent energy dissipation near the impeller, feed "
                "location, and tip speed are critical. " + damkohler_screening_note(t_rxn))
            micro_likely = True
        elif t_rxn < 1.0:
            out["step5"] = amd(
                "warning", "**Fast reaction** - micromixing likely relevant in larger vessels "
                "where local ε at the feed point decreases. Confirm with Damköhler analysis. "
                + damkohler_screening_note(t_rxn))
            micro_likely = True
        elif t_rxn < 10:
            out["step5"] = amd(
                "caution", "**Moderate reaction** - micromixing less likely to dominate, but "
                "macromixing (blend time) could matter in larger vessels. Check blend time vs "
                "t_rxn. " + damkohler_screening_note(t_rxn))
            micro_likely = False
        else:
            out["step5"] = amd(
                "ok", "**Slow reaction** - mixing is unlikely to limit the reaction in "
                "well-agitated vessels. " + damkohler_screening_note(t_rxn))
            micro_likely = False
    else:
        out["trxn_caption"] = ""
        out["step5"] = (amd(
            "unknown", "Reaction kinetics not available - the mixing-time vs reaction-time "
            "comparison cannot be evaluated. A Bourne pre-screen (Test 1) gives a direct "
            "experimental answer.") if kinetics_declined else "")
        micro_likely = False

    # ---- Step 6: findings, verdict, next steps -------------------------
    findings = build_findings(
        b_sensitive, b_mechs, b_done, test_rows, t_rxn, micro_likely,
        meso_sensitive, competing, is_semi_batch, multiphase, phases,
        has_enthalpy, heat_limiting, dH_eff, dt_ad, kinetics_known, using_approx,
        dh_estimated, da)
    verdict, verdict_kind = build_verdict(b_sensitive, b_mechs, b_done, findings, competing)
    next_steps = build_next_steps(
        b_sensitive, b_mechs, using_approx, micro_likely, t_rxn, meso_sensitive,
        multiphase, has_enthalpy, heat_limiting, is_semi_batch, kinetics_known,
        kinetics_declined, dh_estimated)

    ready = bool(kinetics_resolved and phases and competing_set and heat_resolved)
    out.update({
        "ready": ready, "findings": findings, "next_steps": next_steps,
        "verdict": verdict, "verdict_kind": verdict_kind,
        "summary_note": "" if ready else (
            "*Complete Steps 1–4 - select a reaction with kinetics, at least one phase, "
            "whether competing reactions are present, and resolve ΔH - to see the overall "
            "verdict.*"),
        # values carried into the PDF snapshot
        "t_rxn": t_rxn, "dH_eff": dH_eff, "dt_ad": dt_ad, "phases": phases,
        "bourne_rows": test_rows, "b_sensitive": b_sensitive, "b_mechs": b_mechs,
        "competing_set": competing_set, "using_approx": using_approx,
        "dh_estimated": dh_estimated, "is_semi_batch": is_semi_batch, "da": da,
    })
    return out
