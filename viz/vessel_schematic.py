"""Draw a 2D cross-section schematic of a vessel, with an optional liquid line.

Ported from the Streamlit ``1_Reactor_Database.py`` "Draw Reactor" feature. The
vessel outline (straight walls + shape-aware bottom/top dishes), impellers and
shaft are rendered with matplotlib and returned as a self-contained HTML ``<img>``
(base64 PNG); the API serves it as a PNG.

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
from core.vortex import vortex_state

__all__ = ["brim_volume", "build_vessel_schematic", "_geometry"]

_IMP_COLORS = ["#1976D2", "#F57C00", "#388E3C"]
_VESSEL_IN = 3.0  # drawn size (inches) of the vessel's longest dimension


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------
def _dish_drop(r: float, geom: dict) -> float:
    """Depth of the drawn bottom below the tangent line at radius ``r``."""
    return _head_depth(r, geom["R"], geom["bot_depth"], geom["bot_shape"])


def _head_depth(r: float, R: float, depth: float, shape: str) -> float:
    """Distance of a drawn head (dish) from its tangent line at radius ``r``."""
    if depth <= 0 or shape == "flat":
        return 0.0
    x = min(r / R, 1.0)
    return depth * (1.0 - x) if shape == "cone" else depth * float(np.sqrt(1.0 - x * x))


def _fmt_L(v: float) -> str:
    """Fill volume to about three significant figures, with thousands separators."""
    if v >= 100:
        return f"{v:,.0f}"
    return f"{v:.3g}" if v < 10 else f"{v:.1f}"


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
                           title: str = "", as_png: bool = False,
                           rpm: float | None = None) -> dict:
    """Render the schematic; return {html (or png bytes), total_L, level_mm, fill_pct, ...}.

    With ``rpm`` the liquid is drawn with the predicted vortex surface and the static
    level as a dashed reference line.
    """
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
    vortex = vortex_state(geom, row, level, rpm)

    # Fixed drawing scale: the vessel's longest dimension is _VESSEL_IN inches, so every
    # annotation offset below is in inches (u = metres per inch) and the labels keep the
    # same size relative to the vessel whatever its proportions.
    drawn_top = max(H + top_depth, full_top if show_full_height else 0.0)
    total_h = bot_depth + drawn_top
    u = max(2 * R, total_h) / _VESSEL_IN

    # Generous provisional frame (content is measured and the frame cropped at the end).
    x0, x1 = -R - 1.5 * u, R + 3.0 * u
    y0, y1 = -bot_depth - 1.0 * u, drawn_top + 1.0 * u
    fig = plt.figure(figsize=((x1 - x0) / u, (y1 - y0) / u))
    ax = fig.add_axes((0, 0, 1, 1))
    ax.set_aspect("equal")
    ax.set_xlim(x0, x1)
    ax.set_ylim(y0, y1)
    ax.set_axis_off()

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
    fill_label = None
    if level is not None and vortex is not None:
        r_v = np.asarray(vortex["r_m"])
        s_v = np.asarray(vortex["surface_m"])
        xs = np.concatenate([-r_v[::-1], r_v])
        roof = np.array([H + _head_depth(abs(x), R, top_depth, top_shape) for x in xs])
        surf = np.minimum(np.concatenate([s_v[::-1], s_v]), roof)
        bot = np.array([-_dish_drop(abs(x), geom) for x in xs])
        ax.fill_between(xs, bot, surf, where=surf > bot + 1e-9,
                        color="#4FC3F7", alpha=0.30, lw=0, zorder=1)
        ax.plot(xs, surf, color="#0288D1", lw=1.6, zorder=2)
        r_surf = radius_at(level)
        ax.plot([-r_surf, r_surf], [level, level], color="#0288D1", lw=0.9,
                ls=(0, (4, 3)), alpha=0.7, zorder=2)
        fill_label = ax.text(0, drawn_top + 0.08 * u, f"{_fmt_L(fill_L)} L @ {rpm:,.0f} rpm",
                ha="center", va="bottom", fontsize=10, fontweight="bold",
                color="#0277BD", zorder=2)
    elif level is not None:
        z_liq = np.linspace(-bot_depth, level, 80)
        r_liq = np.array([radius_at(z) for z in z_liq])
        xs_liq = np.concatenate([r_liq, -r_liq[::-1]])
        ys_liq = np.concatenate([z_liq, z_liq[::-1]])
        ax.fill(xs_liq, ys_liq, color="#4FC3F7", alpha=0.30, lw=0, zorder=1)
        r_surf = radius_at(level)
        ax.plot([-r_surf, r_surf], [level, level],
                color="#0288D1", lw=1.6, zorder=2)
        fill_label = ax.text(0, drawn_top + 0.08 * u, f"{_fmt_L(fill_L)} L",
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
        ax.plot([r_imp, R + 0.15 * u], [lab_y, lab_y],
                color=color, lw=0.6, alpha=0.5, zorder=3)
        ax.text(R + 0.2 * u, lab_y, f"Imp {idx_imp + 1}  ⌀{d_imp * 1000:.0f} mm",
                fontsize=10, fontweight="bold", va="center", ha="left", color=color)

    # Shaft
    shaft_top = H + top_depth * 0.9
    shaft_bot = min(lowest_imp_y - H * 0.05, 0.0) if impellers else 0.0
    ax.plot([0, 0], [shaft_bot, shaft_top], color="#555555", lw=1.5, zorder=3)

    # Dimension annotations: diameter below; on the left the clearance C (inner) and the
    # straight-side height H (outer), with C's label under its arrow so the H witness
    # line at the tangent never runs through it.
    dim_color, dim_fs, wit_lw = "#555555", 10, 0.6
    arr_y = -bot_depth - 0.3 * u
    for sx in (-R, R):
        ax.plot([sx, sx], [0, arr_y], color=dim_color, lw=wit_lw, zorder=2)
    ax.annotate("", xy=(R, arr_y), xytext=(-R, arr_y),
                arrowprops=dict(arrowstyle="<->", color=dim_color, lw=1))
    ax.text(0, arr_y - 0.06 * u, f"⌀ {geom['D'] * 1000:.0f} mm",
            ha="center", va="top", fontsize=dim_fs, fontweight="bold", color=dim_color)

    hx = -R - 0.6 * u
    for sy in (0.0, H):
        ax.plot([-R, hx], [sy, sy], color=dim_color, lw=wit_lw, zorder=2)
    ax.annotate("", xy=(hx, H), xytext=(hx, 0),
                arrowprops=dict(arrowstyle="<->", color=dim_color, lw=1))
    ax.text(hx - 0.05 * u, H / 2, f"H {H * 1000:.0f} mm",
            ha="right", va="center", fontsize=dim_fs, fontweight="bold",
            color=dim_color, rotation=90)

    if show_full_height:
        label_x = R + 0.35 * u
        if fill_label is not None:  # the centred fill label sits at the same height
            bb = fill_label.get_window_extent(renderer=fig.canvas.get_renderer())
            label_x = max(label_x, ax.transData.inverted().transform((bb.x1, 0))[0] + 0.15 * u)
        ax.annotate(f"H full {full_height * 1000:.0f} mm", xy=(R, full_top),
                    xytext=(label_x, full_top + 0.2 * u), ha="left", va="center",
                    fontsize=dim_fs, fontweight="bold", color="#777777",
                    arrowprops=dict(arrowstyle="->", color="#777777", lw=1.2))

    # Bottom impeller off-bottom clearance (C): vessel bottom -> impeller underside.
    if impellers:
        y_bot = min(cy_i - h_i / 2.0 for (_d, cy_i, h_i, _c, _t) in impellers)
        clr_mm = (y_bot + bot_depth) * 1000.0
        cclr = "#00695C"
        cx = -R - 0.22 * u
        for sy in (-bot_depth, y_bot):
            ax.plot([-R, cx], [sy, sy], color=cclr, lw=wit_lw, zorder=2)
        label_y = -bot_depth - 0.06 * u
        if y_bot + bot_depth >= 0.2 * u:
            ax.annotate("", xy=(cx, y_bot), xytext=(cx, -bot_depth),
                        arrowprops=dict(arrowstyle="<->", color=cclr, lw=1))
        else:
            # Too short for inside arrowheads: point at the extension lines from outside.
            tail = 0.15 * u
            ax.plot([cx, cx], [-bot_depth, y_bot], color=cclr, lw=1, zorder=2)
            for tip, start in ((-bot_depth, -bot_depth - tail), (y_bot, y_bot + tail)):
                ax.annotate("", xy=(cx, tip), xytext=(cx, start),
                            arrowprops=dict(arrowstyle="->", color=cclr, lw=1))
            label_y -= tail
        ax.text(cx + 0.08 * u, label_y, f"C {clr_mm:.0f} mm",
                ha="right", va="top", fontsize=dim_fs, fontweight="bold", color=cclr)

    # Warnings (wall interference, liquid level vs. impeller) are surfaced by
    # the caller via the returned dict, not drawn on the image itself.

    # Crop the frame to everything drawn. The figure is resized with the limits, so the
    # scale (u metres per inch) and therefore every text extent stays fixed.
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    inv = ax.transData.inverted()
    xs, ys = [-R, R], [-bot_depth, drawn_top]
    for artist in [*ax.lines, *ax.patches, *ax.texts]:
        bb = artist.get_window_extent(renderer=renderer)
        if bb.width <= 0 and bb.height <= 0:
            continue
        (bx0, by0), (bx1, by1) = inv.transform([(bb.x0, bb.y0), (bb.x1, bb.y1)])
        xs += [bx0, bx1]
        ys += [by0, by1]
    m = 0.08 * u
    x0, x1, y0, y1 = min(xs) - m, max(xs) + m, min(ys) - m, max(ys) + m
    ax.set_xlim(x0, x1)
    ax.set_ylim(y0, y1)
    fig.set_size_inches((x1 - x0) / u, (y1 - y0) / u)

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
