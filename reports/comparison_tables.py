"""Vessel Comparison result tables, formatted as on the page (shared by Taipy and the API)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from core import scale_up

PCT_STEPS = [10, 20, 30, 40, 50, 60, 70, 80, 90, 100]


def _fmt_range(lo, hi) -> str:
    if not (np.isfinite(lo) and np.isfinite(hi)):
        return "—"
    if abs(lo - hi) < 1e-12:
        return f"{lo:.3g}"
    return f"{lo:.3g} – {hi:.3g}"


def summary_tables(env_df: pd.DataFrame, agg_df: pd.DataFrame, present: list[str]) -> dict:
    """{summary (ranges per vessel), detail (4 corners), rpm_ref (stir-speed reference)}."""
    key_cols = [p for p in ["P/V (W/L)", "Blend time 95% (s)", "Tip speed (m/s)",
                            "Da_macro", "Da_meso", "Da_micro", "Da_GL", "Re"] if p in present]
    rows = []
    for _, a in agg_df.iterrows():
        row = {"Reactor": a["Reactor"], "Scale": a.get("Scale_first", ""),
               "Volume (L)": _fmt_range(a["Volume (L)_min"], a["Volume (L)_max"])}
        for p in key_cols:
            row[p] = _fmt_range(a[f"{p}_min"], a[f"{p}_max"])
        rows.append(row)

    detail_cols = [c for c in ["Reactor", "Corner", "RPM", "V_L", "Re", "P/V (W/L)",
                               "Tip speed (m/s)", "Blend time 95% (s)",
                               "Micromix time t_E (s)", "Kolmogorov η (µm)",
                               "Da_macro", "Da_meso", "Da_micro", "Da_GL", "Da_SL"]
                   if c in env_df.columns]
    det = env_df[detail_cols].copy()
    for c in detail_cols:
        if c not in ("Reactor", "Corner"):
            det[c] = det[c].map(lambda v: f"{v:.3g}" if pd.notna(v) and np.isfinite(v) else "—")

    ref_rows = []
    for name in agg_df["Reactor"].tolist():
        sub = env_df[env_df["Reactor"] == name]
        rpm_max = sub["RPM_max"].iloc[0]
        rpm_min = sub[sub["Corner"] == scale_up.CORNER_LABELS[0]]["RPM"].iloc[0]
        row = {"Reactor": name, "RPM min": f"{rpm_min:.0f}", "RPM max": f"{rpm_max:.0f}"}
        for pct in PCT_STEPS:
            row[f"{pct}%"] = f"{rpm_max * pct / 100:.0f}"
        ref_rows.append(row)

    return {"summary": pd.DataFrame(rows), "detail": det, "rpm_ref": pd.DataFrame(ref_rows)}


def heat_table(env_df: pd.DataFrame, reactor_info: dict) -> pd.DataFrame:
    return pd.DataFrame([{
        "Reactor": h["reactor"], "Volume (L)": f"{h['V_L']:.1f}",
        "U (W/m²·K)": f"{h['U']:.0f}",
        "A (m²)": f"{h['A_ht']:.3f}",
        "Q_gen (W)": f"{h['Q_gen']:.1f}", "Q_cool (W)": f"{h['Q_cool']:.1f}",
        "Q_gen/Q_cool (%)": f"{h['ratio_pct']:.1f}%" if h["ratio_pct"] < 1e4 else "∞",
        "Assessment": h["assessment"],
    } for h in scale_up.heat_summary_data(env_df, reactor_info)])


def scaling_tables(match: dict | None, basis: str) -> dict:
    """{scale (matched points), full (all parameters), pct (% vs basis)} for a scale-up match."""
    empty = pd.DataFrame()
    if match is None:
        return {"scale": pd.DataFrame([{"Reactor": basis, "Status": "Basis geometry missing"}]),
                "full": empty, "pct": empty}
    results, full = match["results"], match["full"]

    res_df = pd.DataFrame(results)
    for c in res_df.columns:
        if c not in ("Reactor", "Role", "Status"):
            res_df[c] = res_df[c].map(
                lambda v: f"{v:.4g}" if isinstance(v, (int, float)) and np.isfinite(v) else v)

    full_df = pd.DataFrame(full)
    show_cols = [c for c in ["Reactor", "Role", "RPM", "Volume (L)", "Re", "P/V (W/L)",
                             "Tip speed (m/s)", "Blend time 95% (s)", "Micromix time t_E (s)",
                             "Kolmogorov η (µm)", "kLa (1/s)", "Torque (N·m)",
                             "EDCF (W/kg/s)", "Froude number"] if c in full_df.columns]
    disp = full_df[show_cols].copy()
    num_cols = [c for c in show_cols if c not in ("Reactor", "Role")]
    for c in num_cols:
        disp[c] = disp[c].map(lambda v: f"{v:.4g}" if pd.notna(v) and np.isfinite(v) else "—")

    basis_row = full_df[full_df["Role"] == "Basis"].iloc[0]
    pct_rows = []
    for _, row in full_df.iterrows():
        entry = {"Reactor": row["Reactor"], "Role": row["Role"]}
        for c in num_cols:
            b, t = basis_row.get(c, 0.0), row.get(c, 0.0)
            if b and np.isfinite(b) and b != 0 and np.isfinite(t):
                entry[c] = f"{(t - b) / abs(b) * 100:+.1f}%"
            else:
                entry[c] = "—"
        pct_rows.append(entry)
    return {"scale": res_df, "full": disp, "pct": pd.DataFrame(pct_rows)}
