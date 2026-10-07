"""Bourne-protocol KPI response assessment (pure functions, UI-agnostic).

Shared by the Bourne Protocol page (live assessment) and the Reaction
Sensitivity Protocol import so both apply identical rules.

Rules
-----
* Each KPI row needs a low / centre / high response. Rows with *all three*
  blank are ignored; rows with *some* blanks are reported as incomplete and
  skipped (a blank is never treated as zero).
* A KPI is "sensitive" when its largest deviation from the centre exceeds a
  KPI-specific threshold (``kpi_threshold``), unless the signal is within the
  measurement noise band (``Std dev`` / ``Precision`` / ``Replicates``).
* The overall status is **not** a majority vote: any sensitive *critical* KPI
  (impurity / selectivity) -> ``sensitive``; all sensitive -> ``sensitive``;
  none -> ``not_sensitive``; otherwise ``inconclusive``.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

SENS_THRESHOLD = 5.0  # default % change from centre that counts as "sensitive"

# Per-test response column names (low / centre / high condition).
KPI_COLUMNS = {
    1: ("Low speed", "Centre", "High speed"),
    2: ("Slow feed", "Centre", "Fast feed"),
    3: ("Surface", "Mid", "Impeller"),
}
NOISE_COLUMNS = ("Std dev", "Replicates")
# Suggested KPI names and units for the response tables (free text is also allowed).
RESPONSE_METRICS = ["Yield", "Purity", "Conversion", "Selectivity",
                    "Impurity level", "Particle size (D50)", "Other"]
KPI_UNITS = ["%", "ppm", "area%", "wt%", "mol%", "µm", "g/L", "AU"]

STATUS_LABEL = {
    "sensitive": "Sensitive",
    "not_sensitive": "Not sensitive",
    "inconclusive": "Inconclusive",
}


def assess_with_threshold(low: float, center: float, high: float,
                          threshold: float = SENS_THRESHOLD) -> tuple[float, bool]:
    """Return (max % change from centre, sensitive?) for a given threshold.

    Near-zero centres use an absolute-difference basis (max(1, span)) so small
    but real changes are detected without reporting every value as 100 %.
    """
    if abs(center) <= 1e-12:
        span = max(abs(low), abs(center), abs(high))
        if span == 0:
            return 0.0, False
        base = max(1.0, span)
        max_pct = max(abs(v - center) / base * 100.0 for v in (low, center, high))
        return max_pct, max_pct >= threshold
    max_pct = max(abs(v - center) / abs(center) * 100.0 for v in (low, center, high))
    return max_pct, max_pct >= threshold


def kpi_threshold(name: str) -> float:
    """KPI-specific sensitivity threshold in percent."""
    text = str(name or "").lower()
    if any(term in text for term in ("impurity", "particle size", "d50", "size")):
        return 10.0
    if any(term in text for term in ("yield", "conversion", "purity", "selectivity")):
        return 5.0
    return SENS_THRESHOLD


def kpi_criticality(name: str) -> str:
    """'critical' for quality-defining KPIs (impurity / selectivity), else 'secondary'."""
    text = str(name or "").lower()
    if any(term in text for term in ("impurity", "selectivity")):
        return "critical"
    return "secondary"


def _num(val) -> float:
    """Float or NaN (blank / non-numeric -> NaN, never 0)."""
    try:
        return float(pd.to_numeric(val, errors="coerce"))
    except (TypeError, ValueError):
        return float("nan")


def _row_name(r: pd.Series) -> str:
    return (str(r.get("KPI", "") or "KPI").strip() or "KPI")


def new_kpi_df(test: int, seed_names=(("Yield", "%"),)) -> pd.DataFrame:
    """Fresh KPI response table (responses + noise columns blank)."""
    low, ctr, high = KPI_COLUMNS[test]
    rows = [{"KPI": n, "Unit": u, low: np.nan, ctr: np.nan, high: np.nan,
             "Std dev": np.nan, "Replicates": np.nan}
            for n, u in seed_names]
    return pd.DataFrame(rows)


def blank_kpi_row(test: int) -> dict:
    low, ctr, high = KPI_COLUMNS[test]
    return {"KPI": "", "Unit": "", low: np.nan, ctr: np.nan, high: np.nan,
            "Std dev": np.nan, "Replicates": np.nan}


def mirror_kpis(src_df: pd.DataFrame, test: int,
                existing: pd.DataFrame | None = None) -> pd.DataFrame:
    """Carry KPI names/units from an upstream test into ``test``'s table.

    If ``existing`` already holds the same KPI names, it is returned unchanged so
    responses the user has typed are not wiped by a re-assessment upstream.
    """
    names = [(_row_name(r) if str(r.get("KPI", "") or "").strip() else "Yield",
              str(r.get("Unit", "") or "").strip())
             for _, r in src_df.iterrows()]
    if not names:
        names = [("Yield", "%")]
    if existing is not None and not existing.empty and "KPI" in existing.columns:
        have = [str(v).strip() for v in existing["KPI"].tolist()]
        if have == [n for n, _ in names]:
            return existing
    return new_kpi_df(test, seed_names=names)


def empty_result(test: int) -> pd.DataFrame:
    low, ctr, high = KPI_COLUMNS[test]
    return pd.DataFrame(columns=["KPI", low, ctr, high, "Max Δ (%)",
                                 "Threshold (%)", "Sensitive?"])


def incomplete_rows(df: pd.DataFrame, test: int) -> list[str]:
    """Names of KPI rows with some (not all) of the three responses blank."""
    low, ctr, high = KPI_COLUMNS[test]
    out = []
    for _, r in df.iterrows():
        vals = {c: _num(r.get(c)) for c in (low, ctr, high)}
        missing = [c for c, v in vals.items() if np.isnan(v)]
        if 0 < len(missing) < 3:
            out.append(f"{_row_name(r)} (missing {', '.join(missing)})")
    return out


def assess_kpis(df: pd.DataFrame, test: int) -> dict | None:
    """Assess a KPI response table; None when no complete row is present.

    The result carries per-KPI details, the overall status, a display table and
    the list of incomplete rows that were skipped.
    """
    low, ctr, high = KPI_COLUMNS[test]
    results = []
    for _, r in df.iterrows():
        lo, ce, hi = (_num(r.get(c)) for c in (low, ctr, high))
        if any(np.isnan(v) for v in (lo, ce, hi)):
            continue  # all-blank rows ignored; partial rows surfaced via incomplete_rows
        if lo == 0.0 and ce == 0.0 and hi == 0.0:
            continue

        name = _row_name(r)
        unit = str(r.get("Unit", "") or "").strip()
        threshold = kpi_threshold(name)
        max_pct, sensitive = assess_with_threshold(lo, ce, hi, threshold)

        # Noise floor: the effect must exceed 2x the combined replicate /
        # analytical uncertainty before a KPI is called sensitive.
        std_dev = _num(r.get("Std dev"))
        precision = _num(r.get("Precision"))
        replicas = _num(r.get("Replicates"))
        std_dev = 0.0 if np.isnan(std_dev) else std_dev
        precision = 0.0 if np.isnan(precision) else precision
        replicas = max(int(replicas) if not np.isnan(replicas) else 1, 1)
        noise_limited = False
        if std_dev > 0.0 or precision > 0.0:
            noise = np.hypot(std_dev, precision)
            if std_dev > 0.0 and replicas > 1:
                noise = max(noise, std_dev / np.sqrt(replicas))
            signal = max(abs(lo - ce), abs(hi - ce))
            if signal <= 2.0 * noise:
                sensitive = False
                noise_limited = True

        results.append({
            "name": name, "unit": unit, "low": lo, "ctr": ce, "high": hi,
            "max_pct": max_pct, "sensitive": sensitive, "threshold": threshold,
            "criticality": kpi_criticality(name), "noise_limited": noise_limited,
        })
    if not results:
        return None

    n_total = len(results)
    n_sensitive = sum(1 for r in results if r["sensitive"])
    critical_sensitive = any(r["sensitive"] for r in results if r["criticality"] == "critical")
    if critical_sensitive or n_sensitive == n_total:
        status = "sensitive"
    elif n_sensitive == 0:
        status = "not_sensitive"
    else:
        status = "inconclusive"

    table = pd.DataFrame([{
        "KPI": f'{r["name"]} ({r["unit"]})' if r["unit"] else r["name"],
        low: f'{r["low"]:g}', ctr: f'{r["ctr"]:g}', high: f'{r["high"]:g}',
        "Max Δ (%)": f'{r["max_pct"]:.1f}%',
        "Threshold (%)": f'{r["threshold"]:.0f}%',
        "Sensitive?": ("No (within noise)" if r["noise_limited"]
                       else "Yes" if r["sensitive"] else "No"),
    } for r in results])
    sens_names = "; ".join(
        f'{r["name"]} ({r["max_pct"]:.1f}%)' for r in results if r["sensitive"])
    return {
        "results": results, "n_total": n_total, "n_sensitive": n_sensitive,
        "status": status, "sensitive": status == "sensitive",
        "sensitive_names": sens_names, "table": table,
        "incomplete": incomplete_rows(df, test),
    }


def threshold_phrase(res: dict) -> str:
    """'≥ 5%' or '≥ 5–10% (KPI-specific)' depending on the thresholds used."""
    thr = sorted({float(r["threshold"]) for r in res["results"]})
    if len(thr) == 1:
        return f"≥ {thr[0]:.0f}%"
    return f"≥ {thr[0]:.0f}–{thr[-1]:.0f}% (KPI-specific)"


def kpi_prefix(res: dict) -> str:
    """Leading verdict sentence summarising the KPI outcome."""
    n, N = res["n_sensitive"], res["n_total"]
    thr = threshold_phrase(res)
    if res["status"] == "sensitive":
        return (f"⚠️ **Sensitive** — {n} of {N} KPI(s) changed {thr} "
                f"({res['sensitive_names']}).")
    if res["status"] == "inconclusive":
        return (f"⚠️ **Inconclusive** — only {n} of {N} KPI(s) changed "
                f"{thr} ({res['sensitive_names']}); mixed signal.")
    return f"✅ **Not sensitive** — no KPI changed {thr} across {N} KPI(s)."
