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

import matplotlib.patches as patches
import numpy as np
import pandas as pd
from matplotlib.patches import Arc
import matplotlib.pyplot as plt

from core.vessel_capacity import brim_volume, fill_state
from core.vessel_capacity import geometry as _geometry

__all__ = ["brim_volume", "build_vessel_schematic", "_geometry"]

_IMP_COLORS = ["#1976D2", "#F57C00", "#388E3C"]


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------
def _png(fig) -> bytes:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=140, facecolor="white")
    plt.close(fig)
    return buf.getvalue()


def _png_html(png: bytes) -> tuple[str, float]:
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
                           title: str = "", as_png: bool = False) -> dict:
    """Render the schematic; return {html (or png bytes), total_L, level_mm, fill_pct, ...}."""
    geom = _geometry(row)
    if geom is None:
        if as_png:
            raise ValueError("Insufficient geometry data (needs tank ID and height) to draw a "
                             "schematic.")
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

    fs = fill_state(geom, fill_L)
    level, fill_pct, contact_area_m2 = fs["level"], fs["fill_pct"], fs["contact_area_m2"]
    lowest_imp_y, warnings, wall_hit = fs["lowest_imp_y"], fs["warnings"], fs["wall_hit"]
    level_warning, level_warning_kind = fs["level_warning"], fs["level_warning_kind"]
    other_level_warning = fs["other_level_warning"]

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
    for idx_imp, (d_imp, cy, h_imp, slot, itype) in enumerate(impellers):
        color = _IMP_COLORS[slot % len(_IMP_COLORS)]
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
    png = _png(fig)
    html, aspect = ("", 0.0) if as_png else _png_html(png)
    return {
        "html": html,
        **({"png": png} if as_png else {}),
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
