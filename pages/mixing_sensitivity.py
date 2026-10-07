"""Reaction Sensitivity Protocol page (Taipy).

Ported from the Streamlit ``10_Mixing_Sensitivity_Protocol.py`` page. A guided,
decision-tree assessment that determines **whether a reaction is sensitive to
mixing** and, if so, **which mechanism controls** it - micromixing, mesomixing,
macromixing, interphase mass transport, or heat transfer.

The workflow synthesises up to seven inputs into an overall verdict:

* **Step 0 - Bourne pre-screen:** experimental evidence (if available) that a
  mixing sensitivity exists (and, when Bourne Tests 1–3 are complete, which
  scale controls it). Independent of the theory below and combined with it.
* **Step 1 - Kinetics:** the characteristic reaction time ``t_rxn`` (1/k or
  1/(k·C₀)), the Damköhler reference timescale.
* **Step 2 - Phases:** single vs multi-phase → interphase mass-transfer risk.
* **Step 3 - Competing reactions:** micro-/mesomixing selectivity risk.
* **Step 4 - Heat transfer:** exothermicity and the adiabatic temperature rise
  ``ΔT_ad = |ΔH|·C₀·1000/(ρ·Cp)``.
* **Step 5 - Mixing time vs reaction time:** micro-/macromixing likelihood from
  the magnitude of ``t_rxn``.
* **Step 6 - Summary:** the classification decision tree → overall verdict,
  findings table, and recommended next steps.
* **Step 7 - Export:** a PDF report (``build_protocol_pdf``).

The Bourne pre-screen can be entered manually or imported from a Bourne
Protocol results CSV (the same ``field,value`` export produced on that page).
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
from taipy.gui import Markdown, download, notify

from pages._menu_icons import inject_icons
from reports.pdf import build_protocol_pdf, report_filename, report_header_label
from core import bourne_io
from core import kinetics
from core import operating_point as op
from core import sensitivity_rules as rules
from core.options import (
    BOURNE_TESTS, BourneStatus, Competing, DhAction, DhBasis, Kinetics, Mechanism, Phase, Toggle,
    bourne_test_number, is_on,
)
from core.records import (
    range_midpoint as _mid,
    reaction_row as _reaction_row,
    reactor_row as _reactor_row,
    sf as _sf,
    solvent_props as _solvent_props,
)
from pages import _db_common as db
from reports import snapshots
from pages._vessel_media import build_image_html
from core import catalog

IMAGES_DIR = Path(__file__).resolve().parent.parent / "images" / "general"
ms_decision_tree_html = build_image_html(
    IMAGES_DIR / "mixing_sensitivity_protocol.png", alt="Reaction mixing sensitivity protocol")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _update_rho_cp(state, solvent: str, T_C: float) -> None:
    p = _solvent_props(solvent, T_C)
    if p:
        state.ms_rho_cp = round(p["rho_kg_m3"] * p["Cp_J_per_kgK"] / 1000.0, 1)


# Aliases kept for tests that import page-private names.
_mesomixing_risk = rules.mesomixing_risk
_damkohler_screening_note = rules.damkohler_screening_note
_reaction_timescale_profile = kinetics.timescale_profile
_heat_transfer_summary = rules.heat_transfer_summary


# ---------------------------------------------------------------------------
# Option lists
# ---------------------------------------------------------------------------
reaction_class_options = catalog.reaction_names("yes")
reaction_measured_options = catalog.reaction_names("no")
reaction_options = reaction_measured_options or reaction_class_options
dh_ref_options = catalog.reactions_with_enthalpy() or ["(none available)"]

_SELECT = "- select -"
_NOT_RESOLVED = "Not resolved"
ms_kinetics_options = Kinetics.labels()
ms_bourne_status_options = BourneStatus.labels()
ms_bourne_mech_options = [_NOT_RESOLVED] + Mechanism.labels()
ms_bourne_tests_options = list(BOURNE_TESTS.values())
ms_phase_options = Phase.labels()
ms_competing_options = [_SELECT] + Competing.labels()
ms_dh_action_options = [_SELECT] + DhAction.labels()
# Labels referenced by the page's `active=` expressions.
ms_lbl_confirmed = BourneStatus.CONFIRMED.label
ms_lbl_estimate = DhAction.ESTIMATE.label
ms_unit_operation_options = ["- select -", "Reaction", "Quench", "Crystallization",
                             "Liquid-Liquid Extraction", "Distillation", "Filtration",
                             "Drying", "Other"]


# ---------------------------------------------------------------------------
# State - Project Information
# ---------------------------------------------------------------------------
ms_project_name = ""
ms_step_text = ""
ms_unit_operation = ms_unit_operation_options[0]
ms_process_version = ""


# ---------------------------------------------------------------------------
# State - Step 0 (Bourne pre-screen)
# ---------------------------------------------------------------------------
ms_bourne_status = ms_bourne_status_options[0]
ms_bourne_mech = _NOT_RESOLVED
ms_bourne_tests = [BOURNE_TESTS[1]]
ms_bourne_upload = ""
ms_step0_assess = ""
ms_bourne_findings_df = pd.DataFrame(columns=["Test", "Finding", "Sensitive KPI(s)"])
ms_bourne_meta = {}
ms_bourne_meta_caption = ""

# ---------------------------------------------------------------------------
# State - Step 1 (kinetics)
# ---------------------------------------------------------------------------
ms_kinetics_avail = ms_kinetics_options[0]
ms_reaction = reaction_options[0] if reaction_options else ""
ms_reaction_options = reaction_options
ms_rxn_order_options = kinetics.ORDER_OPTIONS
_kin_defaults = kinetics.kinetics_defaults


def _sync_reaction_options(state) -> None:
    """Use measured kinetics for confirmed data and class proxies otherwise."""
    use_classes = Kinetics.from_label(state.ms_kinetics_avail) is Kinetics.APPROXIMATE
    options = reaction_class_options if use_classes else reaction_measured_options
    state.ms_reaction_options = options or ["(none available)"]
    if state.ms_reaction not in state.ms_reaction_options:
        state.ms_reaction = state.ms_reaction_options[0]


_kd0 = _kin_defaults(ms_reaction)
ms_rxn_order = _kd0["order"]
ms_rxn_k = _kd0["k"]
ms_rxn_c0 = _kd0["C0"]
ms_rxn_trxn = _kd0["t_rxn"]
ms_rxn_T = _kd0["T"]
ms_rxn_dh = _kd0["dH"]
ms_semi_batch = Toggle.OFF.label
ms_semi_batch_options = Toggle.labels()
ms_kinetics_md = ""
ms_step1_assess = ""

# ---------------------------------------------------------------------------
# State - Step 2 (phases)
# ---------------------------------------------------------------------------
ms_phases = [Phase.LIQUID.label]
ms_step2_assess = ""

# ---------------------------------------------------------------------------
# State - Step 3 (competing reactions)
# ---------------------------------------------------------------------------
ms_competing = _SELECT
ms_step3_assess = ""

# ---------------------------------------------------------------------------
# State - Step 4 (heat transfer)
# ---------------------------------------------------------------------------
ms_show_dh_action = False
ms_dh_action = _SELECT
ms_dh_ref = dh_ref_options[0]
ms_dh_override = 0.0                        # kJ/mol, 0 = use the Step 1 / proxy value
ms_dh_measured = DhBasis.ESTIMATED.label    # measured-ness of the override ΔH
ms_dh_measured_options = DhBasis.labels()
ms_rho_cp = 1800.0
ms_c0_heat = 1.0
ms_step4_assess = ""
ms_dt_ad_caption = ""

# ---------------------------------------------------------------------------
# State - Step 5 (mixing time) - optional reactor-specific Damköhler screen
# ---------------------------------------------------------------------------
ms_trxn_caption = ""
ms_step5_assess = ""
ms_da_mode = Toggle.OFF.label
ms_da_mode_options = Toggle.labels()
ms_da_reactor_options = catalog.reactor_names()
ms_da_reactor = ("TMA EasyMax-102" if "TMA EasyMax-102" in ms_da_reactor_options
                 else (ms_da_reactor_options[0] if ms_da_reactor_options else ""))
_da_r0 = _reactor_row(ms_da_reactor)
ms_da_rpm = _mid(_da_r0, "N_rpm_min", "N_rpm_max", 300.0)
ms_da_vl = _mid(_da_r0, "V_L_min", "V_L_max", _sf(_da_r0.get("V_L"), 1.0))
ms_da_caption = ""

# ---------------------------------------------------------------------------
# State - Step 6 (summary) + Step 7 (export)
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
# Page answers (labels) -> core.sensitivity_rules.ProtocolInputs (codes)
# ---------------------------------------------------------------------------
def _protocol_inputs(state) -> rules.ProtocolInputs:
    dh_action = DhAction.from_label(state.ms_dh_action, "")
    return rules.ProtocolInputs(
        order=str(state.ms_rxn_order or "1"), k=_sf(state.ms_rxn_k), C0=_sf(state.ms_rxn_c0),
        t_specified=_sf(state.ms_rxn_trxn), dH=_sf(state.ms_rxn_dh),
        rxn_type=str(_reaction_row(state.ms_reaction).get("type", "") or ""),
        kinetics=Kinetics.from_label(state.ms_kinetics_avail, Kinetics.AVAILABLE),
        bourne=BourneStatus.from_label(state.ms_bourne_status, BourneStatus.SKIP),
        bourne_mech=Mechanism.from_label(state.ms_bourne_mech, ""),
        bourne_tests_done=[bourne_test_number(t) for t in (state.ms_bourne_tests or [])],
        bourne_rows=(state.ms_bourne_findings_df.to_dict("records")
                     if not state.ms_bourne_findings_df.empty else []),
        semi_batch=is_on(state.ms_semi_batch),
        phases=[Phase.from_label(p) for p in (state.ms_phases or [])],
        competing=Competing.from_label(state.ms_competing, ""),
        dh_override=_sf(state.ms_dh_override),
        dh_override_measured=DhBasis.from_label(state.ms_dh_measured) is DhBasis.MEASURED,
        dh_action=dh_action,
        dh_ref_value=(_sf(_reaction_row(state.ms_dh_ref).get("delta_H_kJ_mol"))
                      if dh_action == DhAction.ESTIMATE else 0.0),
        c0_heat=state.ms_c0_heat, rho_cp=state.ms_rho_cp)


# ---------------------------------------------------------------------------
# Central recompute - runs on every relevant input change
# ---------------------------------------------------------------------------
def _recompute(state):
    # No assessment is made until the user explicitly starts it (avoids showing
    # results for the default inputs on page load).
    if not getattr(state, "ms_started", False):
        return
    required = [
        "ms_reaction", "ms_kinetics_avail", "ms_phases", "ms_competing",
        "ms_dh_action", "ms_rho_cp", "ms_c0_heat",
    ]
    if not all(hasattr(state, name) for name in required):
        return
    res = rules.assess_protocol(_protocol_inputs(state),
                                damkohler_for=lambda t: _inline_damkohler(state, t))
    md = rules.protocol_md(res)

    for n in range(6):
        setattr(state, f"ms_step{n}_assess", md[f"step{n}"])
    state.ms_kinetics_md = md["kinetics_md"]
    state.ms_show_dh_action = res["show_dh_action"]
    state.ms_dt_ad_caption = md["dt_ad_caption"]
    state.ms_da_caption = md["da_caption"]
    state.ms_trxn_caption = md["trxn_caption"]
    state.ms_ready = res["ready"]
    state.ms_findings_df = pd.DataFrame(
        [{"Sensitivity Type": m, "Finding": f"{s} - {d}"} for m, s, d in md["findings"]])
    state.ms_nextsteps_df = pd.DataFrame(md["next_steps"])
    state.ms_verdict = md["verdict"] if res["ready"] else ""
    state.ms_summary_note = md["summary_note"]

    # invalidate a previously generated PDF (inputs changed)
    state.ms_pdf_ready = False
    state._ms_cache = snapshots.protocol_snapshot(
        res, md, reaction=state.ms_reaction, competing_label=state.ms_competing,
        bourne_meta=getattr(state, "ms_bourne_meta", {}))


# ---------------------------------------------------------------------------
# Inline Damköhler screen (Step 5, optional vessel)
# ---------------------------------------------------------------------------
def _inline_damkohler(state, t_rxn: float) -> dict | None:
    """Da_macro / Da_micro for the chosen vessel at the given N and V (literature
    correlations, solvent from the reaction row, else water). None when off or
    the vessel geometry is incomplete."""
    if not is_on(getattr(state, "ms_da_mode", Toggle.OFF.label)):
        return None
    solvent = str(_reaction_row(state.ms_reaction).get("solvent", "") or "")
    return op.screening_damkohler(
        str(getattr(state, "ms_da_reactor", "")), _sf(getattr(state, "ms_da_rpm", 0.0)),
        _sf(getattr(state, "ms_da_vl", 0.0)), solvent,
        _sf(getattr(state, "ms_rxn_T", 25.0), 25.0), t_rxn)


_strip_md = rules.strip_md
_build_verdict = rules.build_verdict


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------
def on_ms_reaction_change(state):
    row = _reaction_row(state.ms_reaction)
    kd = _kin_defaults(state.ms_reaction)
    state.ms_rxn_order = kd["order"]
    state.ms_rxn_k = kd["k"]
    state.ms_rxn_c0 = kd["C0"]
    state.ms_rxn_trxn = kd["t_rxn"]
    state.ms_rxn_T = kd["T"]
    state.ms_rxn_dh = kd["dH"]
    solvent = str(row.get("solvent", "") or "")
    # auto-fill volumetric heat capacity from the solvent when known
    _update_rho_cp(state, solvent, kd["T"])
    state.ms_c0_heat = round(kd["C0"], 4) if kd["C0"] > 0 else 1.0
    _safe_recompute(state)


def on_ms_kin_change(state, var_name=None, value=None):
    if var_name == "ms_rxn_c0" and _sf(state.ms_rxn_c0) > 0:
        state.ms_c0_heat = round(_sf(state.ms_rxn_c0), 4)
    if var_name == "ms_rxn_T":
        row = _reaction_row(state.ms_reaction)
        _update_rho_cp(state, str(row.get("solvent", "") or ""), _sf(state.ms_rxn_T, 25.0))
    _safe_recompute(state)


def on_ms_change(state):
    previous_reaction = state.ms_reaction
    _sync_reaction_options(state)
    if state.ms_reaction != previous_reaction:
        on_ms_reaction_change(state)
        return
    _safe_recompute(state)


def on_ms_da_reactor_change(state):
    """Seed the Step 5 operating point from the chosen vessel's mid-range."""
    row = _reactor_row(state.ms_da_reactor)
    state.ms_da_rpm = _mid(row, "N_rpm_min", "N_rpm_max", _sf(state.ms_da_rpm, 300.0))
    state.ms_da_vl = _mid(row, "V_L_min", "V_L_max", _sf(row.get("V_L"), _sf(state.ms_da_vl, 1.0)))
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
        df = db.read_upload_csv(path, dtype=str, keep_default_na=False)
        imp = bourne_io.parse(df)
    except ValueError as exc:
        notify(state, "E", str(exc))
        return
    except Exception as exc:  # noqa: BLE001
        notify(state, "E", f"Could not read the file: {exc}")
        return
    d = imp["fields"]
    state.ms_bourne_status = imp["status"].label
    state.ms_bourne_mech = Mechanism(imp["mechanism"]).label if imp["mechanism"] else _NOT_RESOLVED
    state.ms_bourne_tests = [BOURNE_TESTS[n] for n in imp["tests_done"]] or [BOURNE_TESTS[1]]
    state.ms_bourne_findings_df = pd.DataFrame(imp["findings"]) if imp["findings"] else pd.DataFrame(
        columns=["Test", "Finding", "Sensitive KPI(s)"])
    state.ms_bourne_meta = imp["meta"]
    state.ms_bourne_meta_caption = imp["meta_caption"]
    # Prefill blank Project Information fields from the Bourne export.
    for attr, fld in (("ms_project_name", "project_name"), ("ms_step_text", "step_number"),
                      ("ms_process_version", "process_version")):
        if d.get(fld) and not str(getattr(state, attr, "") or "").strip():
            setattr(state, attr, d[fld])
    unit_op = d.get("unit_operation", "")
    if (unit_op in ms_unit_operation_options
            and getattr(state, "ms_unit_operation", "") in ("", ms_unit_operation_options[0])):
        state.ms_unit_operation = unit_op
    notify(state, "S", "Bourne results imported.")
    if all(hasattr(state, field) for field in [
        "ms_started", "ms_reaction", "ms_kinetics_avail", "ms_phases",
        "ms_competing", "ms_dh_action", "ms_rho_cp", "ms_c0_heat",
    ]):
        _recompute(state)


def on_ms_export_pdf(state):
    if not state.ms_ready:
        notify(state, "W", "Complete the assessment (Steps 1–4) before exporting.")
        return
    try:
        snap = dict(state._ms_cache)
        snap["bourne_meta"] = dict(getattr(state, "ms_bourne_meta", {}) or {})
        unit_op = state.ms_unit_operation if state.ms_unit_operation != ms_unit_operation_options[0] else ""
        snap["project_name"] = state.ms_project_name
        snap["step_number"] = state.ms_step_text
        snap["unit_operation"] = unit_op
        snap["process_version"] = state.ms_process_version
        state.ms_pdf_bytes = build_protocol_pdf(snap)
        state.ms_pdf_name = report_filename("RxnSens", report_header_label(snap) or state.ms_reaction)
        state.ms_pdf_ready = True
        notify(state, "S", "PDF report generated - click Download.")
    except Exception as exc:  # noqa: BLE001
        notify(state, "E", f"PDF generation failed: {exc}")


def on_ms_pdf_download(state):
    # file_download's `name` property is static, so the filename must be set
    # via the imperative download() call rather than the control's binding.
    if not state.ms_pdf_ready:
        return
    download(state, content=state.ms_pdf_bytes, name=state.ms_pdf_name)


def on_ms_init(state):
    """Start (or refresh) the assessment once the user has set the inputs."""
    state.ms_started = True
    on_ms_reaction_change(state)


def on_ms_update_assessment(state):
    """Re-run the assessment while preserving all current user inputs."""
    state.ms_started = True
    state.ms_pdf_ready = False
    state.ms_pdf_bytes = b""
    _safe_recompute(state)
    notify(state, "S", "Assessment updated with the current inputs.")


def on_ms_reset(state):
    """Reset every input back to its default and clear all results/recommendations."""
    # inputs
    state.ms_project_name = ""
    state.ms_step_text = ""
    state.ms_unit_operation = ms_unit_operation_options[0]
    state.ms_process_version = ""
    state.ms_bourne_status = ms_bourne_status_options[0]
    state.ms_bourne_mech = _NOT_RESOLVED
    state.ms_bourne_tests = [BOURNE_TESTS[1]]
    state.ms_bourne_upload = ""
    state.ms_kinetics_avail = ms_kinetics_options[0]
    state.ms_reaction = reaction_options[0] if reaction_options else ""
    state.ms_reaction_options = reaction_options
    kd = _kin_defaults(state.ms_reaction)
    state.ms_rxn_order = kd["order"]
    state.ms_rxn_k = kd["k"]
    state.ms_rxn_c0 = kd["C0"]
    state.ms_rxn_trxn = kd["t_rxn"]
    state.ms_rxn_T = kd["T"]
    state.ms_rxn_dh = kd["dH"]
    state.ms_semi_batch = Toggle.OFF.label
    state.ms_phases = [Phase.LIQUID.label]
    state.ms_competing = _SELECT
    state.ms_dh_action = _SELECT
    state.ms_dh_ref = dh_ref_options[0]
    state.ms_dh_override = 0.0
    state.ms_dh_measured = DhBasis.ESTIMATED.label
    state.ms_rho_cp = 1800.0
    state.ms_c0_heat = 1.0
    state.ms_da_mode = Toggle.OFF.label
    state.ms_da_caption = ""
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
    state.ms_bourne_meta = {}
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
    notify(state, "I", "Assessment reset - set your inputs and start again.")


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------
page = Markdown(
    inject_icons("""
# __ICON:Mixing_Sensitivity__Reaction Sensitivity Protocol

A guided decision tree to determine **whether a reaction is sensitive to mixing**
and, if so, **which mechanism controls** it - micromixing, mesomixing,
macromixing, interphase mass transport, or heat transfer. Work through the steps;
the **Summary** synthesises everything into an overall verdict.

<|part|height=18px|>

<|Decision-tree flowsheet|expandable|expanded=False|
<|part|content={ms_decision_tree_html}|height=620px|>
|>

<|part|height=18px|>

<|part|class_name=va-card|
## Project Information
<|layout|columns=1 1 1 1|class_name=form-grid|
<|{ms_project_name}|input|label=Project name|>

<|{ms_step_text}|input|label=Step|>

<|{ms_unit_operation}|selector|lov={ms_unit_operation_options}|dropdown|label=Unit operation|>

<|{ms_process_version}|input|label=Process version|>
|>
|>

<|part|height=18px|>

<|part|render={not ms_started}|
**Set your inputs in the steps below, then click _Start assessment_ at the bottom
of the page.** No results are shown until you do.
|>

<|part|render={ms_started}|
<|layout|columns=1 1|class_name=form-grid|
<|Update assessment|button|on_action=on_ms_update_assessment|class_name=compute-btn|>
<|Reset assessment|button|on_action=on_ms_reset|class_name=compute-btn|>
|>
|>

<|part|height=18px|>

<|part|class_name=va-card|
## Step 0 - Bourne Protocol Pre-Screen
Independent experimental evidence of whether a mixing sensitivity exists. If you
have run the Bourne Protocol, enter the outcome (or import its results CSV).

<|part|height=18px|>

<|layout|columns=1 1 1|class_name=form-grid|
<|{ms_bourne_status}|selector|lov={ms_bourne_status_options}|dropdown|label=Bourne outcome|on_change=on_ms_change|>

<|{ms_bourne_mech}|selector|lov={ms_bourne_mech_options}|dropdown|label=Controlling scale identified|on_change=on_ms_change|active={ms_bourne_status == ms_lbl_confirmed}|>

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
## Step 1 - Reaction Kinetics
The characteristic reaction time **t<sub>rxn</sub>** is the Damköhler reference timescale
for every mechanism below. When derived from k and C₀, the protocol uses a conservative
90% conversion process-window estimate rather than only the initial rate.

<|part|height=18px|>

<|layout|columns=1 1|class_name=form-grid|
<|{ms_kinetics_avail}|selector|lov={ms_kinetics_options}|dropdown|label=Are kinetics available?|on_change=on_ms_change|>

<|{ms_reaction}|selector|lov={ms_reaction_options}|dropdown|label=Reaction or proxy class|on_change=on_ms_reaction_change|>
|>

**Reaction conditions & kinetics** - auto-filled from the database; edit any value to override.

<|layout|columns=1 1 1|class_name=form-grid|
<|{ms_rxn_order}|selector|lov={ms_rxn_order_options}|dropdown|label=Reaction order|on_change=on_ms_kin_change|>

<|{ms_rxn_k}|number|label=Rate constant k (1/s or L/mol·s)|on_change=on_ms_kin_change|>

<|{ms_rxn_c0}|number|label=C₀ (mol/L)|on_change=on_ms_kin_change|>
|>

<|layout|columns=1 1 1|class_name=form-grid|
<|{ms_rxn_trxn}|number|label=Reaction time (s, 0 = derive from k)|on_change=on_ms_kin_change|>

<|{ms_rxn_T}|number|label=Temperature (°C)|on_change=on_ms_kin_change|>

<|{ms_rxn_dh}|number|label=ΔH (kJ/mol)|on_change=on_ms_kin_change|>
|>

<|{ms_semi_batch}|toggle|lov={ms_semi_batch_options}|label=Semi-batch (fed-batch) process|class_name=onoff-toggle|on_change=on_ms_change|>

<|part|render={ms_started}|class_name=result-box|
<|{ms_kinetics_md}|text|mode=markdown|>

<|{ms_step1_assess}|text|mode=markdown|>
|>
|>

<|part|class_name=va-card|
## Step 2 - Phase Assessment
Multi-phase systems can be limited by **interphase mass transfer** before mixing
even matters. This includes gas–liquid (k<sub>L</sub>a) transport and solid–liquid (k<sub>SL</sub>)
transport such as solid dissolution, adsorption, and desorption.

<|part|height=18px|>

<|{ms_phases}|selector|lov={ms_phase_options}|multiple|dropdown|label=Which phases are present?|on_change=on_ms_change|class_name=form-grid|>

<|part|render={ms_started}|class_name=result-box|
<|{ms_step2_assess}|text|mode=markdown|>
|>
|>

<|part|class_name=va-card|
## Step 3 - Competing Reactions
When parallel/consecutive reactions compete for a reagent, incomplete
**micromixing** (molecular scale) and **mesomixing** (feed-plume scale) can shift
selectivity.

<|part|height=18px|>

<|{ms_competing}|selector|lov={ms_competing_options}|dropdown|label=Are there competing reactions?|on_change=on_ms_change|class_name=form-grid|>

<|part|render={ms_started}|class_name=result-box|
<|{ms_step3_assess}|text|mode=markdown|>
|>
|>

<|part|class_name=va-card|
## Step 4 - Heat Transfer Screening
The thermal load is set by the enthalpy of reaction (ΔH) and the limiting-reagent
concentration (C₀), and is assessed by the **adiabatic temperature rise**
(ΔT<sub>ad</sub> = |ΔH|·C₀·1000/(ρ·Cp)) - the temperature increase at full conversion with
no cooling and perfect insulation. The reaction rate does not change ΔT_ad, but a
faster reaction releases that heat more quickly and is harder to cool.

<|part|height=18px|>

<|part|render={ms_show_dh_action}|
The selected reaction has **no ΔH data**. Choose how to proceed:
<|layout|columns=1 1|class_name=form-grid|
<|{ms_dh_action}|selector|lov={ms_dh_action_options}|dropdown|label=ΔH source|on_change=on_ms_change|>

<|{ms_dh_ref}|selector|lov={dh_ref_options}|dropdown|label=Reference reaction for ΔH|on_change=on_ms_change|active={ms_dh_action == ms_lbl_estimate}|>
|>
|>

**Heat of reaction basis** - optionally override the ΔH used for this screening and
state whether the value was measured experimentally. With proxy kinetics, the ΔH is
treated as estimated unless a measured override is entered.

<|layout|columns=1 1|class_name=form-grid|
<|{ms_dh_override}|number|label=ΔH override (kJ/mol, 0 = use Step 1 value)|on_change=on_ms_change|>

<|{ms_dh_measured}|selector|lov={ms_dh_measured_options}|dropdown|label=Override ΔH measured?|on_change=on_ms_change|>
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
## Step 5 - Mixing Time vs Reaction Time
The Damköhler number compares **how long mixing takes** with **how long the
reaction takes**: **Da = mixing time / reaction time**. When **Da < 1**, mixing
is faster than the reaction and is less likely to limit the result. When **Da > 1**,
the reaction can proceed before the vessel is fully mixed, so mixing may affect
conversion, selectivity, or temperature.

As vessels get larger, bulk mixing usually takes longer. For geometrically similar
reactors scaled at **constant power per unit volume (P/V)**, the blend time
increases roughly with vessel diameter as **T^(2/3)**. A larger reactor therefore
needs a scale-up check even when the small vessel mixed well. Micromixing is
controlled by local turbulence near the impeller and feed point, while macromixing
describes the time needed to homogenize the whole vessel.

The estimates below compare micromixing time **t<sub>E</sub> ≈ 17.3·√(ν/ε)** and bulk
blend time **θ<sub>95</sub> = 5.2·T^1.5·H^0.5/(N<sub>p</sub>^(1/3)·N·D²)** with the reaction time.
Without a vessel, the screen uses fixed reaction-time bands; select a vessel to
compute the actual **Da<sub>macro</sub>** and **Da<sub>micro</sub>** for a chosen operating point.

<|{ms_da_mode}|toggle|lov={ms_da_mode_options}|label=Compute Damköhler numbers for a vessel|class_name=onoff-toggle|on_change=on_ms_change|>

<|part|render={ms_da_mode == "On"}|
<|layout|columns=2 1 1|class_name=form-grid|
<|{ms_da_reactor}|selector|lov={ms_da_reactor_options}|dropdown|label=Vessel|on_change=on_ms_da_reactor_change|>

<|{ms_da_rpm}|number|label=Agitation speed N (RPM)|on_change=on_ms_change|>

<|{ms_da_vl}|number|label=Working volume (L)|on_change=on_ms_change|>
|>
|>

<|part|render={ms_step5_assess != ""}|class_name=result-box|
<|{ms_trxn_caption}|text|mode=markdown|>

<|{ms_da_caption}|text|mode=markdown|>

<|{ms_step5_assess}|text|mode=markdown|>
|>
|>

<|part|render={not ms_started}|class_name=va-card|
### Ready?
Once you've worked through the steps above, start the assessment to generate the
per-step findings and the overall verdict.

<|Run assessment|button|on_action=on_ms_init|class_name=compute-btn|>
|>

<|part|class_name=va-card|
## Step 6 - Summary & Recommendations
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
## Step 7 - Export Report
Generate a PDF capturing the inputs, findings, overall verdict, and next steps.

<|Generate PDF report|button|on_action=on_ms_export_pdf|class_name=compute-btn|>

<|part|render={ms_pdf_ready}|
<|{None}|file_download|on_action=on_ms_pdf_download|label=Download PDF|>
|>
|>
""")
)
