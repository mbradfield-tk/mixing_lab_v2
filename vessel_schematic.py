"""Draw a 2D cross-section schematic of a vessel, with an optional liquid line.

Ported from the Streamlit ``1_Reactor_Database.py`` "Draw Reactor" feature. The
vessel outline (straight walls + shape-aware bottom/top dishes), impellers and
shaft are rendered with matplotlib and returned as a self-contained HTML ``<img>``
(base64 PNG) so it can be shown in a Taipy ``part`` ``content`` iframe.

Given a fill volume (L) the liquid surface height is found by inverting the
vessel's cumulative capacity curve (which accounts for the dish volumes and an
estimated impeller metal displacement), and a fill line + shaded region is drawn.
"""
from __future__ import annotations

import base64
import io
import struct

import matplotlib

matplotlib.use("Agg")  # headless: render to a buffer, never a GUI window

import re

import matplotlib.patches as patches
import numpy as np
import pandas as pd
from matplotlib.patches import Arc
import matplotlib.pyplot as plt

from utils.calculations.heat_transfer import estimate_jacket_area

_IMP_COLORS = ["#1976D2", "#F57C00", "#388E3C"]
_IMP_SOLIDITY = 0.20  # fraction of the swept impeller disc that is solid metal


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


# ---------------------------------------------------------------------------
# Value helpers
# ---------------------------------------------------------------------------
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
def _geometry(row: pd.Series) -> dict | None:
    """Return the drawable geometry + cumulative capacity curve, or None."""
    D = _f(row, "D_tank_m")
    H = _f(row, "L_tan_tan_m")  # straight-wall (tan-tan) length
    if D <= 0 or H <= 0:
        return None
    R = D / 2.0
    bottom, top = _s(row, "bottom_dish"), _s(row, "top_dish")
    measured_bottom_depth = _f(row, "H_bottom_dish_m")
    bot_depth = measured_bottom_depth if measured_bottom_depth > 0 else _dish_depth(bottom, R)
    top_depth = _dish_depth(top, R)
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
    impellers = []  # (d_imp, cy, h_imp, color, itype)
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
        impellers.append((d_imp, cy, h_imp, _IMP_COLORS[i % len(_IMP_COLORS)], _s(row, t_col)))

    # Cumulative interior volume vs height, less an estimated impeller displacement.
    z_grid = np.linspace(-bot_depth, H, 400)
    rad_grid = np.array([radius_at(z) for z in z_grid])
    area_grid = np.pi * rad_grid ** 2
    dz = (H + bot_depth) / (len(z_grid) - 1) if len(z_grid) > 1 else 0.0
    cum_vessel = np.concatenate(
        [[0.0], np.cumsum((area_grid[:-1] + area_grid[1:]) / 2.0 * dz)])
    disp_below = np.zeros_like(z_grid)
    for (d_i, cy_i, h_i, _c_i, _t_i) in impellers:
        r_i = d_i / 2.0
        v_disp = np.pi * r_i ** 2 * h_i * _IMP_SOLIDITY
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
    geom = _geometry(row)
    return geom["total_L"] if geom else 0.0


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------
def _png_html(fig) -> tuple[str, float]:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=140, facecolor="white")
    plt.close(fig)
    png = buf.getvalue()
    w, h = struct.unpack(">II", png[16:24])  # PNG IHDR carries width/height
    data = base64.b64encode(png).decode("ascii")
    html = (
        "<!DOCTYPE html><html><head><meta charset='utf-8'>"
        "<style>html,body{margin:0;padding:0;height:100%;background:#fff;}"
        "img{display:block;width:100%;height:100%;object-fit:contain;}</style></head>"
        f"<body><img src='data:image/png;base64,{data}'/></body></html>"
    )
    return html, (w / h if h else 1.0)


def build_vessel_schematic(row: pd.Series, fill_L: float | None,
                           title: str = "") -> dict:
    """Render the schematic; return {html, total_L, level_mm, fill_pct}."""
    geom = _geometry(row)
    if geom is None:
        msg = ("<!DOCTYPE html><html><body style='font-family:sans-serif;"
               "color:#8a6d3b;padding:12px;'>Insufficient geometry data "
               "(needs tank ID and height) to draw a schematic.</body></html>")
        return {"html": msg, "aspect": 1.4, "total_L": 0.0, "level_mm": None, "fill_pct": None,
                "contact_area_m2": None, "level_warning": "", "level_warning_kind": None,
                "other_level_warning": ""}

    R, H = geom["R"], geom["H"]
    bot_depth, top_depth = geom["bot_depth"], geom["top_depth"]
    bot_shape, top_shape = geom["bot_shape"], geom["top_shape"]
    full_height, full_top = geom["full_height"], geom["full_top"]
    show_full_height = geom["show_full_height"]
    show_full_height_box = geom["show_full_height_box"]
    radius_at = geom["radius_at"]
    impellers = geom["impellers"]
    total_L = geom["total_L"]

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
    for idx, (d_i, cy_i, h_i, _c_i, t_i) in enumerate(impellers):
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

    # Size-aware padding so labels never crowd the vessel.
    drawn_top = max(H + top_depth, full_top if show_full_height else 0.0)
    total_h = bot_depth + drawn_top
    ref = max(R, total_h)
    gap = ref * 0.06
    left_pad = R * 0.85
    right_pad = R * 2.60
    bot_pad = gap + ref * 0.12
    top_pad = ref * 0.03
    if level is not None:
        top_pad += ref * 0.06

    fig, ax = plt.subplots(1, 1, figsize=(4.6, 4.6))
    ax.set_aspect("equal")
    # Square frame centred on the vessel centre-point: every reactor renders at
    # the same pixel size and centred, so the panel scale is consistent and the
    # reactor centre lands at the panel centre.
    cy_c = (drawn_top - bot_depth) / 2.0
    ex = R + max(left_pad, right_pad)
    ey = max(cy_c + bot_depth + bot_pad, (H + top_depth + top_pad) - cy_c)
    half = max(ex, ey)
    ax.set_xlim(-half, half)
    ax.set_ylim(cy_c - half, cy_c + half)
    ax.set_axis_off()
    fig.subplots_adjust(left=0, right=1, top=1, bottom=0)

    wall_lw, wall_color = 2.0, "#333333"

    # Straight walls
    ax.plot([-R, -R], [0, H], color=wall_color, lw=wall_lw)
    ax.plot([R, R], [0, H], color=wall_color, lw=wall_lw)

    # Bottom dish (shape-aware)
    if bot_depth <= 0 or bot_shape == "flat":
        ax.plot([-R, R], [0, 0], color=wall_color, lw=wall_lw)
    elif bot_shape == "cone":
        ax.plot([-R, 0], [0, -bot_depth], color=wall_color, lw=wall_lw)
        ax.plot([R, 0], [0, -bot_depth], color=wall_color, lw=wall_lw)
    else:
        ax.add_patch(Arc((0, 0), geom["D"], bot_depth * 2,
                         theta1=180, theta2=360, color=wall_color, lw=wall_lw))

    # Top dish (shape-aware)
    if top_depth <= 0 or top_shape == "flat":
        ax.plot([-R, R], [H, H], color=wall_color, lw=wall_lw)
    elif top_shape == "cone":
        ax.plot([-R, 0], [H, H + top_depth], color=wall_color, lw=wall_lw)
        ax.plot([R, 0], [H, H + top_depth], color=wall_color, lw=wall_lw)
    else:
        ax.add_patch(Arc((0, H), geom["D"], top_depth * 2,
                         theta1=0, theta2=180, color=wall_color, lw=wall_lw))

    if show_full_height_box:
        envelope_color = "#777777"
        dotted = (0, (1, 3))
        # Top-right reference corner: continue from the right-wall tangent and
        # mark the measured full-height level across the vessel width.
        ax.plot([R, R], [H, full_top], color=envelope_color,
            lw=1.2, ls=dotted, zorder=3)
        ax.plot([-R, R], [full_top, full_top], color=envelope_color,
            lw=1.2, ls=dotted, zorder=3)

    # Liquid fill (behind the impellers)
    if level is not None:
        z_liq = np.linspace(-bot_depth, level, 80)
        r_liq = np.array([radius_at(z) for z in z_liq])
        xs_liq = np.concatenate([r_liq, -r_liq[::-1]])
        ys_liq = np.concatenate([z_liq, z_liq[::-1]])
        ax.fill(xs_liq, ys_liq, color="#4FC3F7", alpha=0.30, lw=0, zorder=1)
        r_surf = radius_at(level)
        ax.plot([-r_surf, r_surf], [level, level],
                color="#0288D1", lw=1.6, zorder=2)
        ax.text(0, drawn_top + ref * 0.02, f"{fill_L:,.1f} L",
                ha="center", va="bottom", fontsize=10, fontweight="bold",
                color="#0277BD", zorder=2)

    # Impellers (clearance = dish bottom to blade underside)
    for idx_imp, (d_imp, cy, h_imp, color, itype) in enumerate(impellers):
        r_imp = d_imp / 2.0
        edge = "#C62828" if idx_imp in wall_hit else color
        elw = 2.4 if idx_imp in wall_hit else 1.5
        if "chevron" in itype.lower():
            # Downward chevron follows the conical-bottom angle when present.
            if bot_shape == "cone" and R > 0:
                v_drop = r_imp * (bot_depth / R)
            else:
                v_drop = max(h_imp, r_imp * 0.5)
            # Anchor the bottom centre vertex at the blade underside, i.e. the
            # recorded off-bottom clearance (cy - h_imp/2 = -bot_depth + clearance).
            base = cy - h_imp / 2.0
            pts = [
                (-r_imp, base + v_drop + h_imp),
                (0.0, base + h_imp),
                (r_imp, base + v_drop + h_imp),
                (r_imp, base + v_drop),
                (0.0, base),
                (-r_imp, base + v_drop),
            ]
            lab_y = base + (v_drop + h_imp) / 2.0  # centre of the drawn V for the label
            ax.add_patch(patches.Polygon(pts, closed=True, facecolor=color,
                                         edgecolor=edge, alpha=0.7, lw=elw, zorder=4))
        else:
            lab_y = cy
            ax.add_patch(patches.FancyBboxPatch(
                (-r_imp, cy - h_imp / 2.0), d_imp, h_imp,
                boxstyle="round,pad=0.002", facecolor=color, edgecolor=edge,
                alpha=0.7, lw=elw, zorder=4))
        # Leader line + label
        ax.plot([r_imp, R + right_pad * 0.12], [lab_y, lab_y],
                color=color, lw=0.6, alpha=0.5, zorder=3)
        ax.text(R + right_pad * 0.15, lab_y, f"Imp {idx_imp + 1}  ⌀{d_imp * 1000:.0f} mm",
                fontsize=10, fontweight="bold", va="center", ha="left", color=color)

    # Shaft
    shaft_top = H + top_depth * 0.9
    shaft_bot = min(lowest_imp_y - H * 0.05, 0.0) if impellers else 0.0
    ax.plot([0, 0], [shaft_bot, shaft_top], color="#555555", lw=1.5, zorder=3)

    # Dimension annotations (diameter below, height to the left)
    dim_color, dim_fs, wit_lw = "#555555", 10, 0.6
    arr_y = -bot_depth - gap
    for sx in (-R, R):
        ax.plot([sx, sx], [0, arr_y], color=dim_color, lw=wit_lw, zorder=2)
    ax.annotate("", xy=(R, arr_y), xytext=(-R, arr_y),
                arrowprops=dict(arrowstyle="<->", color=dim_color, lw=1))
    ax.text(0, arr_y - ref * 0.04, f"⌀ {geom['D'] * 1000:.0f} mm",
            ha="center", va="top", fontsize=dim_fs, fontweight="bold", color=dim_color)

    hx = -R - left_pad * 0.5
    for sy in (0.0, H):
        ax.plot([-R, hx], [sy, sy], color=dim_color, lw=wit_lw, zorder=2)
    ax.annotate("", xy=(hx, H), xytext=(hx, 0),
                arrowprops=dict(arrowstyle="<->", color=dim_color, lw=1))
    ax.text(hx - R * 0.06, H / 2, f"H {H * 1000:.0f} mm",
            ha="right", va="center", fontsize=dim_fs, fontweight="bold",
            color=dim_color, rotation=90)

    if show_full_height:
        leader_y = full_top + ref * 0.18
        elbow_x = R * 2.15
        leader_end_x = R * 3.35
        ax.plot([elbow_x, leader_end_x], [leader_y, leader_y],
            color="#777777", lw=1.2, zorder=2)
        ax.annotate("", xy=(R, full_top), xytext=(elbow_x, leader_y),
                arrowprops=dict(arrowstyle="->", color="#777777", lw=1.2))
        ax.text((elbow_x + leader_end_x) / 2.0, leader_y + ref * 0.025,
            f"H full {full_height * 1000:.0f} mm",
            ha="center", va="bottom", fontsize=dim_fs, fontweight="bold",
            color="#777777")

    # Bottom impeller off-bottom clearance (C): vessel bottom -> impeller underside.
    if impellers:
        y_bot = min(cy_i - h_i / 2.0 for (_d, cy_i, h_i, _c, _t) in impellers)
        clr_mm = (y_bot + bot_depth) * 1000.0
        cclr = "#00695C"
        cx = -R - left_pad * 0.22
        for sy in (-bot_depth, y_bot):
            ax.plot([-R, cx], [sy, sy], color=cclr, lw=wit_lw, zorder=2)
        ax.annotate("", xy=(cx, y_bot), xytext=(cx, -bot_depth),
                    arrowprops=dict(arrowstyle="<->", color=cclr, lw=1))
        ax.text(cx - R * 0.04, (-bot_depth + y_bot) / 2.0, f"C {clr_mm:.0f} mm",
                ha="right", va="center", fontsize=dim_fs, fontweight="bold",
                color=cclr, rotation=90)

    # Warnings (wall interference, liquid level vs. impeller) are surfaced by
    # the caller via the returned dict, not drawn on the image itself.

    # Labels are fixed pixel-size text, so their data-space extent depends on the
    # vessel proportions and can spill past the geometry-derived frame. Measure
    # the rendered text boxes and widen the square frame until everything fits —
    # expanding rescales the axes while the text keeps its pixel size, so the
    # required extent must be found iteratively (converges geometrically).
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    for _ in range(10):
        inv = ax.transData.inverted()
        needed = half
        for artist in ax.texts:
            bb = artist.get_window_extent(renderer=renderer)
            (x0, y0), (x1, y1) = inv.transform([(bb.x0, bb.y0), (bb.x1, bb.y1)])
            needed = max(needed, abs(x0), abs(x1), abs(y0 - cy_c), abs(y1 - cy_c))
        if needed <= half * 1.001:
            break
        half = needed * 1.02  # small breathing margin
        ax.set_xlim(-half, half)
        ax.set_ylim(cy_c - half, cy_c + half)

    # Title is intentionally not drawn on the canvas (it would offset the vessel
    # from centre); the vessel name is shown in the page selector instead.
    html, aspect = _png_html(fig)
    return {
        "html": html,
        "aspect": aspect,
        "total_L": total_L,
        "level_mm": (level * 1000.0) if level is not None else None,
        "fill_pct": fill_pct,
        "contact_area_m2": contact_area_m2,
        "warnings": warnings,
        "wall_cut": bool(warnings),
        "level_warning": level_warning,
        "level_warning_kind": level_warning_kind,
        "other_level_warning": other_level_warning,
    }
