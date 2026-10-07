"""Operating-window ranges and 1-D root finding for sweeps, Solve-for and scale-up."""
from __future__ import annotations

from typing import Callable

import numpy as np
import pandas as pd

from core.records import sf

# Parameters offered for the Vessel Assessment envelope, surfaces and Solve-for (core keys).
ENVELOPE_PARAMETERS = [
    "Da_macro", "Da_micro", "Da_GL",
    "Re", "Power (W)", "P/V (W/L)", "P/V (W/kg)", "Tip speed (m/s)",
    "Pumping rate (m³/s)", "Blend time 95% (s)", "Circulation time (s)",
    "Micromix time t_E (s)", "Kolmogorov η (µm)", "ε_max (W/kg)",
    "EDCF (W/kg/s)", "Torque (N·m)", "Froude number", "Avg shear rate (1/s)",
    "Max shear rate (1/s)", "Avg shear stress (Pa)", "kLa (1/s)",
    "kLa_surface (1/s)",
]
DEFAULT_ENVELOPE = ["Da_macro", "Da_micro", "P/V (W/L)", "Blend time 95% (s)",
                    "Tip speed (m/s)", "Re"]

def operating_window(row: pd.Series, n_rpm: float, v_l: float,
                     n_pts: int = 40) -> tuple[np.ndarray, float, float]:
    """(RPM sweep array, V_min, V_max) for a reactor row, falling back to a band
    around the current operating point when the database range is missing."""
    n_lo = sf(row.get("N_rpm_min"), max(n_rpm * 0.1, 10.0))
    n_hi = sf(row.get("N_rpm_max"), n_rpm)
    if n_hi <= n_lo:
        n_lo, n_hi = n_rpm * 0.2, n_rpm * 1.2
    v_min = sf(row.get("V_L_min"), 0.0)
    v_max = sf(row.get("V_L_max"), 0.0)
    if v_max <= v_min or v_min <= 0:
        v_min = max(v_l * 0.5, 1e-6)
        v_max = max(v_l, v_min * 1.5)
    return np.linspace(n_lo, n_hi, n_pts), v_min, v_max


def solve_root(f: Callable[[float], float], lo: float, hi: float, x_tol: float,
               f_tol: float = 0.0, maxit: int = 200) -> float | None:
    """Bracketed bisection; None when [lo, hi] has no sign change or f is non-finite.

    ``x_tol`` bounds the interval width (solved-variable units); ``f_tol`` bounds
    the residual (target units) so small-magnitude targets aren't falsely converged.
    """
    flo, fhi = f(lo), f(hi)
    if not (np.isfinite(flo) and np.isfinite(fhi)):
        return None
    if flo == 0:
        return lo
    if fhi == 0:
        return hi
    if flo * fhi > 0:
        return None
    for _ in range(maxit):
        mid = 0.5 * (lo + hi)
        fmid = f(mid)
        if not np.isfinite(fmid):
            return None
        if abs(fmid) <= f_tol or (hi - lo) < x_tol:
            return mid
        if flo * fmid < 0:
            hi, fhi = mid, fmid
        else:
            lo, flo = mid, fmid
    return 0.5 * (lo + hi)


def find_roots(f: Callable[[float], float], lo: float, hi: float, n_pts: int = 60,
               iters: int = 40) -> tuple[list[float], np.ndarray, np.ndarray]:
    """All roots of f on [lo, hi]: scan for sign changes, refine each by bisection.

    Returns (roots, scan x, scan f(x)) so callers can report the reachable range.
    """
    xs = np.linspace(lo, hi, n_pts)
    ys = np.array([f(x) for x in xs])
    roots = []
    for i in range(n_pts - 1):
        a, b, fa, fb = xs[i], xs[i + 1], ys[i], ys[i + 1]
        if not (np.isfinite(fa) and np.isfinite(fb)) or fb == 0:
            continue
        if fa == 0:
            roots.append(float(a))
            continue
        if fa * fb > 0:
            continue
        root = solve_root(f, a, b, x_tol=(b - a) / 2.0**iters)
        if root is not None:
            roots.append(float(root))
    if n_pts and np.isfinite(ys[-1]) and ys[-1] == 0:
        roots.append(float(xs[-1]))
    return roots, xs, ys


# (N_rpm, V_L) -> result dict, e.g. a closure over core.operating_point.evaluate_point.
PointEvaluator = Callable[[float, float], dict]


def sweep(evaluate: PointEvaluator, n_values, v_values, params: list[str]) -> dict:
    """{V: {param: array over n_values}} — one RPM sweep per fill volume."""
    out = {}
    for v_l in v_values:
        rows = [evaluate(n_rpm, v_l) for n_rpm in n_values]
        out[v_l] = {p: np.array([r[p] for r in rows]) for p in params}
    return out


def surface_grid(evaluate: PointEvaluator, n_values, v_values, params: list[str]) -> dict:
    """{param: z[j, i]} with rows along ``v_values`` and columns along ``n_values``."""
    z = {p: np.empty((len(v_values), len(n_values))) for p in params}
    for j, v_l in enumerate(v_values):
        for i, n_rpm in enumerate(n_values):
            r = evaluate(n_rpm, v_l)
            for p in params:
                z[p][j, i] = r[p]
    return z


def envelope_data(evaluate: PointEvaluator, row: pd.Series, n_rpm: float, v_l: float,
                  params: list[str]) -> dict:
    """RPM sweeps at the vessel's V_max ("hi") and V_min ("lo") plus the operating point."""
    n_arr, v_min, v_max = operating_window(row, n_rpm, v_l)
    curves = sweep(evaluate, n_arr, (v_max, v_min), params)
    return {"n_rpm": n_arr, "v_min": v_min, "v_max": v_max, "hi": curves[v_max],
            "lo": curves[v_min], "op": evaluate(n_rpm, v_l)}


def surface_data(evaluate: PointEvaluator, row: pd.Series, n_rpm: float, v_l: float,
                 params: list[str], n_pts: int, v_pts: int) -> dict:
    """N x V response grids over the vessel window plus the operating point."""
    n_full, v_min, v_max = operating_window(row, n_rpm, v_l)
    n_arr = np.linspace(n_full[0], n_full[-1], n_pts)
    v_arr = np.linspace(v_min, v_max, v_pts)
    return {"n_rpm": n_arr, "v_l": v_arr, "v_min": v_min, "v_max": v_max,
            "z": surface_grid(evaluate, n_arr, v_arr, params), "op": evaluate(n_rpm, v_l)}


def solve_target(value_at: Callable[[float], float], target: float, lo: float, hi: float,
                 window: tuple[float, float]) -> dict:
    """Find every x in [lo, hi] where value_at(x) == target.

    Returns {roots, achieved, in_window (bool per root), first_in_window (or None),
    span (min, max) of value_at over the scan, or None when nothing finite}.
    """
    roots, _xs, ys = find_roots(lambda x: value_at(x) - target, lo, hi)
    achieved = [value_at(x) for x in roots]
    in_window = [window[0] <= x <= window[1] for x in roots]
    finite = ys[np.isfinite(ys)] + target
    return {
        "roots": roots, "achieved": achieved, "in_window": in_window,
        "first_in_window": next((x for x, ok in zip(roots, in_window) if ok), None),
        "span": (float(finite.min()), float(finite.max())) if finite.size else None,
    }


def solve_operating_point(evaluate: PointEvaluator, row: pd.Series, param: str,
                          target: float, solve_for: str, n_rpm: float, v_l: float) -> dict:
    """Solve for N (``solve_for="N_rpm"``) at fixed V, or V (``"V_L"``) at fixed N, so
    that ``param`` equals ``target``.

    Speed is scanned beyond the rated range (0.25x min to 2x max) so out-of-range
    answers are still reported. Adds ``search`` and ``window`` (lo, hi) to
    :func:`solve_target`'s result.
    """
    n_arr, v_min, v_max = operating_window(row, n_rpm, v_l)
    if solve_for == "N_rpm":
        window = (float(n_arr[0]), float(n_arr[-1]))
        search = (max(window[0] * 0.25, 1.0), window[1] * 2.0)
        value_at = lambda x: float(evaluate(x, v_l)[param])  # noqa: E731
    else:
        window = search = (v_min, v_max)
        value_at = lambda x: float(evaluate(n_rpm, x)[param])  # noqa: E731
    res = solve_target(value_at, target, search[0], search[1], window)
    return {**res, "search": search, "window": window}
