"""Scale-up arithmetic shared across vessels: operating envelopes, parameter
matching between vessels, fed-batch feed plans and impact ratios."""
from __future__ import annotations

from typing import Callable

import numpy as np
import pandas as pd

from core import operating_point as op
from core.envelope import solve_root
from core.records import VesselGeometry, sf

CORNER_LABELS = ["min RPM / max V", "max RPM / max V",
                 "min RPM / min V", "max RPM / min V"]


def vessel_window(row: pd.Series, geo: VesselGeometry) -> dict | None:
    """RPM and fill-volume window for a vessel, or None when geometry/speed is missing.

    Without a distinct minimum speed the sweep starts at 10% of max so the
    envelope keeps horizontal extent.
    """
    if geo.D_imp <= 0 or geo.D_tank <= 0 or geo.H_max <= 0:
        return None
    rpm_min, rpm_max = sf(row.get("N_rpm_min")), sf(row.get("N_rpm_max"))
    n_rps = sf(row.get("N_rps"))
    if rpm_max <= 0 and n_rps > 0:
        rpm_max = n_rps * 60.0
    if rpm_max <= 0:
        return None
    if rpm_min <= 0 or rpm_min >= rpm_max:
        rpm_min = rpm_max * 0.1
    v_geo = np.pi / 4 * geo.D_tank**2 * geo.H_max * 1000.0
    v_max = sf(row.get("V_L_max")) or sf(row.get("V_L")) or v_geo
    v_min = sf(row.get("V_L_min")) or v_max
    return {"N_lo": rpm_min / 60.0, "N_hi": rpm_max / 60.0, "rpm_max": rpm_max,
            "V_max_L": v_max, "V_min_L": v_min}


def corner_envelope(inp: op.PointInputs, window: dict, plot_params: list[str],
                    n_interp: int = 40) -> tuple[list[dict], dict]:
    """Four-corner operating points plus min/max-volume boundary curves.

    Returns (corner rows, {"pct_arr", "maxV": {param: array}, "minV": {...}}).
    """
    n_lo, n_hi = window["N_lo"], window["N_hi"]
    v_max, v_min = window["V_max_L"], window["V_min_L"]
    corners = []
    for label, n, v in [(CORNER_LABELS[0], n_lo, v_max), (CORNER_LABELS[1], n_hi, v_max),
                        (CORNER_LABELS[2], n_lo, v_min), (CORNER_LABELS[3], n_hi, v_min)]:
        corners.append({"Corner": label, "N (rev/s)": n, "RPM": n * 60.0,
                        "RPM_max": window["rpm_max"], "V_L": v, "Volume (L)": v,
                        **op.evaluate_point(inp, n, v)})

    n_arr = np.linspace(n_lo, n_hi, n_interp)
    curves = {"pct_arr": n_arr / n_hi * 100.0 if n_hi > 0 else np.zeros(n_interp)}
    for key, v in (("maxV", v_max), ("minV", v_min)):
        arrs = {p: np.full(n_interp, np.nan) for p in plot_params}
        for j, n in enumerate(n_arr):
            vals = op.evaluate_point(inp, n, v)
            for p in plot_params:
                arrs[p][j] = vals.get(p, np.nan)
        curves[key] = arrs
    return corners, curves


def matching_window(row: pd.Series, geo: VesselGeometry) -> tuple[tuple[float, float], tuple[float, float]]:
    """((rpm_min, rpm_max), (V_min, V_max)) used to judge a matched operating point."""
    rpm_max = sf(row.get("N_rpm_max")) or sf(row.get("N_rps")) * 60.0
    rpm_min = sf(row.get("N_rpm_min")) or 1.0
    v_max = sf(row.get("V_L_max")) or sf(row.get("V_L")) or (
        np.pi / 4 * geo.D_tank**2 * geo.H_max * 1000.0)
    v_min = sf(row.get("V_L_min")) or v_max * 0.1
    return (rpm_min, rpm_max), (v_min, v_max)


def match_parameter(hydro_at: Callable[[float, float], dict], param: str, target: float, *,
                    solve_rpm: bool, known: float, rpm_window: tuple[float, float],
                    vol_window: tuple[float, float]) -> dict:
    """Operating point on a target vessel that reproduces ``param`` = ``target``.

    ``hydro_at(N_rps, V_L)`` evaluates the target vessel. Solves for RPM at the
    known volume (``solve_rpm``) or for volume at the known RPM, searching beyond
    the vessel window so out-of-range answers are still reported. When no exact
    match exists the closer search bound is returned with a "Not achievable" status.
    Returns {RPM, Volume (L), value, status, hydro}.
    """
    f_tol = max(abs(target) * 1e-4, 1e-9)
    (rpm_min, rpm_max), (v_min, v_max) = rpm_window, vol_window

    if solve_rpm:
        def point(rpm):
            return rpm / 60.0, known
        lo, hi, x_tol = max(rpm_min, 0.5), rpm_max * 1.5, 0.01
        bounds, unit_txt = (rpm_min, rpm_max), "RPM"
        outside = f"Matched (outside {rpm_min:.0f}–{rpm_max:.0f} RPM)"
    else:
        def point(vol):
            return known / 60.0, vol
        lo, hi, x_tol = max(v_min * 0.5, 0.001), v_max * 1.2, 0.001
        bounds, unit_txt = (v_min, v_max), "V"
        outside = f"Matched (outside {v_min:.1f}–{v_max:.1f} L)"

    def value_at(x):
        return hydro_at(*point(x)).get(param, np.nan)

    root = solve_root(lambda x: value_at(x) - target, lo, hi, x_tol=x_tol, f_tol=f_tol)
    if root is None:
        v_lo, v_hi = value_at(lo), value_at(hi)
        x, value = (lo, v_lo) if abs(v_lo - target) < abs(v_hi - target) else (hi, v_hi)
        in_rng = bounds[0] <= x <= bounds[1]
        status = f"Not achievable (closest {value:.4g})" + ("" if in_rng else f" [outside {unit_txt}]")
    else:
        x, value = root, value_at(root)
        status = "Matched" if bounds[0] <= x <= bounds[1] else outside

    n_rps, vol = point(x)
    return {"RPM": n_rps * 60.0, "Volume (L)": vol, "value": value, "status": status,
            "hydro": hydro_at(n_rps, vol)}


def feed_plan_data(reactor_info: dict, basis: str, feed_volume_mL: float,
                   feed_time_hr: float) -> tuple[list[dict], str | None]:
    """Scale the basis vessel's feed volume to every vessel by its V_L_max ratio.

    Feed time is shared, so only volume (and rate) scales; each vessel starts at
    V_L_min. Returns (numeric rows, blocking error code "basis" or None).
    """
    if basis not in reactor_info or reactor_info[basis]["V_max_L"] <= 0:
        return [], "basis"
    basis_vmax = reactor_info[basis]["V_max_L"]
    feed_time_hr = max(feed_time_hr, 1e-9)
    rows = []
    for name, info in reactor_info.items():
        v_max, v_min = info["V_max_L"], info["V_min_L"]
        feed_vol_mL = feed_volume_mL * v_max / basis_vmax
        end_vol_L = v_min + feed_vol_mL / 1000.0
        rows.append({
            "reactor": name, "is_basis": name == basis, "V_max_L": v_max,
            "start_volume_L": v_min, "feed_volume_mL": feed_vol_mL,
            "feed_rate_mL_min": feed_vol_mL / (feed_time_hr * 60.0),
            "end_volume_L": end_vol_L, "exceeds_max": end_vol_L > v_max + 1e-9,
        })
    return rows, None


def feed_plan(reactor_info: dict, basis: str, feed_volume_mL: float,
              feed_time_hr: float) -> tuple[list[dict], list[str], str | None]:
    """Display table of :func:`feed_plan_data`: (rows, vessels that would overflow, error)."""
    data, err = feed_plan_data(reactor_info, basis, feed_volume_mL, feed_time_hr)
    if err:
        status = ("Basis geometry missing" if basis not in reactor_info
                  else "Basis max volume unavailable")
        return [{"Reactor": basis, "Status": status}], [], err
    rows, exceeded = [], []
    for d in data:
        exceeds = d["exceeds_max"]
        if exceeds:
            exceeded.append(f"{d['reactor']} ({d['end_volume_L']:.3g} L > {d['V_max_L']:.3g} L)")
        rows.append({
            "Reactor": d["reactor"], "Role": "Basis" if d["is_basis"] else "Scaled",
            "V_max (L)": f"{d['V_max_L']:.3g}", "Start volume (L)": f"{d['start_volume_L']:.3g}",
            "Feed volume (mL)": "—" if exceeds else f"{d['feed_volume_mL']:.1f}",
            "Feed rate (mL/min)": "—" if exceeds else f"{d['feed_rate_mL_min']:.2f}",
            "End volume (L)": "—" if exceeds else f"{d['end_volume_L']:.3g}",
            "Status": "⚠️ Exceeds max volume" if exceeds else "OK",
        })
    return rows, exceeded, None


def impact_ratio_data(env_df: pd.DataFrame, present: list[str], incl_heat: bool) -> list[dict]:
    """Envelope-mean ratios of each vessel to the first one (NaN when undefined).

    ``cooling_delta_pp`` is the change in Q_gen/Q_cool (percentage points), or None.
    """
    reactors = env_df["Reactor"].drop_duplicates().tolist()
    if len(reactors) < 2:
        return []
    mid = env_df.groupby("Reactor", sort=False)[
        [p for p in present if p in env_df.columns] + ["Volume (L)"]].mean()
    ref = mid.iloc[0]
    rows = []
    for name in reactors[1:]:
        row = mid.loc[name]

        def _ratio(col):
            return row[col] / ref[col] if col in ref and ref[col] not in (0, np.nan) and np.isfinite(ref[col]) and ref[col] != 0 else np.nan

        entry = {"from": reactors[0], "to": name, "volume": _ratio("Volume (L)"),
                 "P_V": _ratio("P/V (W/L)"), "tip_speed": _ratio("Tip speed (m/s)"),
                 "blend_time": _ratio("Blend time 95% (s)"), "Da_macro": _ratio("Da_macro"),
                 "cooling_delta_pp": None}
        if incl_heat and "Q_gen/Q_cool (%)" in mid.columns:
            rp, tp = ref.get("Q_gen/Q_cool (%)", np.nan), row.get("Q_gen/Q_cool (%)", np.nan)
            if np.isfinite(rp) and np.isfinite(tp):
                entry["cooling_delta_pp"] = tp - rp
        rows.append(entry)
    return rows


def impact_ratios(env_df: pd.DataFrame, present: list[str], incl_heat: bool) -> list[dict]:
    """Display table of :func:`impact_ratio_data`."""
    rows = []
    for d in impact_ratio_data(env_df, present, incl_heat):
        entry = {"From → To": f"{d['from']} → {d['to']}",
                 "Volume ×": f"{d['volume']:.2f}", "P/V ×": f"{d['P_V']:.2f}",
                 "Tip speed ×": f"{d['tip_speed']:.2f}",
                 "Blend time ×": f"{d['blend_time']:.2f}", "Da_macro ×": f"{d['Da_macro']:.2f}"}
        delta = d["cooling_delta_pp"]
        if delta is not None:
            entry["Cooling"] = ("≈ Similar" if abs(delta) < 1 else
                                (f"✅ Improves ({delta:+.1f} pp)" if delta < 0
                                 else f"⚠️ Worse ({delta:+.1f} pp)"))
        rows.append(entry)
    return rows
