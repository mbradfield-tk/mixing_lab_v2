"""Bourne Protocol condition tables, formatted as on the page (shared by Taipy and the API)."""
from __future__ import annotations

import pandas as pd

from core.records import sf

SETPOINTS_NOTE = ("Speeds hold each condition's P/m constant as the working volume grows — "
                  "set as discrete setpoints when the volume reaches each milestone.")
SETPOINTS_CLAMPED = (" ⚠ Some values were clamped to the reactor RPM range; the target "
                     "P/m cannot be held at those steps.")


def reactor_limits(row: pd.Series) -> pd.DataFrame:
    """Small Property/Value/Units table of a reactor's volume & speed limits."""
    vmin = sf(row.get("V_L_min"))
    vmax = sf(row.get("V_L_max"), sf(row.get("V_L")))
    nmin = sf(row.get("N_rpm_min"))
    nmax = sf(row.get("N_rpm_max"))
    dimp = sf(row.get("D_imp_m"))
    Np = sf(row.get("Np"))

    def _rng(a, b):
        if a <= 0 and b <= 0:
            return "—"
        if a > 0 and b > 0:
            return f"{a:g} – {b:g}"
        return f"{(a or b):g}"

    return pd.DataFrame([
        {"Property": "Working volume", "Value": _rng(vmin, vmax), "Units": "L"},
        {"Property": "Impeller speed", "Value": _rng(nmin, nmax), "Units": "RPM"},
        {"Property": "Impeller diameter", "Value": f"{dimp:g}" if dimp > 0 else "—", "Units": "m"},
        {"Property": "Power number Np", "Value": f"{Np:g}" if Np > 0 else "—", "Units": "–"},
    ])


def test1_table(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame([{
        "Condition": r["Condition"] + r["note"],
        "N (RPM)": f"{r['N (RPM)']:,.1f}",
        "P/V (W/L)": f"{r['P/V (W/L)']:.4g}",
        "P/m (W/kg)": f"{r['P/m (W/kg)']:.4g}",
        "Blend time (s)": f"{r['Blend time (s)']:.3g}",
        "Avg shear rate (1/s)": f"{r['Avg shear rate (1/s)']:.3g}",
        "Tip speed (m/s)": f"{r['Tip speed (m/s)']:.3g}",
        "Re": f"{r['Re']:,.0f}",
        "kLa_surface (1/s)": f"{r['kLa_surface (1/s)']:.3g}",
        "t_E micro (s)": f"{r['t_E micro (s)']:.3g}",
        "η (µm)": f"{r['η (µm)']:.3g}",
    } for r in rows])


def setpoints_table(setpoints: list[dict], clamped: bool) -> tuple[pd.DataFrame, str]:
    """(table, caption) of ``plan.speed_setpoints`` rows: {Step, Volume (L), <cond>: (rpm, clamped)}."""
    rows = []
    for sp in setpoints:
        row = {"Step": sp["Step"], "Volume (L)": f"{sp['Volume (L)']:.3g}"}
        for col in ("Low (RPM)", "Centre (RPM)", "High (RPM)"):
            n_rpm, was_clamped = sp[col]
            row[col] = f"{n_rpm:.1f}{' ⚠' if was_clamped else ''}"
        rows.append(row)
    return pd.DataFrame(rows), SETPOINTS_NOTE + (SETPOINTS_CLAMPED if clamped else "")


def test2_table(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame([
        {"Condition": r["Condition"], "Feed time (min)": f"{r['Feed time (min)']:.3g}",
         "Flow rate (mL/min)": f"{r['Flow rate (mL/min)']:.3g}", "Note": r["Note"]}
        for r in rows])


# The page labels the mid-tank location more tersely than the PDF report.
T3_PAGE_LABELS = {"Sub-surface (mid-tank)": "Sub-surface (mid)"}


def test3_table(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame([
        {"Feed location": r["Feed location"], "ε_loc/ε_avg": f"{r['ε_loc/ε_avg']:.1f}",
         "ε_loc (W/kg)": f"{r['ε_loc (W/kg)']:.4g}",
         "t_E micro (s)": f"{r['t_E micro (s)']:.3g}"}
        for r in rows])
