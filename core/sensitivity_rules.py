"""Mixing-sensitivity decision rules: the Reaction Sensitivity Protocol findings,
verdict and next steps, Damköhler bands, and the Bourne Protocol decision tree.

Every function is a pure function of its arguments (no GUI state). The protocol
returns structured objects (:mod:`core.messages`); ``protocol_md`` renders them
to the Markdown the web page and PDF report display.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable

import numpy as np

from core.messages import Action, Finding, Message
from core.options import BourneStatus, Competing, DhAction, Kinetics, Mechanism, Phase
from utils.bourne_kpi import SENS_THRESHOLD, kpi_prefix, threshold_phrase
from utils.calculations import characteristic_reaction_time

TEST_PURPOSE = {1: "impeller speed", 2: "feed rate/time", 3: "feed location"}

KNOWN_HOT = ["grignard", "nitration", "sulfonation", "diazotization",
             "polymerization", "hydrogenation", "oxidation"]


# ---------------------------------------------------------------------------
# Text helpers
# ---------------------------------------------------------------------------
def amd(kind: str, text: str) -> str:
    """Traffic-light assessment line: emoji + markdown text."""
    return Message(kind, text).md()


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
    meso_sensitive = competing in (Competing.YES, Competing.NOT_SURE)
    require_feed_zone = is_semi_batch and not meso_sensitive
    return meso_sensitive, require_feed_zone


def damkohler_screening_note(t_rxn: float) -> str:
    """Return the preliminary screening note for reaction-time heuristics.

    The legacy time bands are retained as a quick screen only; the engineering
    decision should be confirmed with reactor-specific Damköhler numbers.
    """
    if not np.isfinite(t_rxn) or t_rxn <= 0:
        return ("No reaction time, so this is qualitative only. Compute Da on the Vessel "
                "Assessment page.")
    return ("This is a rough screen - confirm with Da_macro / Da_micro for a vessel "
            "(below, or on the Vessel Assessment page).")


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
            return f"Low thermal severity (mild, {sign}). A routine heat balance is enough."
        if mag < 50:
            return f"Moderate thermal severity ({sign}). Confirm the duty with a heat balance."
        return f"High thermal severity ({sign}). Review heat removal / input in detail."

    if sign == "exothermic":
        if dt_ad >= 200:
            return ("Very high thermal severity - significant runaway potential. Review cooling "
                    "capacity and emergency relief / quench.")
        if dt_ad >= 50:
            return ("High thermal severity - material runaway risk. Review cooling capacity and "
                    "upset response.")
        if dt_ad >= 20:
            return "Moderate thermal severity. Check the heat load against cooling capacity."
        return "Low thermal severity. Cooling is likely adequate; confirm with a heat balance."

    if dt_ad >= 50:
        return "Significant heating demand. Check the heat input can hold the temperature."
    if dt_ad >= 20:
        return "Moderate heating demand. Confirm the heat input capacity."
    return "Low thermal severity. Heating is likely adequate."


# ---------------------------------------------------------------------------
# Reactor-specific Damköhler bands
# ---------------------------------------------------------------------------
def regime(da: float) -> tuple[str, str]:
    """(kind, label) regime for a single Damköhler number (0 = not evaluated)."""
    if da <= 0:
        return "unknown", "Not evaluated"
    if da < 0.1:
        return "ok", "Mixing-insensitive"
    if da < 1.0:
        return "warning", "Transitional"
    return "critical", "Mixing-limited"


def regime_label(da: float) -> str:
    """Traffic-light regime label for display."""
    if da <= 0:
        return "—"
    kind, label = regime(da)
    return Message(kind, label).md()


def mass_transfer_data(paths: list[tuple[str, float]], t_rxn: float) -> list[dict]:
    """Preliminary kLa capacity vs kinetic demand (1/t_rxn) per transfer path.

    A full mass-transfer demand still needs solubility, driving-force and
    phase-composition data; this only flags paths worth checking. ``screening``
    is a code: unknown | limited | comparable | exceeds.
    """
    demand_rate = 1.0 / t_rxn if t_rxn > 0 else 0.0
    rows = []
    for path, kla_value in paths:
        ratio = kla_value / demand_rate if demand_rate > 0 else 0.0
        if kla_value <= 0:
            screening = "unknown"
        elif ratio < 1.0:
            screening = "limited"
        elif ratio < 10.0:
            screening = "comparable"
        else:
            screening = "exceeds"
        rows.append({"path": path, "kLa": kla_value, "demand": demand_rate, "ratio": ratio,
                     "screening": screening})
    return rows


MT_SCREENING_LABELS = {
    "unknown": "Unknown — kLa unavailable", "limited": "Potentially transfer-limited",
    "comparable": "Capacity comparable to demand", "exceeds": "Capacity exceeds kinetic demand",
}


def mass_transfer_screen(paths: list[tuple[str, float]], t_rxn: float) -> list[dict]:
    """Display table of :func:`mass_transfer_data`."""
    return [{"Transfer path": d["path"], "kLa (1/s)": f"{d['kLa']:.3g}",
             "Demand 1/t_rxn (1/s)": f"{d['demand']:.3g}",
             "Capacity / demand": f"{d['ratio']:.3g}",
             "Screening": MT_SCREENING_LABELS[d["screening"]]}
            for d in mass_transfer_data(paths, t_rxn)]


def correlation_applicability(hydro: dict, geometry, row, v_l: float,
                              gas_on: bool, solids_on: bool) -> str:
    """Markdown summary of :func:`applicability_checks`."""
    res = applicability_checks(hydro, geometry, row, v_l, gas_on, solids_on)
    lines = ["**Correlation applicability:** " + "; ".join(res["checks"]) + "."]
    if res["warnings"]:
        lines.append("**Review required:** " + "; ".join(res["warnings"]) + ".")
    return "\n\n".join(lines)


def applicability_checks(hydro: dict, geometry, row, v_l: float,
                         gas_on: bool, solids_on: bool) -> dict[str, list[str]]:
    """{checks, warnings}: applicability of the stirred-tank correlations.

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
    return {"checks": checks, "warnings": warnings}


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
        parts.append("Micromixing competes with the reaction: feed near the impeller and hold "
                     "local ε on scale-up.")
    if dma >= 0.1:
        parts.append("Blending is slow relative to the reaction and gets slower with scale - "
                     "re-check Da_macro at the next scale.")
    if worst < 0.1:
        parts.append("Re-check in the larger vessel before scale-up.")
    return kind, " ".join(parts), micro_likely


# ---------------------------------------------------------------------------
# Findings / verdict / next-steps builders (faithful to the Streamlit logic)
# ---------------------------------------------------------------------------
def _da_finding(da_value: float) -> tuple[str, str]:
    if da_value >= 1.0:
        return "critical", "Likely sensitive"
    if da_value >= 0.1:
        return "warning", "Transitional"
    return "ok", "Unlikely"


def build_findings(b_sensitive, b_mechs, b_done, test_rows, t_rxn, micro_likely,
                   meso_sensitive, competing, is_semi_batch, multiphase, phases,
                   has_enthalpy, heat_limiting, dH_eff, dt_ad, kinetics_known,
                   using_approx=False, dh_estimated=False, da=None) -> list[Finding]:
    findings: list[Finding] = []

    def add(area, kind, status, detail, code):
        findings.append(Finding(area, kind, status, detail, code))

    kpi_phrase = sensitive_kpi_phrase(test_rows)
    rem = remaining_tests(b_done)
    rem_action = (f"complete {fmt_tests(rem)} of the Bourne Protocol" if rem
                  else "re-run the Bourne Protocol decision tree")
    proxy_tag = " (proxy kinetics)" if using_approx else ""
    proxy_note = " Proxy kinetics - verify with measured data." if using_approx else ""

    # Bourne pre-screen
    area = "Bourne pre-screen"
    if b_sensitive is True:
        if b_mechs:
            add(area, "critical", "Mixing sensitivity confirmed",
                f"Mixing changed {kpi_phrase}. Controlling scale: {', '.join(b_mechs)}.",
                "bourne.confirmed")
        else:
            add(area, "critical", "Mixing sensitivity confirmed",
                f"Mixing changed {kpi_phrase}. Controlling scale unknown - {rem_action}.",
                "bourne.confirmed_unresolved")
    elif b_sensitive is False:
        add(area, "ok", "No sensitivity observed", "No mixing effect at lab scale.",
            "bourne.insensitive")
    elif b_done:
        add(area, "unknown", "Inconclusive",
            "Test 1 not completed - finish it for a direct answer.", "bourne.inconclusive")
    else:
        add(area, "unknown", "Not performed",
            "Run Bourne Test 1 for a direct experimental answer.", "bourne.not_performed")

    # Kinetics basis - proxy kinetics make every timescale conclusion provisional
    if kinetics_known and using_approx:
        add("Kinetics basis", "warning", "Approximate (proxy reaction)",
            "t_rxn comes from a proxy reaction, so the timescale findings are provisional. "
            "Measure the real kinetics.", "kinetics.approximate")

    # Micromixing
    area = "Micromixing"
    if not kinetics_known:
        add(area, "unknown", "Unknown",
            "No kinetics, so t_rxn is unknown. Bourne Test 1 gives a direct answer.",
            "micromixing.unknown")
    elif da:
        dmi = da["Da_micro"]
        kind, status = _da_finding(dmi)
        add(area, kind, status + proxy_tag,
            f"Da_micro = {dmi:.3g} (t_E {da['t_E']:.3g} s vs t_rxn {t_rxn:.4g} s) in "
            f"{da['reactor']} at {da['N_rpm']:.0f} RPM, {da['V_L']:.3g} L."
            + proxy_note, "micromixing.damkohler")
    elif micro_likely and t_rxn < 0.1:
        add(area, "critical", "Likely sensitive" + proxy_tag,
            f"t_rxn = {t_rxn:.4g} s - fast enough for local mixing to control the rate. "
            "Confirm with Da_micro." + proxy_note, "micromixing.fast_reaction")
    elif micro_likely:
        add(area, "warning", "Possible at scale" + proxy_tag,
            f"t_rxn = {t_rxn:.4g} s - may compete with micromixing in larger vessels. "
            "Confirm with Da_micro." + proxy_note, "micromixing.fast_reaction")
    elif using_approx:
        add(area, "warning", "Unlikely (proxy kinetics)",
            f"t_rxn = {t_rxn:.4g} s - slow vs micromixing (proxy kinetics; verify).",
            "micromixing.unlikely")
    else:
        add(area, "ok", "Unlikely", f"t_rxn = {t_rxn:.4g} s - slow vs micromixing.",
            "micromixing.unlikely")

    # Micro/mesomixing (selectivity)
    if meso_sensitive or is_semi_batch:
        if not meso_sensitive:
            add("Mesomixing (feed-plume)", "warning", "Semi-batch - check experimentally",
                "No competing reactions, but the feed plume sets the local concentration. "
                "Vary feed rate and location (Bourne Tests 2 & 3).", "mesomixing.semi_batch")
        else:
            not_sure = competing == Competing.NOT_SURE
            feed = " Feed rate and location matter (Bourne Tests 2 & 3)." if is_semi_batch else ""
            add("Micro/mesomixing (selectivity)", "warning" if not_sure else "critical",
                "Potentially sensitive" if not_sure else "Likely sensitive",
                ("Competing reactions may be present" if not_sure else "Competing reactions present")
                + " - local mixing at the feed can shift selectivity." + feed,
                "selectivity.competing")
    else:
        add("Micro/mesomixing (selectivity)", "ok", "Not a factor",
            "No competing reactions and no feed.", "selectivity.none")

    # Macromixing
    area = "Macromixing (blend time)"
    if not kinetics_known:
        add(area, "unknown", "Unknown", "No kinetics - cannot compare t_rxn with blend time.",
            "macromixing.unknown")
    elif da:
        dma = da["Da_macro"]
        kind, status = _da_finding(dma)
        add(area, kind, status + proxy_tag,
            f"Da_macro = {dma:.3g} (θ₉₅ {da['t_blend']:.3g} s vs t_rxn {t_rxn:.4g} s) in "
            f"{da['reactor']}. Blend time grows with scale - re-check at the next scale."
            + proxy_note, "macromixing.damkohler")
    elif t_rxn < 60:
        add(area, "warning", "Check at scale",
            f"t_rxn = {t_rxn:.4g} s is within typical large-vessel blend times (10–120 s). "
            "Compute Da_macro.", "macromixing.check_at_scale")
    elif using_approx:
        add(area, "warning", "Unlikely (proxy kinetics)",
            f"t_rxn = {t_rxn:.4g} s - much longer than blend times (proxy kinetics; verify).",
            "macromixing.unlikely")
    else:
        add(area, "ok", "Unlikely", f"t_rxn = {t_rxn:.4g} s - much longer than blend times.",
            "macromixing.unlikely")

    # Mass transfer
    phase_names = [Phase(p).label for p in phases]
    if multiphase:
        add(f"Mass transfer ({' + '.join(phase_names)})", "warning", "System-dependent",
            "Interphase transport may limit the rate. Check gas–liquid kLa and "
            "solid–liquid transport.", "mass_transfer.multiphase")
    else:
        phase_lbl = phase_names[0] if phase_names else Phase.LIQUID.label
        add("Mass transfer", "ok", "Not applicable",
            f"Single phase ({phase_lbl}) - no interphase transport.", "mass_transfer.single_phase")

    # Heat transfer
    detail = f"|ΔH| = {abs(dH_eff):.1f} kJ/mol"
    if dt_ad is not None:
        detail += f", ΔT_ad ≈ {dt_ad:.0f} K"
    if has_enthalpy and heat_limiting:
        duty = "cooling" if dH_eff < 0 else "heating"
        note = " ΔH is estimated - confirm by calorimetry." if dh_estimated else ""
        add("Heat transfer", "critical",
            "Likely heat-transfer-limited" + (" (estimated ΔH)" if dh_estimated else ""),
            f"{detail} - check {duty} capacity with a heat balance.{note}", "heat.limiting")
    elif has_enthalpy and dh_estimated:
        add("Heat transfer", "warning", "Manageable (estimated ΔH)",
            f"{detail} - modest load, but ΔH is estimated. Confirm by calorimetry.",
            "heat.manageable")
    elif has_enthalpy:
        add("Heat transfer", "ok", "Manageable", f"{detail} - modest load, unlikely to limit.",
            "heat.manageable")
    else:
        add("Heat transfer", "unknown", "Unknown",
            "No ΔH - measure it by reaction calorimetry (RC1 / µRC).", "heat.unknown")
    return findings


MIXING_GROUPS = ("micromixing", "selectivity", "mesomixing", "macromixing", "mass_transfer")


def _group(f: Finding) -> str:
    return f.code.split(".")[0]


def _confirm_by(groups: set[str], da_done: bool) -> str:
    """How to confirm the flagged mixing mechanisms (each mechanism has its own check)."""
    parts = []
    if groups & {"micromixing", "macromixing"}:
        parts.append("Da_micro / Da_macro at the target scale" if da_done
                     else "vessel-specific Da_micro / Da_macro")
    if groups & {"selectivity", "mesomixing"}:
        parts.append("feed-rate and feed-location tests (Bourne Tests 2 and 3)")
    if "mass_transfer" in groups:
        parts.append("Da_GL / Da_SL on the Vessel Assessment page")
    if len(parts) > 1:
        return ", ".join(parts[:-1]) + " and " + parts[-1]
    return parts[0] if parts else "a vessel-specific assessment"


def verdict_message(b_sensitive, b_mechs, b_done, findings: list[Finding], competing) -> Message:
    """Overall mixing-sensitivity verdict.

    Only mixing / mass-transport findings drive the mixing verdict. Heat transfer is a
    separate thermal question and is reported alongside it, never as a mixing mechanism.
    """
    mix = [f for f in findings if _group(f) in MIXING_GROUPS]
    red = [f for f in mix if f.kind == "critical"]
    red_mechs = [f.area for f in red]
    n_yellow = sum(1 for f in mix if f.kind in ("warning", "caution"))
    n_unknown = sum(1 for f in mix if f.kind == "unknown")
    da_done = any(f.code.endswith(".damkohler") for f in mix)
    confirm = _confirm_by({_group(f) for f in red}, da_done)
    rem = remaining_tests(b_done)
    rem_action = (f"complete {fmt_tests(rem)} of the Bourne Protocol" if rem
                  else "re-run the Bourne Protocol decision tree")

    def mixing() -> tuple[str, str, str, str]:
        """(kind, headline, explanation, code) of the mixing verdict."""
        if b_sensitive is True:
            head = "Mixing sensitivity confirmed"
            if b_mechs:
                return ("critical", head, f"the Bourne Protocol points to **{join_mechs(b_mechs)}** "
                        "as the controlling scale. Focus scale-up on it.", "confirmed.mechanism")
            if red_mechs:
                return ("critical", head, "the Bourne pre-screen shows a sensitivity and theory "
                        f"points to **{join_mechs(red_mechs)}**. To confirm the scale, {rem_action}.",
                        "confirmed.theory_flagged")
            if n_yellow:
                return ("critical", head, "the Bourne pre-screen shows a sensitivity, but no single "
                        f"mechanism stands out. To find the scale, {rem_action}.",
                        "confirmed.needs_tests")
            return ("critical", head, "the Bourne pre-screen shows a sensitivity that theory does "
                    f"not explain. Check the inputs (kinetics, phases, feed) and {rem_action}.",
                    "confirmed.unexplained")

        if b_sensitive is False:
            if n_unknown:
                return ("warning", "Incomplete assessment", f"{n_unknown} mixing item(s) could not "
                        "be assessed (e.g. no kinetics). No effect at lab scale, but the scale-up "
                        "risk is unconfirmed.", "incomplete")
            if red_mechs:
                return ("warning", "Possible scale-dependent mixing sensitivity", "no effect at lab "
                        f"scale, but **{join_mechs(red_mechs)}** may limit at larger scale. Confirm "
                        f"with {confirm} before scale-up.", "scale_dependent")
            if n_yellow:
                return ("ok", "Low mixing sensitivity risk", "no effect at lab scale and no likely "
                        "mechanism; a few items need a check at scale.", "low.with_checks")
            return ("ok", "Low mixing sensitivity risk", "no effect at lab scale and no mechanism "
                    "expected to limit.", "low")

        # Bourne not performed - theory only
        if len(red_mechs) >= 2:
            return ("critical", "High mixing sensitivity risk", f"**{join_mechs(red_mechs)}** are "
                    f"likely to limit at scale. Confirm with {confirm}, and run a Bourne "
                    "pre-screen.", "high")
        if red_mechs:
            return ("warning", "Moderate mixing sensitivity risk", f"**{join_mechs(red_mechs)}** "
                    f"is likely to be sensitive. Confirm with {confirm}, and run a Bourne "
                    "pre-screen.", "moderate")
        if n_unknown:
            return ("warning", "Incomplete assessment", f"{n_unknown} mixing item(s) could not be "
                    "assessed (e.g. no kinetics). Resolve them or run a Bourne pre-screen.",
                    "incomplete")
        if n_yellow:
            return ("warning", "Low-to-moderate mixing sensitivity risk", "nothing is likely "
                    "sensitive, but some items need a check at scale. A Bourne pre-screen would "
                    "confirm.", "low_to_moderate")
        return ("ok", "Low mixing sensitivity risk", "no mixing mechanism is expected to limit "
                "this reaction.", "low")

    kind, head, body, code = mixing()

    heat = next((f for f in findings if _group(f) == "heat"), None)
    if heat is not None and heat.kind == "critical":
        body += (" **Separately, heat transfer is likely limiting** - a thermal issue, not a "
                 "mixing sensitivity. Run a heat balance.")
        if kind == "ok":
            kind, head = "warning", head + "; heat transfer needs review"
        else:
            head += "; heat transfer also needs review"
    elif heat is not None and heat.kind == "unknown":
        body += " ΔH is unknown, so heat transfer is not assessed."
    elif heat is not None and heat.kind in ("warning", "caution"):
        body += " The heat load looks manageable, but ΔH is estimated."
    if any(f.code == "kinetics.approximate" for f in findings) and b_sensitive is not True:
        body += " Timescales rely on proxy kinetics."
    return Message(kind, f"**{head}** - {body}", code)


_MECH_ACTIONS = {
    "Micromixing": "Hold local ε (P/V) on scale-up and feed near the impeller.",
    "Mesomixing": "Hold local ε, slow the feed, or add feed points.",
    "Macromixing": "Shorten the blend time: better or more impellers, baffles, or in-line mixers.",
}


def build_next_steps(b_sensitive, b_mechs, using_approx, micro_likely, t_rxn,
                     meso_sensitive, multiphase, has_enthalpy, heat_limiting, is_semi_batch,
                     kinetics_known, kinetics_declined, dh_estimated=False, *,
                     b_done=(), da_done=False) -> list[Action]:
    steps: list[Action] = []
    rem = remaining_tests(b_done)
    if b_sensitive is None:
        steps.append(Action("Bourne pre-screen", "Run Bourne Test 1 to check experimentally "
                            "whether mixing matters.", "bourne.run"))
    if b_sensitive is True and b_mechs:
        for m in b_mechs:
            if m in _MECH_ACTIONS:
                steps.append(Action(f"{m} (Bourne-confirmed)", _MECH_ACTIONS[m],
                                    f"bourne.{m.lower()}"))
    elif b_sensitive is True and rem:
        steps.append(Action("Bourne Protocol", f"Complete {fmt_tests(rem)} "
                            f"({fmt_test_purposes(rem)}) to find the controlling scale.",
                            "bourne.complete"))
    if using_approx:
        steps.append(Action("Kinetics", "Measure the real kinetics to replace the proxy values.",
                            "kinetics.replace_approximate"))
    if kinetics_declined:
        steps.append(Action("Kinetics", "Measure the kinetics and add them to the database to "
                            "enable the Damköhler check.", "kinetics.measure"))
    if kinetics_known and (micro_likely or t_rxn < 60):
        if da_done:
            steps.append(Action("Damköhler analysis", "Re-check Da_micro / Da_macro in the "
                                "target-scale vessel.", "damkohler.recheck"))
        else:
            steps.append(Action("Damköhler analysis", "Compute Da_micro / Da_macro for your "
                                "vessel (Step 7 or Vessel Assessment).", "damkohler.compute"))
    if (meso_sensitive or is_semi_batch) and not (b_sensitive is True and b_mechs):
        if b_sensitive is None:
            steps.append(Action("Micro/mesomixing", "Run the full Bourne Protocol to check "
                                "feed-zone effects.", "selectivity.bourne"))
        elif rem and b_sensitive is False:
            steps.append(Action("Micro/mesomixing", f"Run {fmt_tests(rem)} (feed rate and "
                                "location) - Test 1 alone does not cover the feed zone.",
                                "selectivity.bourne"))
    if multiphase:
        steps.append(Action("Mass transfer", "Assess Da_GL / Da_SL on the Vessel Assessment "
                            "page.", "mass_transfer.assess"))
    if has_enthalpy and heat_limiting:
        steps.append(Action("Heat transfer", "Run a heat balance (Vessel Assessment or Heat "
                            "Transfer) against the jacket duty.", "heat.balance"))
    if has_enthalpy and dh_estimated:
        steps.append(Action("Heat of reaction", "Measure ΔH by calorimetry (RC1 / µRC) to "
                            "replace the estimate.", "heat.calorimetry"))
    if not steps:
        steps.append(Action("General", "Low risk - standard scale-up practice is sufficient.",
                            "general.low_risk"))
    return steps


# ---------------------------------------------------------------------------
# Bourne Protocol decision tree
# ---------------------------------------------------------------------------
MECH_CONCLUSION = {
    "Mixing-insensitive": (
        "**🟢 Mixing is not rate-limiting.** Scale up on geometric similarity."),
    "Micromixing": (
        "**🔬 Micromixing controls.** Scale-up rule: **hold local ε constant** at the feed "
        "point."),
    "Mesomixing": (
        "**Mesomixing controls.** Scale-up rule: **match P/V, extend the feed time and add "
        "feed points.**"),
    "Macromixing": (
        "**Macromixing controls.** Scale-up rule: **keep blend times short.**"),
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
        lines.append("- **Test 1:** sensitive to impeller speed.")
    elif o["s1"] == "inconclusive":
        lines.append("- **Test 1:** mixed response to impeller speed (inconclusive).")
    elif o["s1"] == "not_sensitive" and not o["range_ok"]:
        lines.append(f"- **Test 1:** no effect, but only a {o['ratio']:.1f}× P/m span "
                     "(100× intended) - inconclusive.")
    elif o["s1"] == "not_sensitive":
        lines.append("- **Test 1:** not sensitive to impeller speed.")
    if o["s2"]:
        lines.append({"sensitive": "- **Test 2:** sensitive to feed rate.",
                      "not_sensitive": "- **Test 2:** not sensitive to feed rate.",
                      }.get(o["s2"], "- **Test 2:** mixed response to feed rate (inconclusive)."))
    if o["s3"]:
        lines.append({"sensitive": "- **Test 3:** sensitive to feed location.",
                      "not_sensitive": "- **Test 3:** not sensitive to feed location.",
                      }.get(o["s3"], "- **Test 3:** mixed response to feed location (inconclusive)."))
    return lines


BOURNE_TEST_TITLES = {1: "Test 1 - Impeller speed", 2: "Test 2 - Feed rate",
                      3: "Test 3 - Feed location"}


def bourne_test_verdict(test: int, res: dict, ratio: float = 100.0) -> tuple[str, bool]:
    """(Markdown verdict, run the next test?) after assessing Bourne ``test`` with the
    ``assess_kpis`` result ``res``; ``ratio`` = achieved Test 1 P/m span."""
    prefix, status = kpi_prefix(res), res["status"]
    if test == 1:
        if status == "sensitive":
            return prefix + " **Mixing matters.** Next: Test 2.", True
        if status == "inconclusive":
            return prefix + " Possible sensitivity. Next: Test 2.", True
        if ratio < 100.0:
            return (prefix + f" Only a {ratio:.1f}× P/m span was reached (100× intended), so "
                    "this is **inconclusive**. Widen the speed range, or continue to Test 2.", True)
        return prefix + " Mixing is not limiting - scale up on geometric similarity.", False
    if test == 2:
        if status == "sensitive":
            return prefix + " Feed rate matters (**mesomixing** likely). Next: Test 3.", True
        if status == "inconclusive":
            return prefix + " Possible mesomixing. Next: Test 3.", True
        return (prefix + " **Micromixing** controls. Scale-up: hold local ε constant at the "
                "feed point.", False)
    if status == "sensitive":
        return (prefix + " **Mesomixing** controls. Scale-up: match P/V, extend the feed time "
                "and add feed points.", False)
    if status == "inconclusive":
        return (prefix + " Meso vs macro is unresolved. Replicate Test 3 or widen the ε "
                "contrast between feed points.", False)
    return prefix + " **Macromixing** controls. Scale-up: keep blend times short.", False


def bourne_summary_md(o: dict) -> str:
    """Decision-tree conclusion (Markdown) for a ``bourne_outcome``."""
    lines = ["### Decision-tree conclusion", ""] + bourne_test_lines(o) + [""]
    return "\n".join(lines + bourne_conclusion_lines(o))


def bourne_conclusion_lines(o: dict) -> list[str]:
    """The conclusion paragraph(s) of :func:`bourne_summary_md` (after the per-test bullets)."""
    lines: list[str] = []
    dom = o["dominant"]
    if dom in MECH_CONCLUSION:
        lines.append(MECH_CONCLUSION[dom])
        if o["tentative"]:
            lines.append("")
            lines.append("⚠️ **Tentative:** an earlier test was inconclusive. Replicate it "
                         "before fixing the scale-up rule.")
    elif dom == "Inconclusive":
        if o["s3"] == "inconclusive":
            lines.append("⚪ **Meso vs macro unresolved** - Test 3 gave a mixed result. "
                         "Replicate it or widen the ε contrast between feed points.")
        else:
            lines.append("⚪ **No confirmed sensitivity** - Test 1 was inconclusive and feed rate "
                         "had no effect. Repeat Test 1 with replicates over the full 100× P/m span.")
    elif o["next_test"] == 3:
        lines.append("Tests 1 and 2 show a mixing effect. Run **Test 3** (feed location) to "
                     "separate meso- from macromixing.")
    else:
        lines.append("Continue with **Test 2** (feed rate).")
    return lines


def bourne_conclusions(o: dict, results: dict) -> list[tuple[str, str, str]]:
    """Report verdict rows (title, Markdown verdict, icon) from a ``bourne_outcome``
    and the ``assess_kpis`` result of each test (None when not run)."""
    def verdict(res):
        n, N = res["n_sensitive"], res["n_total"]
        thr = threshold_phrase(res) if res.get("results") else f"≥ {SENS_THRESHOLD:.0f}%"
        if res["status"] == "sensitive":
            return f"**Sensitive** ({n}/{N} KPIs {thr})"
        if res["status"] == "inconclusive":
            return f"**Inconclusive** ({n}/{N} KPIs {thr})"
        return f"**Not sensitive** (0/{N} KPIs)"

    rows = []
    for test in (1, 2, 3):
        res = results.get(test)
        if not res:
            continue
        v = verdict(res)
        if test == 1 and o["s1"] == "not_sensitive" and not o["range_ok"]:
            v += f" - only a {o['ratio']:.1f}x P/m span; treated as inconclusive"
        rows.append((BOURNE_TEST_TITLES[test], v, ""))
    if o["tentative"]:
        rows.append(("Confidence", "**Tentative** - an earlier test was inconclusive; "
                     "replicate it first", ""))
    return rows


# ---------------------------------------------------------------------------
# Reaction Sensitivity Protocol — full step-by-step assessment
# ---------------------------------------------------------------------------
@dataclass
class ProtocolInputs:
    """User answers for the Reaction Sensitivity Protocol, as codes from :mod:`core.options`.

    ``competing`` and ``dh_action`` are "" when unanswered; ``bourne_mech`` is ""
    when the controlling scale was not resolved.
    """
    order: str
    k: float
    C0: float
    t_specified: float
    dH: float
    rxn_type: str = ""
    kinetics: Kinetics = Kinetics.AVAILABLE
    bourne: BourneStatus = BourneStatus.SKIP
    bourne_mech: Mechanism | str = ""
    bourne_tests_done: list[int] = field(default_factory=list)
    bourne_rows: list[dict] = field(default_factory=list)
    semi_batch: bool = False
    phases: list[Phase] = field(default_factory=lambda: [Phase.LIQUID])
    competing: Competing | str = ""
    dh_override: float = 0.0
    dh_override_measured: bool = False
    dh_action: DhAction | str = ""
    dh_ref_value: float = 0.0
    c0_heat: float = 1.0
    rho_cp: float = 1800.0


def bourne_prescreen(status: str, mech: str, done: list[int]):
    """(sensitive True/False/None, confirmed mechanisms, completed tests) from the pre-screen."""
    done = sorted(done)
    if status == BourneStatus.CONFIRMED:
        return True, ([mech] if mech in tuple(Mechanism) else []), done
    if status == BourneStatus.INSENSITIVE:
        return False, [], done
    if status == BourneStatus.INCONCLUSIVE:
        return None, [], done
    return None, [], []


def rate_law(order: str) -> str:
    n_sym = "k'" if order.startswith("pseudo") else "k"
    conc = {"0": "", "1": "·C", "2": "·C²"}.get(order.split("-")[-1] if order else "1", f"·C^{order}")
    return f"−dC/dt = {n_sym}{conc}"


def kinetics_md(kin: dict) -> str:
    t_rxn, t_90 = kin["t_rxn"], kin["t_90"]
    if t_rxn <= 0:
        return "⚠️ Cannot determine a reaction time - check k, C₀ and t_rxn."
    return (
        f"**Rate law** (order {kin['order']}): {kin['law']}\n\n"
        f"**t_rxn = {t_rxn:.4g} s** ({kin['basis']}) - the initial-rate time constant used for "
        "every Damköhler check."
        + (f" 90% conversion takes ~{t_90:.4g} s (planning only)." if t_90 != t_rxn else ""))


def assess_protocol(inp: ProtocolInputs,
                    damkohler_for: Callable[[float], dict | None] | None = None) -> dict:
    """Run every step of the Reaction Sensitivity Protocol.

    ``damkohler_for(t_rxn)`` optionally returns reactor-specific Da numbers (see
    ``da_caption``) for Step 5. Returns structured results: ``steps`` (one
    :class:`Message` or None per step 0-5), ``findings``, ``verdict``,
    ``next_steps``, ``ready`` and the underlying values. Render with :func:`protocol_md`.
    """
    steps: list[Message | None] = [None] * 6

    # ---- Step 0: Bourne pre-screen -------------------------------------
    b_sensitive, b_mechs, b_done = bourne_prescreen(
        inp.bourne, inp.bourne_mech, inp.bourne_tests_done)
    test_rows = list(inp.bourne_rows)
    if inp.bourne == BourneStatus.SKIP:
        steps[0] = Message(
            "caution", "**Bourne pre-screen skipped** - using theory only. A Bourne test gives "
            "a direct answer.", "bourne.skipped")
    elif b_sensitive is True:
        if b_mechs:
            steps[0] = Message(
                "critical", f"**Mixing sensitivity confirmed** - controlling scale: "
                f"**{b_mechs[0].lower()}**.", "bourne.confirmed")
        else:
            rem = remaining_tests(b_done)
            add = (f" Run **{fmt_tests(rem)}** ({fmt_test_purposes(rem)}) to find it."
                   if rem else "")
            steps[0] = Message(
                "critical", "**Mixing sensitivity confirmed**; controlling scale not yet "
                "resolved." + add, "bourne.confirmed_unresolved")
    elif b_sensitive is False:
        steps[0] = Message(
            "ok", "**No mixing sensitivity** at lab scale. The steps below check for risks at "
            "larger scale.", "bourne.insensitive")
    else:
        steps[0] = Message(
            "caution", "Bourne result **inconclusive** - complete at least Test 1.",
            "bourne.inconclusive")

    # ---- Step 1: kinetics ----------------------------------------------
    order = inp.order or "1"
    t_rxn, t_90, t_basis = characteristic_reaction_time(order, inp.k, inp.C0, inp.t_specified)
    using_approx = inp.kinetics == Kinetics.APPROXIMATE
    kinetics_declined = inp.kinetics == Kinetics.DECLINED
    kinetics_known = (t_rxn > 0) and not kinetics_declined
    kinetics_resolved = kinetics_known or kinetics_declined
    kinetics = {"order": order, "law": rate_law(order), "t_rxn": t_rxn, "t_90": t_90,
                "basis": t_basis}
    if kinetics_declined:
        steps[1] = Message(
            "warning", "**No kinetics yet.** Measure them and add the reaction to the database. "
            "Meanwhile, a Bourne pre-screen gives a direct answer.", "kinetics.declined")
    elif not kinetics_known:
        steps[1] = Message(
            "critical", "Cannot derive a reaction time from this data.", "kinetics.missing")
    elif using_approx:
        steps[1] = Message(
            "warning", "**Proxy kinetics** - timescale conclusions are provisional. Confirm "
            "with measured data.", "kinetics.approximate")
    else:
        steps[1] = Message("ok", "**Kinetics available.**", "kinetics.available")
    is_semi_batch = inp.semi_batch

    # ---- Step 2: phases -------------------------------------------------
    phases = list(inp.phases or [])
    phase_names = [Phase(p).label for p in phases]
    multiphase = len(phases) > 1
    if not phases:
        steps[2] = Message("caution", "Select at least one phase to continue.", "phases.none")
    elif multiphase:
        steps[2] = Message(
            "warning", "**Multi-phase** (" + " + ".join(phase_names) + ") - interphase transfer "
            "may limit the rate. Check Da_GL / Da_SL on the Vessel Assessment page.",
            "phases.multiphase")
    elif phases == [Phase.LIQUID]:
        steps[2] = Message(
            "ok", "**Single liquid phase** - no interphase transfer.", "phases.single_liquid")
    else:
        steps[2] = Message(
            "caution", f"**Only {phase_names[0].lower()} selected** - check the liquid phase "
            "is not missing.", "phases.single_other")

    # ---- Step 3: competing reactions -----------------------------------
    competing = inp.competing
    competing_set = competing in tuple(Competing)
    meso_sensitive, require_feed_zone = mesomixing_risk(competing, is_semi_batch)
    if not competing_set:
        steps[3] = Message("caution", "Select an option to continue.", "competing.unset")
    elif competing == Competing.YES:
        steps[3] = Message(
            "critical", "**Competing reactions** - mixing at the feed can shift selectivity; "
            "likely mixing-sensitive.", "competing.yes")
    elif competing == Competing.NOT_SURE:
        steps[3] = Message(
            "warning", "Treat as **potentially sensitive** until a Bourne test confirms.",
            "competing.not_sure")
    elif require_feed_zone:
        steps[3] = Message(
            "warning", "No competing reactions, but **semi-batch** - check feed rate and "
            "location before ruling out mesomixing.", "competing.no_semi_batch")
    else:
        steps[3] = Message(
            "ok", "**No competing reactions** in a batch process - selectivity is unlikely to "
            "depend on mixing.", "competing.no")

    # ---- Step 4: heat transfer -----------------------------------------
    dh_from_override = inp.dh_override != 0.0
    has_enthalpy = inp.dH != 0.0 or dh_from_override
    dH_eff = inp.dh_override if dh_from_override else inp.dH
    show_dh_action = not has_enthalpy
    heat_resolved = True
    dt_ad = None
    heat_summary = None
    if not has_enthalpy:
        if inp.dh_action == DhAction.ESTIMATE:
            dH_eff = inp.dh_ref_value
            has_enthalpy = dH_eff != 0.0
        elif inp.dh_action != DhAction.CALORIMETRY:
            heat_resolved = False

    # An override is measured only if declared so; otherwise ΔH inherits the
    # kinetics basis (proxy kinetics ==> proxy ΔH).
    if dh_from_override:
        dh_estimated = not inp.dh_override_measured
    elif inp.dH == 0.0 and inp.dh_action == DhAction.ESTIMATE:
        dh_estimated = True
    else:
        dh_estimated = using_approx

    abs_dH = abs(dH_eff)
    heat_limiting = False
    heat_flagged_type = any(t in inp.rxn_type.lower() for t in KNOWN_HOT)
    if has_enthalpy:
        if inp.c0_heat > 0 and inp.rho_cp > 0:
            dt_ad = abs_dH * inp.c0_heat * 1000.0 / inp.rho_cp
            heat_summary = heat_transfer_summary(abs_dH, dt_ad, dH_eff=dH_eff)
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
            msg += f" **Heat transfer likely limiting** - check {duty} capacity with a heat balance."
        if heat_flagged_type:
            msg += (f" **{inp.rxn_type}** reactions are often strongly exothermic - assess heat "
                    "regardless of ΔH.")
        if dh_estimated:
            msg += " ΔH is **estimated** - confirm by calorimetry."
        steps[4] = Message("critical" if heat_limiting else heat_kind, msg,
                           "heat.limiting" if heat_limiting else "heat.assessed")
    elif inp.dh_action == DhAction.CALORIMETRY:
        steps[4] = Message(
            "caution", "Heat transfer **cannot be assessed without ΔH** - measure it by "
            "calorimetry (RC1 / µRC) and return.", "heat.calorimetry")
    elif not heat_resolved:
        steps[4] = Message(
            "unknown", "No ΔH for this reaction - choose how to proceed above.",
            "heat.unresolved")
    else:
        steps[4] = Message("unknown", "No ΔH - measure it by reaction calorimetry.",
                           "heat.no_data")

    # ---- Step 5: mixing time vs reaction time --------------------------
    da = damkohler_for(t_rxn) if (damkohler_for and kinetics_known and t_rxn > 0) else None
    if kinetics_known and t_rxn > 0:
        if da:
            kind, text, micro_likely = da_assessment(da)
            steps[5] = Message(kind, text, "timescale.damkohler")
        elif t_rxn < 0.1:
            steps[5] = Message(
                "critical", "**Very fast reaction** - micromixing-sensitive in most vessels; "
                "feed location and tip speed matter. " + damkohler_screening_note(t_rxn),
                "timescale.very_fast")
            micro_likely = True
        elif t_rxn < 1.0:
            steps[5] = Message(
                "warning", "**Fast reaction** - micromixing may matter in larger vessels. "
                + damkohler_screening_note(t_rxn), "timescale.fast")
            micro_likely = True
        elif t_rxn < 10:
            steps[5] = Message(
                "caution", "**Moderate reaction** - blend time could matter in larger vessels. "
                + damkohler_screening_note(t_rxn), "timescale.moderate")
            micro_likely = False
        else:
            steps[5] = Message(
                "ok", "**Slow reaction** - mixing is unlikely to limit. "
                + damkohler_screening_note(t_rxn), "timescale.slow")
            micro_likely = False
    else:
        if kinetics_declined:
            steps[5] = Message(
                "unknown", "No kinetics - cannot compare mixing and reaction times. Bourne "
                "Test 1 gives a direct answer.", "timescale.no_kinetics")
        micro_likely = False

    # ---- Step 6: findings, verdict, next steps -------------------------
    findings = build_findings(
        b_sensitive, b_mechs, b_done, test_rows, t_rxn, micro_likely,
        meso_sensitive, competing, is_semi_batch, multiphase, phases,
        has_enthalpy, heat_limiting, dH_eff, dt_ad, kinetics_known, using_approx,
        dh_estimated, da)
    verdict = verdict_message(b_sensitive, b_mechs, b_done, findings, competing)
    next_steps = build_next_steps(
        b_sensitive, b_mechs, using_approx, micro_likely, t_rxn, meso_sensitive,
        multiphase, has_enthalpy, heat_limiting, is_semi_batch, kinetics_known,
        kinetics_declined, dh_estimated, b_done=b_done, da_done=da is not None)

    return {
        "steps": steps, "findings": findings, "verdict": verdict, "next_steps": next_steps,
        "ready": bool(kinetics_resolved and phases and competing_set and heat_resolved),
        "kinetics": kinetics, "kinetics_known": kinetics_known, "using_approx": using_approx,
        "t_rxn": t_rxn, "has_enthalpy": has_enthalpy, "heat_resolved": heat_resolved,
        "show_dh_action": show_dh_action, "dH_eff": dH_eff, "dt_ad": dt_ad,
        "heat_summary": heat_summary, "dh_estimated": dh_estimated, "phases": phases,
        "competing_set": competing_set, "is_semi_batch": is_semi_batch, "da": da,
        "bourne_rows": test_rows, "b_sensitive": b_sensitive, "b_mechs": b_mechs,
    }


SUMMARY_PENDING = ("*Complete the kinetics, phases, competing-reactions and ΔH steps to see "
                   "the verdict.*")


def protocol_md(res: dict) -> dict:
    """Markdown rendering of :func:`assess_protocol` for the web page and PDF report."""
    out = {f"step{i}": (m.md() if m else "") for i, m in enumerate(res["steps"])}
    t_rxn, dt_ad = res["t_rxn"], res["dt_ad"]
    if not res["has_enthalpy"]:
        dt_caption = ""
    elif dt_ad is None:
        dt_caption = "Enter C₀ and ρ·Cp above to estimate ΔT_ad."
    else:
        dt_caption = f"ΔT_ad ≈ **{dt_ad:.0f} K** - {res['heat_summary']}"
    out.update({
        "kinetics_md": kinetics_md(res["kinetics"]),
        "dt_ad_caption": dt_caption,
        "da_caption": da_caption(res["da"]),
        "trxn_caption": (f"Your reaction time: **t_rxn = {t_rxn:.4g} s**."
                         if res["kinetics_known"] else ""),
        "summary_note": "" if res["ready"] else SUMMARY_PENDING,
        "verdict": res["verdict"].md(),
        "findings": [f.row() for f in res["findings"]],
        "next_steps": [a.row() for a in res["next_steps"]],
    })
    return out
