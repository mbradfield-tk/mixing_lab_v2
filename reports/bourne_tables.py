"""Bourne Protocol condition tables, formatted as on the page and in the report."""
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


def test1_summary_table(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame([{
        "Condition": r["Condition"] + r["note"],
        "N (RPM)": f"{r['N (RPM)']:,.1f}",
        "Fill volume (L)": f"{r['Volume (L)']:.4g}",
        "P/V (W/L)": f"{r['P/V (W/L)']:.4g}",
        "P/m (W/kg)": f"{r['P/m (W/kg)']:.4g}",
    } for r in rows])


# (compute_reactor_hydro key, column, format) of the Test 1 detail table.
T1_DETAIL = [
    ("Power (W)", "Power (W)", ".4g"),
    ("Torque (N·m)", "Torque (N·m)", ".3g"),
    ("ε_max (W/kg)", "EDR max ε_max (W/kg)", ".3g"),
    ("Tip speed (m/s)", "Tip speed (m/s)", ".3g"),
    ("Re", "Re", ",.0f"),
    ("Froude number", "Froude number", ".3g"),
    ("Pumping rate (m³/s)", "Pumping rate (m³/s)", ".3g"),
    ("Circulation time (s)", "Circulation time (s)", ".3g"),
    ("Blend time 95% (s)", "Blend time 95% (s)", ".3g"),
    ("Micromix time t_E (s)", "Micromix t_E bulk (s)", ".3g"),
    ("Micromix time t_E_local (s)", "Micromix t_E at impeller (s)", ".3g"),
    ("Kolmogorov η (µm)", "Kolmogorov η (µm)", ".3g"),
    ("Avg shear rate (1/s)", "Avg shear rate (1/s)", ".3g"),
    ("Max shear rate (1/s)", "Max shear rate (1/s)", ".3g"),
    ("Avg shear stress (Pa)", "Avg shear stress (Pa)", ".3g"),
    ("EDCF (W/kg/s)", "EDCF (W/kg/s)", ".3g"),
    ("kLa_surface (1/s)", "kLa_surface (1/s)", ".3g"),
]


def test1_detail_table(rows: list[dict], hydros: list[dict], rho: float) -> pd.DataFrame:
    """Test 1 conditions with the full hydrodynamics (``compute_reactor_hydro`` per condition)."""
    out = []
    for r, h in zip(rows, hydros):
        row = {"Condition": r["Condition"] + r["note"], "N (RPM)": f"{r['N (RPM)']:,.1f}",
               "Fill volume (L)": f"{r['Volume (L)']:.4g}", "P/V (W/L)": f"{r['P/V (W/L)']:.4g}",
               "EDR mean ε = P/m (W/kg)": f"{r['P/m (W/kg)']:.4g}"}
        for key, col, spec in T1_DETAIL:
            v = h.get(key)
            row[col] = format(v, spec) if isinstance(v, (int, float)) else "—"
        out.append(row)
    return pd.DataFrame(out)


def with_operating(df: pd.DataFrame, T_C: float, V_L: float | None = None,
                   N_rpm: float | None = None) -> pd.DataFrame:
    """``df`` with temperature (and a fixed speed / fill volume) after the first column."""
    df = df.copy()
    cols = [("T (°C)", f"{T_C:g}")]
    if N_rpm is not None:
        cols.append(("N (RPM)", f"{N_rpm:,.1f}"))
    if V_L is not None:
        cols.append(("Fill volume (L)", f"{V_L:.4g}"))
    for i, (col, value) in enumerate(cols, start=1):
        df.insert(i, col, value)
    return df


# (reactors.csv column, label, unit) of the vessel description in the Bourne report.
VESSEL_INFO = [
    ("manufacturer", "Manufacturer", ""), ("manufacturer_model", "Model", ""),
    ("type", "Vessel type", ""), ("scale", "Scale", ""),
    ("D_tank_m", "Tank diameter", "m"), ("bottom_dish", "Bottom dish", ""),
    ("baffles", "Baffles", ""), ("shell_material", "Shell material", ""),
    ("lining_material", "Lining", ""), ("impeller_type", "Impeller type", ""),
    ("impeller_model", "Impeller model", ""), ("impeller_flow", "Impeller flow", ""),
    ("impeller_count", "Number of impellers", ""), ("D_imp_m", "Impeller diameter", "m"),
    ("imp1_clearance_m", "Impeller clearance", "m"), ("Np", "Power number Np", ""),
    ("D_feed_pipe_m", "Feed pipe diameter", "m"), ("probes", "Probes", ""),
    ("instrumentation", "Instrumentation", ""), ("heating_cooling", "Heating / cooling", ""),
    ("heat_transfer_medium", "Heat-transfer medium", ""),
]


def vessel_info(row: pd.Series) -> list[tuple[str, str]]:
    """(label, value) pairs of the populated vessel-description fields, plus the volume and
    speed ranges."""
    out = []
    for col, label, unit in VESSEL_INFO:
        v = row.get(col)
        if v is None or (isinstance(v, float) and pd.isna(v)) or str(v).strip() in ("", "0"):
            continue
        text = f"{v:g}" if isinstance(v, float) else str(v).strip()
        out.append((label, f"{text} {unit}".strip()))
    limits = reactor_limits(row)
    out += [(r["Property"] + " range", f"{r['Value']} {r['Units']}") for _, r in limits.iterrows()
            if r["Property"] in ("Working volume", "Impeller speed") and r["Value"] != "—"]
    return out


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
