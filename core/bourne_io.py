"""Bourne Protocol results hand-off CSV (``field,value`` rows): written by the Bourne
Protocol page, read by the Reaction Sensitivity Protocol page."""
from __future__ import annotations

import csv
import io

import pandas as pd

from core.options import BourneStatus, Mechanism

RECORD_TYPE = "bourne_results"
PROTOCOL_VERSION = "2"
MECHANISMS = tuple(Mechanism)
TEST_NAMES = {1: "Test 1 - Impeller speed", 2: "Test 2 - Feed rate/time", 3: "Test 3 - Feed location"}
META_KEYS = ("project_name", "step_number", "unit_operation", "process_version",
             "reactor", "fluid", "working_volume_L", "test_status", "protocol_version",
             "test1_pm_range_ratio", "dominant_mechanism_tentative")

TEST_FINDINGS = {
    1: {"sensitive": "Mixing-sensitive (impeller speed)",
        "not_sensitive": "Mixing-insensitive",
        "inconclusive": "Inconclusive (mixed KPI response to impeller speed)"},
    2: {"sensitive": "Sensitive to feed rate (mesomixing)",
        "not_sensitive": "Insensitive to feed rate (micromixing-controlled)",
        "inconclusive": "Inconclusive (mixed KPI response to feed rate)"},
    3: {"sensitive": "Sensitive to feed location (mesomixing)",
        "not_sensitive": "Insensitive to feed location (macromixing-controlled)",
        "inconclusive": "Inconclusive (mixed KPI response to feed location)"},
}


def test_finding(status: str, test: int, range_ok: bool = True) -> str:
    """Per-test finding label for the export."""
    if not status:
        return ""
    if test == 1 and status == "not_sensitive" and not range_ok:
        return "Inconclusive (no response, but P/m span < 100x)"
    return TEST_FINDINGS[test].get(status, "")


def export_rows(outcome: dict, meta: dict, sensitive_kpis: dict[int, str]) -> list[tuple[str, str]]:
    """``field,value`` rows from a ``bourne_outcome`` dict.

    ``meta`` holds project_name, step_number, unit_operation, process_version,
    reactor, fluid and working_volume_L; ``sensitive_kpis`` maps test -> KPI list text.
    """
    o = outcome
    mechanism = o["dominant"] if (o["dominant"] in MECHANISMS and not o["tentative"]) else ""
    tentative = o["dominant"] if (o["dominant"] in MECHANISMS and o["tentative"]) else ""
    overall = {"sensitive": "yes", "not_sensitive": "no"}.get(o["s1_eff"], "inconclusive")
    rows = [
        ("record_type", RECORD_TYPE),
        ("protocol_version", PROTOCOL_VERSION),
        ("project_name", str(meta.get("project_name", ""))),
        ("step_number", str(meta.get("step_number", ""))),
        ("unit_operation", str(meta.get("unit_operation", ""))),
        ("process_version", str(meta.get("process_version", ""))),
        ("reactor", str(meta.get("reactor", ""))),
        ("fluid", str(meta.get("fluid", ""))),
        ("working_volume_L", f"{float(meta.get('working_volume_L', 0.0)):g}"),
        ("test1_pm_range_ratio", f"{o['ratio']:.1f}"),
    ]
    for n in (1, 2, 3):
        s = o[f"s{n}"]
        rows += [
            (f"test{n}_assessed", "yes" if s else "no"),
            (f"test{n}_status", s),
            (f"test{n}_finding", test_finding(s, n, o["range_ok"])),
            (f"test{n}_sensitive_kpis", sensitive_kpis.get(n, "")),
        ]
    rows += [
        ("overall_sensitive", overall),
        ("dominant_mechanism", mechanism),
        ("dominant_mechanism_tentative", tentative),
    ]
    return rows


def write_csv(rows: list[tuple[str, str]]) -> bytes:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["field", "value"])
    writer.writerows(rows)
    return buf.getvalue().encode("utf-8")


def parse(df: pd.DataFrame) -> dict:
    """Interpret an uploaded export (string-typed ``field,value`` frame).

    Raises ValueError with a user-facing message when the file is not a Bourne
    results export. Returns {overall: yes|no|inconclusive, status (BourneStatus),
    mechanism (or ""), tests_done (test numbers), findings (rows), meta, meta_caption,
    fields (raw dict)}.
    """
    if not ({"field", "value"} <= set(df.columns)):
        if {"KPI", "Sensitive?"} <= set(df.columns):
            raise ValueError(
                "This is a per-test KPI results table, not the Bourne results export. On the "
                "Bourne Protocol page, use 'Generate Sensitivity CSV' then 'Download Sensitivity "
                "CSV' and import that file.")
        raise ValueError("Not a Bourne results CSV (expected 'field','value' columns). Export it "
                         "with 'Generate Sensitivity CSV' on the Bourne Protocol page.")
    d = {str(k).strip(): str(v).strip() for k, v in zip(df["field"], df["value"])}
    if d.get("record_type") != RECORD_TYPE:
        raise ValueError("That CSV is not a Bourne Protocol results export.")

    overall = (d.get("overall_sensitive") or "unknown").lower()
    if overall not in ("yes", "no"):
        overall = "inconclusive"
    dom = d.get("dominant_mechanism", "")
    done, findings = [], []
    for n in (1, 2, 3):
        # "completed" is the pre-v2 spelling of "assessed".
        assessed = (d.get(f"test{n}_assessed") or d.get(f"test{n}_completed") or "no") == "yes"
        if not assessed:
            continue
        done.append(n)
        findings.append({"Test": TEST_NAMES[n], "Finding": d.get(f"test{n}_finding") or "-",
                         "Sensitive KPI(s)": d.get(f"test{n}_sensitive_kpis")
                         or "None (no KPI over threshold)"})
    bits = [f"**{lbl}:** {d[fld]}" for lbl, fld in (
        ("Project", "project_name"), ("Step", "step_number"), ("Reactor", "reactor"),
        ("Fluid", "fluid"), ("Tentative mechanism", "dominant_mechanism_tentative"))
        if d.get(fld, "")]
    return {
        "overall": overall,
        "status": {"yes": BourneStatus.CONFIRMED, "no": BourneStatus.INSENSITIVE}.get(
            overall, BourneStatus.INCONCLUSIVE),
        "mechanism": dom if dom in MECHANISMS else "",
        "tests_done": done,
        "findings": findings,
        "meta": {k: d[k] for k in META_KEYS if d.get(k)},
        "meta_caption": "Imported Bourne results - " + "  •  ".join(bits) if bits else "",
        "fields": d,
    }
