"""Vessel capacity geometry: interior radius vs height, the cumulative capacity curve
(dish volumes less impeller displacement), and the fill state at a given volume —
liquid level, wetted area and impeller placement warnings. Drawn by
:mod:`viz.vessel_schematic`; served as data by the API."""
from __future__ import annotations

import re

import numpy as np
import pandas as pd

from core.vortex import vortex_state
from utils.calculations.heat_transfer import estimate_jacket_area

IMP_SOLIDITY = 0.20  # fraction of the swept impeller disc that is solid metal


def _parse_cone_angle_deg(dish_type: str, default: float = 45.0) -> float:
    """Cone wall angle from the horizontal (deg), parsed from a dish label."""
    s = str(dish_type).lower()
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:°|deg)", s)
    if m is None:
        m = re.search(r"(\d+(?:\.\d+)?)", s)
    if m is not None:
        ang = float(m.group(1))
        if 5.0 <= ang <= 85.0:
            return ang
    return default


def _f(row: pd.Series, col: str, default: float = 0.0) -> float:
    try:
        v = float(row.get(col))
        return default if np.isnan(v) else v
    except (TypeError, ValueError):
        return default


def _s(row: pd.Series, col: str, default: str = "") -> str:
    v = row.get(col)
    return str(v).strip() if pd.notna(v) else default


# ---------------------------------------------------------------------------
# Dish geometry heuristics (depth as a fraction of the tank radius R = D/2)
# ---------------------------------------------------------------------------
def _dish_depth(dish_type: str, radius: float) -> float:
    dt = dish_type.lower().strip()
    if not dt or "flat" in dt or "none" in dt:
        return 0.0
    if "cone" in dt or "conical" in dt:
        return radius * float(np.tan(np.radians(_parse_cone_angle_deg(dt))))
    if "hemi" in dt or "round" in dt:
        return radius
    if "korbbogen" in dt or "28013" in dt:
        return radius * 0.51
    if ("klopper" in dt or "kloepper" in dt or "klöpper" in dt
            or "28011" in dt or ("din" in dt and "tori" in dt)):
        return radius * 0.39
    if ("tori" in dt or "asme" in dt or "f&d" in dt
            or "f & d" in dt or "flanged" in dt):
        return radius * 0.34
    if "ellip" in dt or "2:1" in dt:
        return radius * 0.50
    if "dish" in dt:
        return radius * 0.20
    return radius * 0.20  # unknown but non-flat -> shallow dish


def _dish_shape(dish_type: str) -> str:
    """Classify the dish profile: 'flat', 'cone' or 'curved'."""
    dt = dish_type.lower().strip()
    if not dt or "flat" in dt or "none" in dt:
        return "flat"
    if "cone" in dt or "conical" in dt:
        return "cone"
    return "curved"


def _bottom_dish_depth(row: pd.Series, dish_type: str, radius: float) -> float:
    """Bottom-dish height (m): CSV H_bot_dish_m, else H_max_m - L_tan_tan_m, else type heuristic."""
    depth = _f(row, "H_bot_dish_m", float("nan"))
    if not np.isfinite(depth):
        h_max, l_tt = _f(row, "H_max_m"), _f(row, "L_tan_tan_m")
        depth = h_max - l_tt if h_max > 0 and l_tt > 0 else float("nan")
    if np.isfinite(depth) and depth >= 0:
        return depth
    return _dish_depth(dish_type, radius)


# ---------------------------------------------------------------------------
# Geometry + capacity curve
# ---------------------------------------------------------------------------
def geometry(row: pd.Series) -> dict | None:
    """Drawable geometry + cumulative capacity curve, or None without tank ID and height.

    ``impellers`` items are (diameter, centre height, blade height, slot 0-2, type).
    """
    D = _f(row, "D_tank_m")
    H = _f(row, "L_tan_tan_m")  # straight-wall (tan-tan) length
    if D <= 0 or H <= 0:
        return None
    R = D / 2.0
    bottom, top = _s(row, "bottom_dish"), _s(row, "top_dish")
    bot_shape, top_shape = _dish_shape(bottom), _dish_shape(top)
    top_depth = _dish_depth(top, R)
    # Bottom-dish height comes from the CSV (H_bot_dish_m = H_max_m - L_tan_tan_m);
    # the dish-type heuristic is only a fallback when H_max_m is missing.
    bot_depth = _bottom_dish_depth(row, bottom, R)
    if bot_depth > 0 and bot_shape == "flat":
        bot_shape = "curved"
    full_height = _f(row, "H_m")
    full_top = full_height - bot_depth if full_height > 0 else 0.0
    show_full_height = full_top > H + max(D, H) * 1e-6
    show_full_height_box = show_full_height
    n_imp = int(_f(row, "impeller_count", 1) or 1)
    n_imp = max(1, min(3, n_imp))

    def radius_at(z: float) -> float:
        """Interior radius at absolute height z (z=0 is the bottom tangent line)."""
        if z >= 0.0 or bot_depth <= 0:
            return R
        d = -z
        if d >= bot_depth:
            return 0.0
        if bot_shape == "cone":
            return R * (z + bot_depth) / bot_depth
        return R * float(np.sqrt(max(0.0, 1.0 - (d / bot_depth) ** 2)))

    # Impellers: clearance is the gap from the lowest interior point to the
    # impeller underside; cy is the resulting blade centre height.
    imp_data = [
        ("D_imp_m", "imp1_clearance_m", "imp1_height_m", "impeller_type"),
        ("D_imp2_m", "imp2_clearance_m", "imp2_height_m", "impeller_type2"),
        ("D_imp3_m", "imp3_clearance_m", "imp3_height_m", "impeller_type3"),
    ]
    impellers = []  # (d_imp, cy, h_imp, slot, itype)
    for i in range(n_imp):
        d_col, c_col, h_col, t_col = imp_data[i]
        d_imp = _f(row, d_col)
        if d_imp <= 0:
            continue
        clr = _f(row, c_col)
        if clr <= 0:
            clr = (bot_depth + H) * (i + 1) / (n_imp + 1)
        h_imp = _f(row, h_col)
        if h_imp <= 0:
            h_imp = d_imp * 0.15
        cy = -bot_depth + clr + h_imp / 2.0
        impellers.append((d_imp, cy, h_imp, i, _s(row, t_col)))

    # Cumulative interior volume vs height, less an estimated impeller displacement.
    z_grid = np.linspace(-bot_depth, H, 400)
    rad_grid = np.array([radius_at(z) for z in z_grid])
    area_grid = np.pi * rad_grid ** 2
    dz = (H + bot_depth) / (len(z_grid) - 1) if len(z_grid) > 1 else 0.0
    cum_vessel = np.concatenate(
        [[0.0], np.cumsum((area_grid[:-1] + area_grid[1:]) / 2.0 * dz)])
    disp_below = np.zeros_like(z_grid)
    for (d_i, cy_i, h_i, _slot_i, _t_i) in impellers:
        r_i = d_i / 2.0
        v_disp = np.pi * r_i ** 2 * h_i * IMP_SOLIDITY
        z0, z1 = cy_i - h_i / 2.0, cy_i + h_i / 2.0
        if z1 > z0:
            disp_below += v_disp * np.clip((z_grid - z0) / (z1 - z0), 0.0, 1.0)
    cap_grid = np.clip(cum_vessel - disp_below, 0.0, None)

    return {
        "D": D, "H": H, "R": R,
        "bottom": bottom, "top": top,
        "bot_depth": bot_depth, "top_depth": top_depth,
        "bot_shape": bot_shape, "top_shape": top_shape,
        "full_height": full_height, "full_top": full_top,
        "show_full_height": show_full_height,
        "show_full_height_box": show_full_height_box,
        "impellers": impellers, "radius_at": radius_at,
        "z_grid": z_grid, "cap_grid": cap_grid,
        "total_L": float(cap_grid[-1]) * 1000.0,
    }


def brim_volume(row: pd.Series) -> float:
    """Return the brim-full working volume (L), or 0 when geometry is missing."""
    geom = geometry(row)
    return geom["total_L"] if geom else 0.0


def fill_state(geom: dict, fill_L: float | None) -> dict:
    """Liquid level (m above the bottom tangent line), fill %, wetted area and impeller
    warnings for ``fill_L`` litres in a vessel described by :func:`geometry`."""
    R, H = geom["R"], geom["H"]
    bot_depth, top_depth, bot_shape = geom["bot_depth"], geom["top_depth"], geom["bot_shape"]
    radius_at, impellers, total_L = geom["radius_at"], geom["impellers"], geom["total_L"]

    # Liquid surface height from the fill volume (invert the capacity curve).
    level = None
    fill_pct = None
    contact_area_m2 = None
    if fill_L is not None and fill_L > 0 and total_L > 0:
        fill_L = min(float(fill_L), total_L)
        level = float(np.interp(fill_L / 1000.0, geom["cap_grid"], geom["z_grid"]))
        fill_pct = fill_L / total_L * 100.0
        # Wetted wall area (m^2), measured from the true bottom of the dish.
        contact_area_m2 = estimate_jacket_area(
            geom["D"], level + bot_depth, geom["bottom"], geom["bot_depth"])

    lowest_imp_y = min((c[1] for c in impellers), default=0.0)

    # Flag impellers whose blades cut into the wall / dish, or spill past the
    # vessel ends (usually a mis-entered diameter, height or clearance).
    tol = R * 1e-3

    def _blade_band(cy_i: float, h_i: float, t_i: str, r_i: float) -> tuple[float, float]:
        """Return the drawn blade's (bottom, top) z-extent; chevrons draw a
        V taller than cy +/- h/2, so their apparent top must include the drop."""
        bottom = cy_i - h_i / 2.0
        if "chevron" in t_i.lower():
            v_drop = r_i * (bot_depth / R) if (bot_shape == "cone" and R > 0) else max(h_i, r_i * 0.5)
            return bottom, bottom + v_drop + h_i
        return bottom, cy_i + h_i / 2.0

    warnings: list[str] = []
    wall_hit: set[int] = set()
    for idx, (d_i, cy_i, h_i, _slot_i, t_i) in enumerate(impellers):
        r_i = d_i / 2.0
        zb, zt = cy_i - h_i / 2.0, cy_i + h_i / 2.0
        local_r = min(radius_at(z) for z in np.linspace(zb, zt, 12))
        if r_i > R + tol:
            warnings.append(f"Impeller {idx + 1}: ⌀{d_i * 1000:.0f} mm exceeds the tank ID "
                            f"⌀{geom['D'] * 1000:.0f} mm.")
            wall_hit.add(idx)
        elif "chevron" in t_i.lower():
            # For a chevron, we assume the blade angle matches the cone angle and
            # therefore the only meaningful wall check is whether the underside has
            # positive clearance above the dish bottom.
            clearance = (cy_i - h_i / 2.0) + bot_depth
            if clearance <= tol:
                warnings.append(f"Impeller {idx + 1}: the blade (⌀{d_i * 1000:.0f} mm) cuts into "
                                "the dish wall at its height.")
                wall_hit.add(idx)
        elif r_i > local_r + tol:
            warnings.append(f"Impeller {idx + 1}: the blade (⌀{d_i * 1000:.0f} mm) cuts into "
                            "the dish wall at its height.")
            wall_hit.add(idx)
        if zb < -bot_depth - tol:
            warnings.append(f"Impeller {idx + 1}: extends below the vessel bottom.")
            wall_hit.add(idx)
        if zt > H + top_depth + tol:
            warnings.append(f"Impeller {idx + 1}: extends above the vessel top.")
            wall_hit.add(idx)

    # Liquid level vs. the lowest impeller: the optimal scenario has the liquid
    # surface above the impeller. Fully dry -> red; partially submerged -> yellow.
    level_warning = ""
    level_warning_kind: str | None = None
    other_level_warning = ""
    if level is not None and impellers:
        imp_order = sorted(range(len(impellers)), key=lambda i: impellers[i][1])
        lowest_idx = imp_order[0]
        _, low_cy, low_h, _, low_t = impellers[lowest_idx]
        imp_bottom, imp_top = _blade_band(low_cy, low_h, low_t, impellers[lowest_idx][0] / 2.0)
        if level < imp_bottom - tol:
            level_warning_kind = "red"
            level_warning = "Liquid level is below the lowest impeller — it is not submerged."
        elif level < imp_top - tol:
            level_warning_kind = "yellow"
            level_warning = ("Liquid level is at the lowest impeller — raise the fill so it is "
                             "fully submerged.")

        # Non-overlapping impeller bands mean the surface can only ever straddle
        # one band, so at most one higher impeller needs this check.
        for idx in imp_order[1:]:
            d_i, cy_i, h_i, _, t_i = impellers[idx]
            imp_bottom_i, imp_top_i = _blade_band(cy_i, h_i, t_i, d_i / 2.0)
            if imp_bottom_i - tol < level < imp_top_i + tol:
                other_level_warning = f"Liquid level intersects impeller {idx + 1}"
                break

    return {
        "level": level, "fill_pct": fill_pct, "contact_area_m2": contact_area_m2,
        "lowest_imp_y": lowest_imp_y, "warnings": warnings, "wall_hit": wall_hit,
        "level_warning": level_warning, "level_warning_kind": level_warning_kind,
        "other_level_warning": other_level_warning,
    }


def fill_summary(row: pd.Series, fill_L: float | None, rpm: float | None = None) -> dict:
    """JSON-ready fill state for a vessel record (what the schematic annotates); with
    ``rpm`` it includes the predicted vortex surface (:mod:`core.vortex`)."""
    geom = geometry(row)
    if geom is None:
        return {"total_L": 0.0, "level_mm": None, "fill_pct": None, "contact_area_m2": None,
                "warnings": [], "level_warning": "", "level_warning_kind": None,
                "other_level_warning": "", "vortex": None}
    fs = fill_state(geom, fill_L)
    vortex = vortex_state(geom, row, fs["level"], rpm)
    if vortex is not None:
        vortex = {k: v for k, v in vortex.items() if k not in ("r_m", "surface_m")}
    return {
        "total_L": geom["total_L"],
        "level_mm": fs["level"] * 1000.0 if fs["level"] is not None else None,
        "fill_pct": fs["fill_pct"], "contact_area_m2": fs["contact_area_m2"],
        "warnings": fs["warnings"], "level_warning": fs["level_warning"],
        "level_warning_kind": fs["level_warning_kind"],
        "other_level_warning": fs["other_level_warning"],
        "vortex": vortex,
    }
