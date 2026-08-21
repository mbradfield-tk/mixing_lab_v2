"""Reaction Sensitivity Protocol page (Taipy).

Ported from the Streamlit ``10_Mixing_Sensitivity_Protocol.py`` page. A guided,
decision-tree assessment that determines **whether a reaction is sensitive to
mixing** and, if so, **which mechanism controls** it — micromixing, mesomixing,
macromixing, interphase mass transport, or heat transfer.

The workflow synthesises up to seven inputs into an overall verdict:

* **Step 0 — Bourne pre-screen:** experimental evidence (if available) that a
  mixing sensitivity exists (and, when Bourne Tests 1–3 are complete, which
  scale controls it). Independent of the theory below and combined with it.
* **Step 1 — Kinetics:** the characteristic reaction time ``t_rxn`` (1/k or
  1/(k·C₀)), the Damköhler reference timescale.
* **Step 2 — Phases:** single vs multi-phase → interphase mass-transfer risk.
* **Step 3 — Competing reactions:** micro-/mesomixing selectivity risk.
* **Step 4 — Heat transfer:** exothermicity and the adiabatic temperature rise
  ``ΔT_ad = |ΔH|·C₀·1000/(ρ·Cp)``.
* **Step 5 — Mixing time vs reaction time:** micro-/macromixing likelihood from
  the magnitude of ``t_rxn``.
* **Step 6 — Summary:** the classification decision tree → overall verdict,
  findings table, and recommended next steps.
* **Step 7 — Export:** a PDF report (``build_protocol_pdf``).

The Bourne pre-screen can be entered manually or imported from a Bourne
Protocol results CSV (the same ``field,value`` export produced on that page).
"""
from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pandas as pd
from taipy.gui import Markdown, notify

from utils.menu_icons import inject_icons
from utils.solvent_properties import get_properties, is_known_solvent
from utils.report_builder import build_protocol_pdf, report_filename
from pages import _db_common as db
from vessel_media import build_image_html

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
reactions_df = pd.read_csv(DATA_DIR / "reactions.csv")

IMAGES_DIR = Path(__file__).resolve().parent.parent / "images" / "general"
ms_decision_tree_html = build_image_html(
    IMAGES_DIR / "mixing_sensitivity_protocol.png", alt="Reaction mixing sensitivity protocol")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _sf(val, default=0.0) -> float:
    try:
        f = float(val)
        return default if np.isnan(f) else f
    except (TypeError, ValueError):
        return default


def _reaction_row(name: str) -> pd.Series:
    df = db.fresh_csv(DATA_DIR / "reactions.csv", ["reaction_name"])
    row = df[df["reaction_name"].astype(str) == str(name)]
    return row.iloc[0] if not row.empty else pd.Series(dtype=object)


def _amd(kind: str, text: str) -> str:
    """Traffic-light assessment line: emoji + markdown text."""
    icon = {"critical": "🔴", "warning": "🟡", "caution": "🟡",
            "ok": "🟢", "unknown": "⚪"}.get(kind, "⚪")
    return f"{icon} {text}"


_TEST_PURPOSE = {1: "impeller speed", 2: "feed rate/time", 3: "feed location"}


def _remaining_tests(done_tests, needed=(2, 3)) -> list[int]:
    return [t for t in needed if t not in (done_tests or [])]


def _fmt_tests(nums) -> str:
    if not nums:
        return ""
    if len(nums) == 1:
        return f"Test {nums[0]}"
    return "Tests " + " and ".join(str(n) for n in nums)


def _fmt_test_purposes(nums) -> str:
    return " and ".join(_TEST_PURPOSE[n] for n in nums if n in _TEST_PURPOSE)


def _join_mechs(names: list[str]) -> str:
    clean = [n.split("(")[0].strip().lower() for n in names]
    if len(clean) == 1:
        return clean[0]
    if len(clean) == 2:
        return f"{clean[0]} and {clean[1]}"
    return ", ".join(clean[:-1]) + f", and {clean[-1]}"


def _sensitive_kpi_phrase(test_rows) -> str:
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


_KNOWN_HOT = ["grignard", "nitration", "sulfonation", "diazotization",
              "polymerization", "hydrogenation", "oxidation"]


# ---------------------------------------------------------------------------
# Option lists
# ---------------------------------------------------------------------------
reaction_options = sorted(reactions_df["reaction_name"].dropna().astype(str).tolist())
_dh_ref_df = reactions_df[reactions_df["delta_H_kJ_mol"].apply(lambda v: _sf(v) != 0.0)]
dh_ref_options = sorted(_dh_ref_df["reaction_name"].dropna().astype(str).tolist()) or ["(none available)"]

ms_kinetics_options = ["Yes — kinetics available in the database",
                       "Approximate — use a similar reaction as a proxy",
                       "No — kinetics not yet available"]
ms_bourne_status_options = ["Not run — skip pre-screen",
                            "Ran — sensitivity confirmed",
                            "Ran — no sensitivity at lab scale",
                            "Ran — inconclusive (Test 1 not completed)"]
ms_bourne_mech_options = ["Not resolved", "Micromixing", "Mesomixing", "Macromixing"]
ms_bourne_tests_options = ["Test 1", "Test 2", "Test 3"]
ms_phase_options = ["Liquid", "Solid", "Gas"]
ms_competing_options = ["— select —", "Yes", "No", "Not sure"]
ms_dh_action_options = ["— select —",
                        "Perform calorimetry — measure ΔH experimentally",
                        "Estimate ΔH from a similar reaction"]


# ---------------------------------------------------------------------------
# State — Step 0 (Bourne pre-screen)
# ---------------------------------------------------------------------------
ms_bourne_status = ms_bourne_status_options[0]
ms_bourne_mech = "Not resolved"
ms_bourne_tests = ["Test 1"]
ms_bourne_upload = ""
ms_step0_assess = ""
ms_bourne_findings_df = pd.DataFrame(columns=["Test", "Finding", "Sensitive KPI(s)"])
ms_bourne_meta_caption = ""

# ---------------------------------------------------------------------------
# State — Step 1 (kinetics)
# ---------------------------------------------------------------------------
ms_kinetics_avail = ms_kinetics_options[0]
ms_reaction = reaction_options[0] if reaction_options else ""
ms_semi_batch = "Off"
ms_semi_batch_options = ["Off", "On"]
ms_kinetics_md = ""
ms_step1_assess = ""

# ---------------------------------------------------------------------------
# State — Step 2 (phases)
# ---------------------------------------------------------------------------
ms_phases = ["Liquid"]
ms_step2_assess = ""

# ---------------------------------------------------------------------------
# State — Step 3 (competing reactions)
# ---------------------------------------------------------------------------
ms_competing = "— select —"
ms_step3_assess = ""

# ---------------------------------------------------------------------------
# State — Step 4 (heat transfer)
# ---------------------------------------------------------------------------
ms_show_dh_action = False
ms_dh_action = "— select —"
ms_dh_ref = dh_ref_options[0]
ms_rho_cp = 1800.0
ms_c0_heat = 1.0
ms_step4_assess = ""
ms_dt_ad_caption = ""

# ---------------------------------------------------------------------------
# State — Step 5 (mixing time)
# ---------------------------------------------------------------------------
ms_trxn_caption = ""
ms_step5_assess = ""

# ---------------------------------------------------------------------------
# State — Step 6 (summary) + Step 7 (export)
# ---------------------------------------------------------------------------
ms_started = False
ms_ready = False
ms_summary_note = ("*Set your inputs in the steps below, then click **Start assessment** to see "
                   "the overall verdict, findings, and recommended next steps.*")
ms_findings_df = pd.DataFrame(columns=["Sensitivity Type", "Finding"])
ms_verdict = ""
ms_nextsteps_df = pd.DataFrame(columns=["Area", "Recommended action"])

# cached values for the PDF snapshot
_ms_cache: dict = {}

ms_pdf_bytes = b""
ms_pdf_name = "Sensitivity_Protocol.pdf"
ms_pdf_ready = False


# ---------------------------------------------------------------------------
# Derivation of the Bourne pre-screen inputs
# ---------------------------------------------------------------------------
def _bourne_derive(state):
    """Return (sensitive: True/False/None, mechanisms: list, done_tests: list)."""
    status = state.ms_bourne_status
    done = sorted(int(t.split()[-1]) for t in (state.ms_bourne_tests or []))
    if status == "Ran — sensitivity confirmed":
        mech = state.ms_bourne_mech
        mechs = [mech] if mech in ("Micromixing", "Mesomixing", "Macromixing") else []
        return True, mechs, done
    if status == "Ran — no sensitivity at lab scale":
        return False, [], done
    if status == "Ran — inconclusive (Test 1 not completed)":
        return None, [], done
    return None, [], []  # not run / skip


# ---------------------------------------------------------------------------
# Central recompute — runs on every relevant input change
# ---------------------------------------------------------------------------
def _recompute(state):
    # No assessment is made until the user explicitly starts it (avoids showing
    # results for the default inputs on page load).
    if not getattr(state, "ms_started", False):
        return
    # ---- Step 0: Bourne pre-screen -------------------------------------
    b_sensitive, b_mechs, b_done = _bourne_derive(state)
    test_rows = state.ms_bourne_findings_df.to_dict("records") if not state.ms_bourne_findings_df.empty else []

    if state.ms_bourne_status == "Not run — skip pre-screen":
        state.ms_step0_assess = _amd(
            "caution", "**Bourne pre-screen skipped** — proceeding with the theoretical "
            "assessment. Running the Bourne Protocol gives a direct experimental answer.")
    elif b_sensitive is True:
        if b_mechs:
            state.ms_step0_assess = _amd(
                "critical", f"Bourne Protocol confirmed **mixing sensitivity** — the "
                f"controlling scale is **{b_mechs[0].lower()}**. Carried into the summary "
                "as an experimentally confirmed result.")
        else:
            rem = _remaining_tests(b_done)
            add = (f" Complete **{_fmt_tests(rem)}** ({_fmt_test_purposes(rem)}) to pinpoint "
                   "the controlling scale." if rem else "")
            state.ms_step0_assess = _amd(
                "critical", "Bourne Protocol confirmed **mixing sensitivity**, but the "
                "controlling scale is not yet resolved." + add)
    elif b_sensitive is False:
        state.ms_step0_assess = _amd(
            "ok", "Bourne Protocol showed **no mixing sensitivity** at lab scale (Test 1 "
            "response insensitive to impeller speed). The remaining steps check for latent "
            "risks at larger scale.")
    else:
        state.ms_step0_assess = _amd(
            "caution", "Bourne results **inconclusive** — Test 1 was not completed, so "
            "experimental mixing sensitivity is undetermined. Complete at least Test 1.")

    # ---- Step 1: kinetics ----------------------------------------------
    row = _reaction_row(state.ms_reaction)
    order = str(row.get("order", "1"))
    k = _sf(row.get("k_value"))
    C0 = _sf(row.get("C0_mol_L"))
    t_specified = _sf(row.get("t_rxn_s"))
    dH = _sf(row.get("delta_H_kJ_mol"))
    T = _sf(row.get("T_C"), 25.0)
    solvent = str(row.get("solvent", "") or "")
    rxn_type = str(row.get("type", "") or "")

    if t_specified > 0:
        t_rxn = t_specified
        t_basis = "specified directly"
    elif k > 0:
        if order in ("1", "pseudo-1"):
            t_rxn = 1.0 / k
            t_basis = f"1/k = 1/{k:.4g} s⁻¹"
        elif order in ("2", "pseudo-2") and C0 > 0:
            t_rxn = 1.0 / (k * C0)
            t_basis = f"1/(k·C₀) = 1/({k:.4g}×{C0:.4g})"
        else:
            t_rxn = 1.0
            t_basis = "fallback (order/C₀ incomplete)"
    else:
        t_rxn = 0.0
        t_basis = ""

    using_approx = state.ms_kinetics_avail.startswith("Approximate")
    kinetics_declined = state.ms_kinetics_avail.startswith("No")
    kinetics_ok = (t_rxn > 0) and not kinetics_declined
    # "known" = usable t_rxn for the Damköhler-based (theory) mechanisms;
    # "resolved" = the kinetics question has been answered (available OR declined),
    # which is enough to produce an overall verdict from the other evidence.
    kinetics_known = kinetics_ok
    kinetics_resolved = kinetics_ok or kinetics_declined

    n_sym = "k'" if order.startswith("pseudo") else "k"
    conc = {"0": "", "1": "·C", "2": "·C²"}.get(order.split("-")[-1] if order else "1", f"·C^{order}")
    law = f"−dC/dt = {n_sym}{conc}"
    if t_rxn > 0:
        state.ms_kinetics_md = (
            f"**Kinetic model** (order {order}): {law}\n\n"
            f"Characteristic reaction time **t_rxn = {t_rxn:.4g} s** ({t_basis}). "
            "This is the reaction time constant used in the Damköhler number "
            "(the e-folding time, not the half-life).")
    else:
        state.ms_kinetics_md = ("⚠️ Cannot determine a characteristic reaction time — "
                                "check k, C₀ and t_rxn in the Reaction Database.")

    if kinetics_declined:
        state.ms_step1_assess = _amd(
            "warning", "**Kinetics not yet available.** Measure them (e.g. by calorimetry / "
            "reaction monitoring), add the reaction to the database, and return here. A "
            "Bourne pre-screen can still give a direct experimental answer in the meantime.")
    elif not kinetics_ok:
        state.ms_step1_assess = _amd(
            "critical", "Cannot determine a characteristic reaction time from the selected "
            "reaction data.")
    elif using_approx:
        state.ms_step1_assess = _amd(
            "warning", "**Approximate kinetics** — t_rxn is based on a proxy reaction. All "
            "downstream conclusions are only valid if the proxy kinetics match the true "
            "reaction. Confirm with measured data.")
    else:
        state.ms_step1_assess = _amd("ok", "**Kinetics available** — characteristic reaction "
                                     "time shown above.")

    is_semi_batch = state.ms_semi_batch == "On"

    # ---- Step 2: phases -------------------------------------------------
    phases = list(state.ms_phases or [])
    multiphase = len(phases) > 1
    if not phases:
        state.ms_step2_assess = _amd("caution", "Select at least one phase to continue.")
    elif multiphase:
        state.ms_step2_assess = _amd(
            "warning", "**Multi-phase system** (" + " + ".join(phases) + ") — interphase mass "
            "transfer may limit the observed rate. Characterise kLa (gas–liquid) and/or k_SL "
            "(solid–liquid) and compute Da_GL / Da_SL for your reactor on the Vessel "
            "Assessment page.")
    else:
        state.ms_step2_assess = _amd(
            "ok", "**Single liquid phase** — interphase mass transfer is not a factor. Micro-, "
            "meso- and macromixing may still affect the reaction.")

    # ---- Step 3: competing reactions -----------------------------------
    competing = state.ms_competing
    competing_set = competing in ("Yes", "No", "Not sure")
    meso_sensitive = competing in ("Yes", "Not sure")
    if is_semi_batch and not meso_sensitive:
        meso_sensitive = True
    if not competing_set:
        state.ms_step3_assess = _amd("caution", "Select an option to continue.")
    elif competing == "Yes":
        state.ms_step3_assess = _amd(
            "critical", "**Competing reactions present** — both micromixing (local ε) and "
            "mesomixing (feed dispersion) can shift selectivity; likely mixing-sensitive.")
    elif competing == "Not sure":
        state.ms_step3_assess = _amd(
            "warning", "Treat as **potentially sensitive** until confirmed — a Bourne Protocol "
            "screen resolves whether micro/mesomixing affects selectivity.")
    elif is_semi_batch:
        state.ms_step3_assess = _amd(
            "warning", "No competing reactions, but this is a **semi-batch** process — "
            "mesomixing (feed-plume dispersion) is always relevant at the feed point.")
    else:
        state.ms_step3_assess = _amd(
            "ok", "**No competing reactions** in a batch process — micro/mesomixing unlikely "
            "to affect selectivity.")

    # ---- Step 4: heat transfer -----------------------------------------
    has_enthalpy = dH != 0.0
    dH_eff = dH
    state.ms_show_dh_action = not has_enthalpy
    heat_resolved = True
    dt_ad = None

    if not has_enthalpy:
        if state.ms_dh_action == "Estimate ΔH from a similar reaction":
            ref_row = _reaction_row(state.ms_dh_ref)
            dH_eff = _sf(ref_row.get("delta_H_kJ_mol"))
            has_enthalpy = dH_eff != 0.0
        elif state.ms_dh_action == "Perform calorimetry — measure ΔH experimentally":
            has_enthalpy = False
            heat_resolved = True
        else:
            heat_resolved = False

    abs_dH = abs(dH_eff)
    heat_sensitive = False
    heat_flagged_type = any(t in rxn_type.lower() for t in _KNOWN_HOT)

    if has_enthalpy:
        if state.ms_c0_heat > 0 and state.ms_rho_cp > 0:
            dt_ad = abs_dH * state.ms_c0_heat * 1000.0 / state.ms_rho_cp
        heat_flag = abs_dH >= 50 or (dt_ad is not None and dt_ad >= 50)
        heat_sensitive = heat_flag or heat_flagged_type
        if abs_dH >= 100:
            heat_class, heat_kind = "highly exothermic", "critical"
        elif abs_dH >= 50:
            heat_class, heat_kind = "moderately exothermic", "warning"
        elif abs_dH >= 20:
            heat_class, heat_kind = "mildly exothermic", "caution"
        else:
            heat_class, heat_kind = "low exothermicity", "ok"
        sign = "exothermic" if dH_eff < 0 else "endothermic"
        parts = [f"**{heat_class.title()}** {sign} reaction — |ΔH| = {abs_dH:.1f} kJ/mol"]
        if dt_ad is not None:
            parts.append(f"ΔT_ad ≈ {dt_ad:.0f} K")
        msg = ", ".join(parts) + "."
        if heat_flag:
            msg += (" Heat transfer is **likely sensitive** — run a heat balance (Vessel "
                    "Assessment) to confirm adequate cooling capacity (Q_gen vs Q_cool).")
        if heat_flagged_type:
            msg += (f" Reaction type **{rxn_type}** is commonly strongly exothermic — heat "
                    "assessment recommended regardless of the reported ΔH.")
        state.ms_step4_assess = _amd("critical" if heat_sensitive else heat_kind, msg)
        if dt_ad is not None:
            if dt_ad >= 200:
                sev = "🔴 Very high — loss of cooling could drive a runaway; assess MTSR vs T_D24 (Stoessel)."
            elif dt_ad >= 50:
                sev = "🔴 High — strong cooling and feed-rate control required."
            elif dt_ad >= 20:
                sev = "🟡 Moderate — manageable with adequate cooling; verify the heat balance at scale."
            else:
                sev = "🟢 Low — runaway unlikely, though feed-point hot spots may still occur."
            state.ms_dt_ad_caption = (f"ΔT_ad = |ΔH|·C₀·1000/(ρ·Cp) ≈ **{dt_ad:.0f} K**  —  {sev}")
        else:
            state.ms_dt_ad_caption = "Enter C₀ and ρ·Cp above to estimate ΔT_ad."
    else:
        if state.ms_dh_action == "Perform calorimetry — measure ΔH experimentally":
            state.ms_step4_assess = _amd(
                "caution", "Heat-transfer risk **cannot be evaluated without ΔH** — measure it "
                "by reaction calorimetry (RC1 / µRC), add it to the Reaction Database, and "
                "return here.")
        elif not heat_resolved:
            state.ms_step4_assess = _amd(
                "unknown", "No ΔH data for this reaction — choose how to proceed above "
                "(measure by calorimetry, or estimate from a similar reaction).")
        else:
            state.ms_step4_assess = _amd("unknown", "No ΔH data available — consider calorimetry.")
        state.ms_dt_ad_caption = ""

    # ---- Step 5: mixing time vs reaction time --------------------------
    if kinetics_known and t_rxn > 0:
        state.ms_trxn_caption = f"Your reaction time: **t_rxn = {t_rxn:.4g} s**."
        if t_rxn < 0.1:
            state.ms_step5_assess = _amd(
                "critical", "**Very fast reaction** — micromixing-sensitive in most reactor "
                "configurations. Local turbulent energy dissipation near the impeller, feed "
                "location, and tip speed are critical.")
            micro_likely = True
        elif t_rxn < 1.0:
            state.ms_step5_assess = _amd(
                "warning", "**Fast reaction** — micromixing likely relevant in larger vessels "
                "where local ε at the feed point decreases. Confirm with Damköhler analysis.")
            micro_likely = True
        elif t_rxn < 10:
            state.ms_step5_assess = _amd(
                "caution", "**Moderate reaction** — micromixing less likely to dominate, but "
                "macromixing (blend time) could matter in larger vessels. Check blend time vs "
                "t_rxn.")
            micro_likely = False
        else:
            state.ms_step5_assess = _amd(
                "ok", "**Slow reaction** — mixing is unlikely to limit the reaction in "
                "well-agitated vessels.")
            micro_likely = False
    else:
        state.ms_trxn_caption = ""
        if kinetics_declined:
            state.ms_step5_assess = _amd(
                "unknown", "Reaction kinetics not available — the mixing-time vs reaction-time "
                "comparison cannot be evaluated. A Bourne pre-screen (Test 1) gives a direct "
                "experimental answer.")
        else:
            state.ms_step5_assess = ""
        micro_likely = False

    # ---- Step 6: findings, verdict, next steps -------------------------
    findings = _build_findings(
        b_sensitive, b_mechs, b_done, test_rows, t_rxn, micro_likely,
        meso_sensitive, competing, is_semi_batch, multiphase, phases,
        has_enthalpy, heat_sensitive, dH_eff, dt_ad, kinetics_known)
    verdict, verdict_kind = _build_verdict(
        b_sensitive, b_mechs, b_done, findings, competing)
    next_steps = _build_next_steps(
        b_sensitive, b_mechs, using_approx, micro_likely, t_rxn, meso_sensitive,
        multiphase, has_enthalpy, heat_sensitive, is_semi_batch, kinetics_known,
        kinetics_declined)

    state.ms_ready = bool(kinetics_resolved and phases and competing_set and heat_resolved)

    state.ms_findings_df = pd.DataFrame(
        [{"Sensitivity Type": m, "Finding": f"{s} — {d}"} for m, s, d in findings])
    state.ms_nextsteps_df = pd.DataFrame(next_steps)
    if state.ms_ready:
        state.ms_verdict = verdict
        state.ms_summary_note = ""
    else:
        state.ms_verdict = ""
        state.ms_summary_note = ("*Complete Steps 1–4 — select a reaction with kinetics, at "
                                 "least one phase, whether competing reactions are present, and "
                                 "resolve ΔH — to see the overall verdict.*")

    # invalidate a previously generated PDF (inputs changed)
    state.ms_pdf_ready = False

    # cache for the PDF snapshot
    bourne_txt = {
        True: "Mixing sensitivity confirmed", False: "No sensitivity observed",
        None: "Not performed / undetermined"}[b_sensitive]
    state._ms_cache = {
        "reaction": state.ms_reaction, "t_rxn": t_rxn, "rxn_delta_H": dH_eff,
        "dT_ad": dt_ad, "phases": phases, "findings": findings, "next_steps": next_steps,
        "bourne_result": bourne_txt, "bourne_tests": test_rows,
        "bourne_mechanism": b_mechs[0] if b_mechs else "",
        "bourne_meta": _ms_meta_from_caption(state.ms_bourne_meta_caption),
        "competing": competing if competing_set else "Not assessed",
        "overall_verdict": _strip_md(verdict), "using_approximate": using_approx,
        "is_semi_batch": is_semi_batch,
    }


def _ms_meta_from_caption(_caption: str) -> dict:
    return {}


def _strip_md(text: str) -> str:
    return text.replace("**", "").replace("🔴", "").replace("🟡", "").replace("🟢", "").strip()


# ---------------------------------------------------------------------------
# Findings / verdict / next-steps builders (faithful to the Streamlit logic)
# ---------------------------------------------------------------------------
def _build_findings(b_sensitive, b_mechs, b_done, test_rows, t_rxn, micro_likely,
                    meso_sensitive, competing, is_semi_batch, multiphase, phases,
                    has_enthalpy, heat_sensitive, dH_eff, dt_ad, kinetics_known):
    findings: list[tuple[str, str, str]] = []
    kpi_phrase = _sensitive_kpi_phrase(test_rows)
    rem = _remaining_tests(b_done)
    rem_action = (f"complete {_fmt_tests(rem)} of the Bourne Protocol" if rem
                  else "re-run the Bourne Protocol decision tree")

    # Bourne pre-screen
    if b_sensitive is True:
        if b_mechs:
            findings.append(("Bourne pre-screen", "🔴 Mixing sensitivity confirmed",
                             f"Experimental pre-screen showed {kpi_phrase} changed with mixing "
                             f"conditions. Controlling scale(s): {', '.join(b_mechs)}."))
        else:
            findings.append(("Bourne pre-screen", "🔴 Mixing sensitivity confirmed",
                             f"Experimental pre-screen showed {kpi_phrase} changed with mixing "
                             f"conditions. Controlling scale not yet identified — {rem_action}."))
    elif b_sensitive is False:
        findings.append(("Bourne pre-screen", "🟢 No sensitivity observed",
                         "Experimental pre-screen showed no mixing sensitivity at lab scale."))
    else:
        findings.append(("Bourne pre-screen", "⚪ Not performed",
                         "Consider running Bourne Protocol Part 1 for a direct experimental answer."))

    # Micromixing
    if not kinetics_known:
        findings.append(("Micromixing", "⚪ Unknown",
                         "Reaction kinetics not available — micromixing cannot be assessed from "
                         "t_rxn. A Bourne pre-screen (Test 1) gives a direct experimental answer."))
    elif micro_likely:
        findings.append(("Micromixing", "🔴 Likely sensitive",
                         f"t_rxn = {t_rxn:.4g} s — fast enough that local energy dissipation "
                         "controls the mixing rate."))
    else:
        findings.append(("Micromixing", "🟢 Unlikely",
                         f"t_rxn = {t_rxn:.4g} s — slow relative to typical micromixing times."))

    # Micro/mesomixing (selectivity)
    if meso_sensitive:
        if is_semi_batch and competing == "No":
            findings.append(("Mesomixing (feed-plume)", "🟡 Semi-batch — check experimentally",
                             "No competing reactions, but feed-plume dispersion controls local "
                             "concentration. Vary feed rate and location (Bourne Tests 2 & 3)."))
        else:
            findings.append(("Micro/mesomixing (selectivity)",
                             "🟡 Potentially sensitive" if competing == "Not sure" else "🔴 Likely sensitive",
                             "Competing reactions present — both micromixing (local ε) and "
                             "mesomixing (feed dispersion) may affect selectivity."))
    else:
        findings.append(("Micro/mesomixing (selectivity)", "🟢 Not a factor",
                         "No competing reactions; batch process (no feed addition)."))

    # Macromixing
    if not kinetics_known:
        findings.append(("Macromixing (blend time)", "⚪ Unknown",
                         "Reaction kinetics not available — t_rxn cannot be compared to the "
                         "vessel blend time."))
    elif t_rxn < 60:
        findings.append(("Macromixing (blend time)", "🟡 Check at scale",
                         f"t_rxn = {t_rxn:.4g} s is within the range of blend times in larger "
                         "vessels (10–120 s). Compute Da_macro for your reactor."))
    else:
        findings.append(("Macromixing (blend time)", "🟢 Unlikely",
                         f"t_rxn = {t_rxn:.4g} s is much longer than typical blend times."))

    # Mass transfer
    if multiphase:
        findings.append((f"Mass transfer ({' + '.join(phases)})", "🟡 System-dependent",
                         "Multi-phase system — interphase transport may limit the observed rate. "
                         "Characterise kLa and/or k_SL for each reactor."))
    else:
        findings.append(("Mass transfer", "🟢 Not applicable",
                         "Single liquid phase — no interphase transport."))

    # Heat transfer
    if has_enthalpy and heat_sensitive:
        detail = f"|ΔH| = {abs(dH_eff):.1f} kJ/mol"
        if dt_ad is not None:
            detail += f", ΔT_ad ≈ {dt_ad:.0f} K"
        findings.append(("Heat transfer", "🔴 Likely sensitive",
                         f"{detail} — run a heat balance to confirm adequate cooling capacity."))
    elif has_enthalpy and not heat_sensitive:
        detail = f"|ΔH| = {abs(dH_eff):.1f} kJ/mol"
        if dt_ad is not None:
            detail += f", ΔT_ad ≈ {dt_ad:.0f} K"
        findings.append(("Heat transfer", "🟢 Manageable",
                         f"{detail} — modest thermal load, unlikely to be limiting in most "
                         "configurations."))
    else:
        findings.append(("Heat transfer", "⚪ Unknown",
                         "No ΔH data available — consider measuring by calorimetry."))

    # Semi-batch
    if is_semi_batch:
        findings.append(("Semi-batch (fed-batch)", "🟡 Feed-point sensitive",
                         "Mesomixing (feed-plume dispersion) controls local concentration, heat "
                         "release and supersaturation at the feed point."))
    return findings


def _build_verdict(b_sensitive, b_mechs, b_done, findings, competing):
    mech_findings = [f for f in findings if f[0] != "Bourne pre-screen"]
    n_red = sum(1 for _, s, _ in mech_findings if "🔴" in s)
    n_yellow = sum(1 for _, s, _ in mech_findings if "🟡" in s)
    red_mechs = [m for m, s, _ in mech_findings if "🔴" in s]
    rem = _remaining_tests(b_done)
    rem_action = (f"complete {_fmt_tests(rem)} of the Bourne Protocol" if rem
                  else "re-run the Bourne Protocol decision tree")

    if b_sensitive is True:
        if b_mechs:
            return (f"🔴 **Mixing sensitivity confirmed** — the Bourne Protocol identified "
                    f"**{_join_mechs(b_mechs)}** as the controlling scale(s). Focus scale-up "
                    "efforts on this mechanism (see recommendations below)."), "critical"
        if red_mechs:
            return (f"🔴 **Mixing sensitivity confirmed** — the reaction may be "
                    f"**{_join_mechs(red_mechs)} limited**, and the Bourne pre-screen confirms a "
                    "sensitivity is present. Detailed characterisation is recommended to identify "
                    "the controlling mechanism."), "critical"
        if n_yellow >= 1:
            return ("🔴 **Mixing sensitivity confirmed** — the Bourne pre-screen shows a "
                    "sensitivity is present. The theory did not flag a specific mechanism as "
                    f"likely, but some items require verification at scale. To pinpoint the "
                    f"controlling scale, {rem_action}."), "critical"
        return ("🔴 **Mixing sensitivity confirmed** — the Bourne pre-screen shows an experimental "
                "sensitivity even though the theory flagged no mechanism. Revisit the inputs "
                f"(kinetics, phases, feed strategy) and {rem_action}."), "critical"

    if b_sensitive is False:
        if red_mechs:
            return (f"🟡 **Possible scale-dependent sensitivity** — the Bourne pre-screen showed "
                    f"no sensitivity at lab scale, but the assessment flags **{_join_mechs(red_mechs)}** "
                    "as likely to become limiting at larger scale. Confirm with Damköhler analysis "
                    "before scale-up."), "warning"
        if n_yellow >= 1:
            return ("🟢 **Low mixing sensitivity risk** — the Bourne pre-screen showed no "
                    "sensitivity and no mechanism is flagged as likely, though a few items warrant "
                    "a check at scale."), "ok"
        return ("🟢 **Low mixing sensitivity risk** — the Bourne pre-screen showed no sensitivity "
                "and no mixing mechanism is expected to limit this reaction."), "ok"

    # Bourne not performed — theory only
    if n_red >= 2:
        return (f"🔴 **High mixing sensitivity risk** — multiple mechanisms "
                f"(**{_join_mechs(red_mechs)}**) are likely to limit this reaction at scale. "
                "Detailed characterisation is strongly recommended; a Bourne pre-screen would "
                "provide direct experimental confirmation."), "critical"
    if n_red == 1:
        return (f"🟡 **Moderate mixing sensitivity risk** — **{_join_mechs(red_mechs)}** is likely "
                "to be sensitive. Targeted investigation is recommended; a Bourne pre-screen would "
                "confirm whether a sensitivity is present experimentally."), "warning"
    if n_yellow >= 1:
        return ("🟡 **Low-to-moderate mixing sensitivity risk** — no mechanisms are flagged as "
                "likely sensitive, but some require verification at scale. A Bourne pre-screen "
                "would provide a direct experimental answer."), "warning"
    return ("🟢 **Low mixing sensitivity risk** — no mixing mechanisms are expected to limit this "
            "reaction under typical operating conditions."), "ok"


def _build_next_steps(b_sensitive, b_mechs, using_approx, micro_likely, t_rxn,
                      meso_sensitive, multiphase, has_enthalpy, heat_sensitive, is_semi_batch,
                      kinetics_known, kinetics_declined):
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
    if has_enthalpy and heat_sensitive:
        steps.append({"Area": "Heat transfer",
                      "Recommended action": "Run a heat balance (Vessel Assessment) to quantify "
                      "Q_gen vs Q_cool."})
    if is_semi_batch:
        steps.append({"Area": "Semi-batch",
                      "Recommended action": "Run the full Bourne Protocol: vary impeller speed, "
                      "feed rate/time, and feed location."})
    if not steps:
        steps.append({"Area": "General",
                      "Recommended action": "Low risk; standard scale-up practices are sufficient."})
    return steps


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------
def on_ms_reaction_change(state):
    row = _reaction_row(state.ms_reaction)
    solvent = str(row.get("solvent", "") or "")
    T = _sf(row.get("T_C"), 25.0)
    C0 = _sf(row.get("C0_mol_L"))
    # auto-fill volumetric heat capacity from the solvent when known
    if solvent and is_known_solvent(solvent):
        try:
            p = get_properties(solvent, T, 1.0)
            state.ms_rho_cp = round(p["rho_kg_m3"] * p["Cp_J_per_kgK"] / 1000.0, 1)
        except Exception:  # noqa: BLE001
            pass
    state.ms_c0_heat = round(C0, 4) if C0 > 0 else 1.0
    _safe_recompute(state)


def on_ms_change(state):
    _safe_recompute(state)


def _safe_recompute(state):
    """Recompute all assessments; surface any error instead of leaving them stale."""
    try:
        _recompute(state)
    except Exception as exc:  # noqa: BLE001 - never leave the UI silently stale
        notify(state, "E", f"Assessment update failed: {exc}")


def on_ms_bourne_import(state):
    path = state.ms_bourne_upload
    if not path:
        return
    try:
        df = pd.read_csv(path, dtype=str, keep_default_na=False)
    except Exception as exc:  # noqa: BLE001
        notify(state, "E", f"Could not read the file: {exc}")
        return
    if not ({"field", "value"} <= set(df.columns)):
        notify(state, "E", "Not a Bourne results CSV (expected 'field','value' columns).")
        return
    d = dict(zip(df["field"], df["value"]))
    if d.get("record_type") != "bourne_results":
        notify(state, "E", "That CSV is not a Bourne Protocol results export.")
        return
    # map into the manual-entry controls
    overall = (d.get("overall_sensitive") or "unknown").strip()
    if overall == "yes":
        state.ms_bourne_status = "Ran — sensitivity confirmed"
    elif overall == "no":
        state.ms_bourne_status = "Ran — no sensitivity at lab scale"
    else:
        state.ms_bourne_status = "Ran — inconclusive (Test 1 not completed)"
    dom = (d.get("dominant_mechanism") or "").strip()
    state.ms_bourne_mech = dom if dom in ("Micromixing", "Mesomixing", "Macromixing") else "Not resolved"
    done, rows = [], []
    names = {1: "Test 1 — Impeller speed", 2: "Test 2 — Feed rate/time", 3: "Test 3 — Feed location"}
    for n in (1, 2, 3):
        assessed = (d.get(f"test{n}_assessed") or d.get(f"test{n}_completed") or "no") == "yes"
        if not assessed:
            continue
        done.append(f"Test {n}")
        rows.append({"Test": names[n], "Finding": (d.get(f"test{n}_finding") or "—").strip() or "—",
                     "Sensitive KPI(s)": (d.get(f"test{n}_sensitive_kpis") or "").strip()
                     or "None (no KPI over threshold)"})
    state.ms_bourne_tests = done or ["Test 1"]
    state.ms_bourne_findings_df = pd.DataFrame(rows) if rows else pd.DataFrame(
        columns=["Test", "Finding", "Sensitive KPI(s)"])
    meta_bits = []
    for lbl, fld in [("Project", "project_name"), ("Reactor", "reactor"), ("Fluid", "fluid")]:
        v = (d.get(fld) or "").strip()
        if v:
            meta_bits.append(f"**{lbl}:** {v}")
    state.ms_bourne_meta_caption = "Imported Bourne results — " + "  •  ".join(meta_bits) if meta_bits else ""
    notify(state, "S", "Bourne results imported.")
    _recompute(state)


def on_ms_export_pdf(state):
    if not state.ms_ready:
        notify(state, "W", "Complete the assessment (Steps 1–4) before exporting.")
        return
    try:
        snap = dict(state._ms_cache)
        snap["bourne_meta"] = _ms_meta_from_caption(state.ms_bourne_meta_caption)
        state.ms_pdf_bytes = build_protocol_pdf(snap)
        state.ms_pdf_name = report_filename("Sensitivity_Protocol", state.ms_reaction)
        state.ms_pdf_ready = True
        notify(state, "S", "PDF report generated — click Download.")
    except Exception as exc:  # noqa: BLE001
        notify(state, "E", f"PDF generation failed: {exc}")


def on_ms_init(state):
    """Start (or refresh) the assessment once the user has set the inputs."""
    state.ms_started = True
    on_ms_reaction_change(state)


def on_ms_reset(state):
    """Reset every input back to its default and clear all results/recommendations."""
    # inputs
    state.ms_bourne_status = ms_bourne_status_options[0]
    state.ms_bourne_mech = "Not resolved"
    state.ms_bourne_tests = ["Test 1"]
    state.ms_bourne_upload = ""
    state.ms_kinetics_avail = ms_kinetics_options[0]
    state.ms_reaction = reaction_options[0] if reaction_options else ""
    state.ms_semi_batch = "Off"
    state.ms_phases = ["Liquid"]
    state.ms_competing = "— select —"
    state.ms_dh_action = "— select —"
    state.ms_dh_ref = dh_ref_options[0]
    state.ms_rho_cp = 1800.0
    state.ms_c0_heat = 1.0
    # computed outputs
    state.ms_step0_assess = ""
    state.ms_step1_assess = ""
    state.ms_step2_assess = ""
    state.ms_step3_assess = ""
    state.ms_step4_assess = ""
    state.ms_step5_assess = ""
    state.ms_kinetics_md = ""
    state.ms_trxn_caption = ""
    state.ms_dt_ad_caption = ""
    state.ms_show_dh_action = False
    state.ms_bourne_meta_caption = ""
    state.ms_bourne_findings_df = pd.DataFrame(columns=["Test", "Finding", "Sensitive KPI(s)"])
    state.ms_findings_df = pd.DataFrame(columns=["Sensitivity Type", "Finding"])
    state.ms_nextsteps_df = pd.DataFrame(columns=["Area", "Recommended action"])
    state.ms_verdict = ""
    state.ms_summary_note = ("*Set your inputs in the steps below, then click **Start assessment** "
                             "to see the overall verdict, findings, and recommended next steps.*")
    state.ms_pdf_ready = False
    state.ms_pdf_bytes = b""
    # back to the pre-start state so no results are shown
    state.ms_ready = False
    state.ms_started = False
    notify(state, "I", "Assessment reset — set your inputs and start again.")


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------
page = Markdown(
    inject_icons("""
# __ICON:Mixing_Sensitivity__Reaction Sensitivity Protocol

A guided decision tree to determine **whether a reaction is sensitive to mixing**
and, if so, **which mechanism controls** it — micromixing, mesomixing,
macromixing, interphase mass transport, or heat transfer. Work through the steps;
the **Summary** synthesises everything into an overall verdict.

<|part|height=18px|>

<|Decision-tree flowsheet|expandable|expanded=False|
<|part|content={ms_decision_tree_html}|height=620px|>
|>

<|part|height=18px|>

<|part|render={not ms_started}|
**Set your inputs in the steps below, then click _Start assessment_ at the bottom
of the page.** No results are shown until you do.
|>

<|part|render={ms_started}|
<|Reset assessment|button|on_action=on_ms_reset|class_name=compute-btn|>
|>

<|part|height=18px|>

<|part|class_name=va-card|
## Step 0 — Bourne Protocol Pre-Screen
Independent experimental evidence of whether a mixing sensitivity exists. If you
have run the Bourne Protocol, enter the outcome (or import its results CSV).

<|layout|columns=1 1 1|class_name=form-grid|
<|{ms_bourne_status}|selector|lov={ms_bourne_status_options}|dropdown|label=Bourne outcome|on_change=on_ms_change|>

<|{ms_bourne_mech}|selector|lov={ms_bourne_mech_options}|dropdown|label=Controlling scale identified|on_change=on_ms_change|active={ms_bourne_status == "Ran — sensitivity confirmed"}|>

<|{ms_bourne_tests}|selector|lov={ms_bourne_tests_options}|multiple|dropdown|label=Tests completed|on_change=on_ms_change|>
|>

<|{ms_bourne_upload}|file_selector|label=Import Bourne results CSV (optional)|on_action=on_ms_bourne_import|extensions=.csv|>

<|part|render={ms_bourne_meta_caption != ""}|
<|{ms_bourne_meta_caption}|text|mode=markdown|>
|>

<|part|render={len(ms_bourne_findings_df) > 0}|
<|{ms_bourne_findings_df}|table|width=100%|show_all|>
|>

<|part|render={ms_started}|class_name=result-box|
<|{ms_step0_assess}|text|mode=markdown|>
|>
|>

<|part|class_name=va-card|
## Step 1 — Reaction Kinetics
The characteristic reaction time **t_rxn** (1/k or 1/(k·C₀)) is the Damköhler
reference timescale for every mechanism below.

<|layout|columns=1 1|class_name=form-grid|
<|{ms_kinetics_avail}|selector|lov={ms_kinetics_options}|dropdown|label=Are kinetics available?|on_change=on_ms_change|>

<|{ms_reaction}|selector|lov={reaction_options}|dropdown|label=Reaction|on_change=on_ms_reaction_change|>
|>

<|{ms_semi_batch}|toggle|lov={ms_semi_batch_options}|label=Semi-batch (fed-batch) process|class_name=onoff-toggle|on_change=on_ms_change|>

<|part|render={ms_started}|class_name=result-box|
<|{ms_kinetics_md}|text|mode=markdown|>

<|{ms_step1_assess}|text|mode=markdown|>
|>
|>

<|part|class_name=va-card|
## Step 2 — Phase Assessment
Multi-phase systems can be limited by **interphase mass transfer** (gas→liquid
kLa, or solid dissolution k_SL) before mixing even matters.

<|{ms_phases}|selector|lov={ms_phase_options}|multiple|dropdown|label=Which phases are present?|on_change=on_ms_change|class_name=form-grid|>

<|part|render={ms_started}|class_name=result-box|
<|{ms_step2_assess}|text|mode=markdown|>
|>
|>

<|part|class_name=va-card|
## Step 3 — Competing Reactions
When parallel/consecutive reactions compete for a reagent, incomplete
**micromixing** (molecular scale) and **mesomixing** (feed-plume scale) shift
selectivity.

<|{ms_competing}|selector|lov={ms_competing_options}|dropdown|label=Are there competing reactions?|on_change=on_ms_change|class_name=form-grid|>

<|part|render={ms_started}|class_name=result-box|
<|{ms_step3_assess}|text|mode=markdown|>
|>
|>

<|part|class_name=va-card|
## Step 4 — Heat Transfer Screening
Exothermicity is judged by the **adiabatic temperature rise**
ΔT_ad = |ΔH|·C₀·1000/(ρ·Cp) — the rise with no cooling — not by ΔH per mole alone.

<|part|render={ms_show_dh_action}|
The selected reaction has **no ΔH data**. Choose how to proceed:
<|layout|columns=1 1|class_name=form-grid|
<|{ms_dh_action}|selector|lov={ms_dh_action_options}|dropdown|label=ΔH source|on_change=on_ms_change|>

<|{ms_dh_ref}|selector|lov={dh_ref_options}|dropdown|label=Reference reaction for ΔH|on_change=on_ms_change|active={ms_dh_action == "Estimate ΔH from a similar reaction"}|>
|>
|>

<|layout|columns=1 1|class_name=form-grid|
<|{ms_rho_cp}|number|label=Volumetric heat capacity ρ·Cp (kJ/m³·K)|on_change=on_ms_change|>

<|{ms_c0_heat}|number|label=Limiting-reagent C₀ (mol/L)|on_change=on_ms_change|>
|>

<|part|render={ms_started}|class_name=result-box|
<|{ms_dt_ad_caption}|text|mode=markdown|>

<|{ms_step4_assess}|text|mode=markdown|>
|>
|>

<|part|class_name=va-card|
## Step 5 — Mixing Time vs Reaction Time
The Damköhler number Da = t_mix / t_rxn; when Da > 1 the reaction outpaces mixing
and is mixing-sensitive. Micromixing t_E ≈ 17.3·√(ν/ε); macromixing (blend time)
θ₉₅ = 5.2·V/(N_Q·N·D³), which grows ∝ T^(2/3) with scale.

<|part|render={ms_step5_assess != ""}|class_name=result-box|
<|{ms_trxn_caption}|text|mode=markdown|>

<|{ms_step5_assess}|text|mode=markdown|>
|>
|>

<|part|render={not ms_started}|class_name=va-card|
### Ready?
You've worked through the steps above — start the assessment to generate the
per-step findings and the overall verdict.

<|Start assessment|button|on_action=on_ms_init|class_name=compute-btn|>
|>

<|part|class_name=va-card|
## Step 6 — Summary & Recommendations
<|{ms_summary_note}|text|mode=markdown|>

<|part|render={ms_ready}|class_name=result-box|
### Overall verdict
<|{ms_verdict}|text|mode=markdown|>

### Sensitivity findings
<|{ms_findings_df}|table|width=100%|show_all|>

<|part|render={len(ms_bourne_findings_df) > 0}|
### Bourne Protocol experimental findings
<|{ms_bourne_findings_df}|table|width=100%|show_all|>
|>

### Recommended next steps
<|{ms_nextsteps_df}|table|width=100%|show_all|>
|>
|>

<|part|render={ms_ready}|class_name=va-card|
## Step 7 — Export Report
Generate a PDF capturing the inputs, findings, overall verdict, and next steps.

<|Generate PDF report|button|on_action=on_ms_export_pdf|class_name=compute-btn|>

<|part|render={ms_pdf_ready}|
<|Download PDF|file_download|content={ms_pdf_bytes}|name={ms_pdf_name}|label=Download PDF|>
|>
|>
""")
)
