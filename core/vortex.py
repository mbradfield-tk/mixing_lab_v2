"""Free-surface vortex shape at a given agitation rate (Nagata's combined Rankine vortex).

Unbaffled vessel: liquid inside the critical radius r_c rotates as a solid body (forced
vortex, angular velocity w = 2*pi*N) and outside it as a free vortex (w*r_c^2/r), giving

    z(r) = z0 + w^2 r^2 / (2g)                          r <= r_c
    z(r) = z0 + w^2 r_c^2 / (2g) * (2 - r_c^2 / r^2)    r >  r_c

r_c is taken as the impeller radius and the centre height z0 is found by conserving the
static liquid volume over the real (dished) vessel bottom. Fully baffled vessels (>= 3
baffles) suppress the vortex, so the surface stays flat; partially baffled or unknown
vessels are drawn with the unbaffled profile as an upper bound.
Ref: Nagata, S. (1975). Mixing: Principles and Applications, Ch. 3; Busciglio et al. (2013),
Chem. Eng. Sci. 104, 868 (doi:10.1016/j.ces.2013.10.019).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

G = 9.81
FULL_BAFFLES = 3
N_RADIAL = 240


def surface_profile(r: np.ndarray, omega: float, r_c: float) -> np.ndarray:
    """Surface rise above the vortex centre (m) at radii ``r``."""
    rc2 = r_c * r_c
    k = omega * omega / (2.0 * G)
    safe_r2 = np.maximum(r * r, 1e-30)
    return np.where(r <= r_c, k * r * r, k * rc2 * (2.0 - rc2 / safe_r2))


def _bottom_height(r: np.ndarray, geom: dict) -> np.ndarray:
    """Height of the vessel bottom (m, tangent line = 0) at radius ``r``."""
    if "bottom_at" in geom:
        return np.array([geom["bottom_at"](float(x)) for x in r])
    R, bd, shape = geom["R"], geom["bot_depth"], geom["bot_shape"]
    if bd <= 0 or shape == "flat":
        return np.zeros_like(r)
    x = np.clip(r / R, 0.0, 1.0)
    if shape == "cone":
        return bd * x - bd
    return -bd * np.sqrt(1.0 - x * x)


def _volume(z_surface: np.ndarray, r: np.ndarray, bottom: np.ndarray) -> float:
    column = np.clip(z_surface - bottom, 0.0, None)
    return float(np.trapezoid(2.0 * np.pi * r * column, r))


def baffle_regime(row: pd.Series) -> tuple[str, str]:
    """('full' | 'partial' | 'none' | 'unknown', description)."""
    raw = row.get("baffles")
    try:
        n = float(raw)
    except (TypeError, ValueError):
        n = float("nan")
    if not np.isfinite(n):
        return "unknown", "Baffles not recorded; drawn as unbaffled (upper bound)."
    if n >= FULL_BAFFLES:
        return "full", f"{n:.0f} baffles: the vortex is suppressed and the surface stays essentially flat."
    if n > 0:
        return "partial", (f"{n:.0f} baffle(s): partial baffling reduces the vortex; "
                           "the unbaffled profile is shown as an upper bound.")
    return "none", "Unbaffled vessel."


def vortex_state(geom: dict, row: pd.Series, level: float | None, rpm: float | None,
                 rho: float = 997.0, mu: float = 8.9e-4) -> dict | None:
    """Vortex surface for a static liquid ``level`` (m above the bottom tangent line)."""
    if level is None or rpm is None or rpm <= 0 or not geom["impellers"]:
        return None
    R, H = geom["R"], geom["H"]
    d_imp = geom["impellers"][0][0]
    r_c = min(d_imp / 2.0, R)
    n_rps = rpm / 60.0
    omega = 2.0 * np.pi * n_rps
    regime, baffle_note = baffle_regime(row)

    r = np.linspace(0.0, R, N_RADIAL)
    bottom = _bottom_height(r, geom)
    rise = surface_profile(r, omega, r_c) if regime != "full" else np.zeros_like(r)
    target = _volume(np.full_like(r, level), r, bottom)

    lo, hi = float(bottom.min()) - float(rise.max()), level + 1e-9
    for _ in range(80):  # centre height z0 that conserves the liquid volume
        mid = 0.5 * (lo + hi)
        if _volume(mid + rise, r, bottom) < target:
            lo = mid
        else:
            hi = mid
    z0 = 0.5 * (lo + hi)
    surface = np.maximum(z0 + rise, bottom)

    imp_tops = [cy + h / 2.0 for (_d, cy, h, _s, _t) in geom["impellers"]]
    top_imp = max(imp_tops)
    centre, wall = float(surface[0]), float(surface[-1])
    warnings: list[str] = []
    if regime != "full":
        if centre <= bottom[0] + 1e-6:
            warnings.append("The vortex reaches the vessel bottom (dry centre).")
        elif centre < top_imp:
            warnings.append("The vortex reaches the top impeller: expect gas entrainment and "
                            "unstable power draw.")
        if wall > H + geom["top_depth"]:
            warnings.append("The liquid climbs above the vessel top at the wall (overflow risk).")
        elif wall > H:
            warnings.append("The liquid climbs above the top tangent line at the wall.")

    re = rho * n_rps * d_imp ** 2 / mu
    fr = n_rps ** 2 * d_imp / G
    return {
        "rpm": rpm, "regime": regime, "baffle_note": baffle_note,
        "r_m": r.tolist(), "surface_m": surface.tolist(),
        "centre_mm": centre * 1000.0, "wall_mm": wall * 1000.0,
        "depth_mm": (wall - centre) * 1000.0, "critical_radius_mm": r_c * 1000.0,
        "Re": re, "Fr": fr, "warnings": warnings,
        "low_re": re < 1e4,
    }
