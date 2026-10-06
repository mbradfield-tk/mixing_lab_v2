"""Chrome-free PNG rendering of Plotly figures with matplotlib.

Covers what the PDF reports use — scatter lines/markers/filled polygons, bars,
subplot grids, secondary y axes, log axes, line/rect shapes (incl. ``add_hline`` /
``add_vline``), annotations and legends. 3D traces are drawn as a placeholder note.
Fidelity is close to, not identical with, Plotly's own (kaleido) output.
"""
from __future__ import annotations

import io
import re

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib import transforms  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from matplotlib.patches import Rectangle  # noqa: E402

PLOTLY_COLORWAY = ["#636efa", "#EF553B", "#00cc96", "#ab63fa", "#FFA15A",
                   "#19d3f3", "#FF6692", "#B6E880", "#FF97FF", "#FECB52"]
_DASH = {"dot": ":", "dash": "--", "dashdot": "-.", "longdash": "--", "longdashdot": "-.",
         "solid": "-", None: "-"}
_SYMBOL = {"circle": "o", "square": "s", "diamond": "D", "star": "*", "cross": "P",
           "x": "X", "triangle-up": "^", "triangle-down": "v"}
_PX = 0.75  # plotly px -> matplotlib points


def _color(value, default=None):
    """Plotly colour string -> matplotlib colour (RGBA tuple for rgb()/rgba())."""
    if value is None:
        return default
    m = re.fullmatch(r"\s*rgba?\(([^)]*)\)\s*", str(value))
    if not m:
        return value
    parts = [float(p) for p in m.group(1).split(",")]
    r, g, b = (p / 255.0 for p in parts[:3])
    return (r, g, b, parts[3] if len(parts) > 3 else 1.0)


def _with_alpha(color, alpha: float):
    """(colour, alpha): an rgba() colour's own alpha multiplies the trace opacity."""
    if isinstance(color, tuple) and len(color) == 4:
        return color[:3], color[3] * alpha
    return color, alpha


def _text(value) -> str:
    s = "" if value is None else str(value)
    s = re.sub(r"<br\s*/?>", "\n", s)
    return re.sub(r"<[^>]+>", "", s)


def _axis_id(ref: str | None, axis: str) -> str:
    """'x2' / 'x2 domain' / None -> layout key 'xaxis2' (axis = 'x' | 'y')."""
    ref = (ref or axis).split()[0]
    suffix = ref[1:]
    return f"{axis}axis{suffix}"


class _Renderer:
    def __init__(self, fig, scale: float):
        self.fig = fig
        lay = fig.layout
        self.w_px = lay.width or 700
        self.h_px = lay.height or 450
        m = lay.margin
        self.ml = m.l if m.l is not None else 80
        self.mr = m.r if m.r is not None else 80
        self.mt = m.t if m.t is not None else 100
        self.mb = m.b if m.b is not None else 80
        self.mfig = plt.figure(figsize=(self.w_px / 100, self.h_px / 100), dpi=100 * scale)
        self.colorway = list(lay.colorway or (lay.template.layout.colorway if lay.template else None)
                             or PLOTLY_COLORWAY)
        self.paper = self._add_axes((0, 1), (0, 1), zorder=-1)
        self.paper.set_axis_off()
        self.axes: dict[tuple[str, str], plt.Axes] = {}
        self.handles: list = []

    # -- layout helpers ------------------------------------------------------
    def _rect(self, xdom, ydom):
        pw = self.w_px - self.ml - self.mr
        ph = self.h_px - self.mt - self.mb
        x0 = (self.ml + xdom[0] * pw) / self.w_px
        y0 = (self.mb + ydom[0] * ph) / self.h_px
        return [x0, y0, (xdom[1] - xdom[0]) * pw / self.w_px, (ydom[1] - ydom[0]) * ph / self.h_px]

    def _add_axes(self, xdom, ydom, **kw):
        return self.mfig.add_axes(self._rect(xdom, ydom), **kw)

    def _layout_axis(self, key: str):
        return self.fig.layout[key] if key in self.fig.layout else None

    def ax(self, xref: str | None, yref: str | None) -> plt.Axes:
        xk, yk = _axis_id(xref, "x"), _axis_id(yref, "y")
        if (xk, yk) in self.axes:
            return self.axes[(xk, yk)]
        xa, ya = self._layout_axis(xk), self._layout_axis(yk)
        overlay = ya.overlaying if ya is not None and ya.overlaying else None
        if overlay:
            base = self.ax(xref, overlay)
            a = base.twinx()
            a.set_zorder(base.get_zorder() + 1)
            a.patch.set_visible(False)
        else:
            xdom = tuple(xa.domain) if xa is not None and xa.domain else (0, 1)
            ydom = tuple(ya.domain) if ya is not None and ya.domain else (0, 1)
            a = self._add_axes(xdom, ydom)
            a.set_facecolor(_color(self.fig.layout.plot_bgcolor, "#E5ECF6"))
            a.grid(True, color="white", linewidth=0.8)
            a.set_axisbelow(True)
            for side in ("top", "right"):
                a.spines[side].set_visible(False)
        self._style_axis(a.xaxis, xa, a.set_xscale, a.set_xlim, a.set_xlabel)
        self._style_axis(a.yaxis, ya, a.set_yscale, a.set_ylim, a.set_ylabel, a=a)
        if ya is not None and ya.side == "right":
            a.yaxis.tick_right()
            a.yaxis.set_label_position("right")
        self.axes[(xk, yk)] = a
        return a

    @staticmethod
    def _style_axis(axis, spec, set_scale, set_lim, set_label, a=None):
        axis.label.set_size(8)
        for t in axis.get_ticklabels():
            t.set_fontsize(7)
        axis.set_tick_params(labelsize=7)
        if spec is None:
            return
        if spec.type == "log":
            set_scale("log")
        if spec.range is not None and spec.autorange is not True:
            lo, hi = spec.range
            if spec.type == "log":
                lo, hi = 10 ** lo, 10 ** hi
            set_lim(lo, hi)
        if spec.title and spec.title.text:
            set_label(_text(spec.title.text), fontsize=8)
        if spec.visible is False:
            axis.set_visible(False)
        if spec.autorange == "reversed" and a is not None:
            a.invert_yaxis()

    def _transform(self, a: plt.Axes, xref: str | None, yref: str | None):
        def pick(ref, data_t, axes_t, paper_t):
            ref = ref or ""
            if ref == "paper":
                return paper_t
            return axes_t if ref.endswith("domain") else data_t
        return transforms.blended_transform_factory(
            pick(xref, a.transData, a.transAxes, self.paper.transAxes),
            pick(yref, a.transData, a.transAxes, self.paper.transAxes))

    # -- traces --------------------------------------------------------------
    def trace(self, i: int, t) -> None:
        kind = t.type
        if kind in ("surface", "scatter3d", "mesh3d"):
            self.paper.text(0.5, 0.5, "3D chart (interactive view only)", ha="center",
                            va="center", fontsize=9, color="#5C6670",
                            transform=self.paper.transAxes)
            return
        a = self.ax(t.xaxis, t.yaxis)
        color = self.colorway[i % len(self.colorway)]
        label = t.name if (t.showlegend is not False and t.name) else None
        if kind == "bar":
            self._bar(a, t, color, label)
        elif kind == "scatter":
            self._scatter(a, t, color, label)

    def _scatter(self, a, t, color, label):
        x = list(t.x) if t.x is not None else []
        y = list(t.y) if t.y is not None else []
        if not y:
            return
        if not x:
            x = list(range(len(y)))
        line_color = _color(t.line.color if t.line else None, color)
        alpha = t.opacity if t.opacity is not None else 1.0
        mode = t.mode or ("lines+markers" if len(y) < 20 else "lines")
        if t.fill == "toself":
            fc, fa = _with_alpha(_color(t.fillcolor, line_color), alpha)
            a.fill(x, y, color=fc, alpha=fa, linewidth=0,
                   label=label if "lines" not in mode else None)
        elif t.fill in ("tozeroy", "tonexty"):
            fc, fa = _with_alpha(_color(t.fillcolor, line_color), 0.3 * alpha)
            a.fill_between(x, y, 0, color=fc, alpha=fa)
        width = (t.line.width if t.line and t.line.width is not None else 2) * _PX
        style = dict(color=line_color, alpha=alpha)
        if "lines" in mode and width > 0:
            a.plot(x, y, linestyle=_DASH.get(t.line.dash if t.line else None, "-"),
                   linewidth=width, label=label, **style)
            label = None
        if "markers" in mode:
            mk = t.marker
            mcolor = _color(mk.color if mk and isinstance(mk.color, str) else None, line_color)
            edge = _color(mk.line.color if mk and mk.line else None, mcolor)
            a.plot(x, y, linestyle="none", marker=_SYMBOL.get(mk.symbol if mk else None, "o"),
                   markersize=(mk.size if mk and mk.size else 6) * _PX * 1.2, color=mcolor,
                   markeredgecolor=edge, label=label, alpha=alpha)

    def _bar(self, a, t, color, label):
        cats, vals = (list(t.y), list(t.x)) if t.orientation == "h" else (list(t.x), list(t.y))
        c = _color(t.marker.color if t.marker and isinstance(t.marker.color, str) else None, color)
        bars = (a.barh if t.orientation == "h" else a.bar)(cats, vals, color=c, label=label)
        if t.text is not None:
            a.bar_label(bars, labels=[_text(s) for s in t.text], fontsize=7, padding=2)

    # -- shapes / annotations / titles --------------------------------------
    def shape(self, sh) -> None:
        a = self.ax(sh.xref if sh.xref != "paper" else None, sh.yref if sh.yref != "paper" else None)
        tr = self._transform(a, sh.xref, sh.yref)
        line = sh.line
        color = _color(line.color if line else None, "#444444")
        width = (line.width if line and line.width is not None else 2) * _PX
        dash = _DASH.get(line.dash if line else None, "-")
        self._include_in_range(a, sh)
        if sh.type == "line":
            a.add_line(Line2D([sh.x0, sh.x1], [sh.y0, sh.y1], transform=tr, color=color,
                              linewidth=width, linestyle=dash, clip_on=False))
        elif sh.type == "rect":
            a.add_patch(Rectangle((sh.x0, sh.y0), sh.x1 - sh.x0, sh.y1 - sh.y0, transform=tr,
                                  facecolor=_color(sh.fillcolor, "none"),
                                  alpha=sh.opacity if sh.opacity is not None else 1.0,
                                  edgecolor=color if width > 0 else "none", linewidth=width,
                                  clip_on=False))

    def _include_in_range(self, a, sh) -> None:
        """Plotly autoranges over data-referenced shapes; mirror that on unfixed axes."""
        def data_ref(ref, axis):
            return bool(ref) and ref != "paper" and not ref.endswith("domain") \
                and ref.startswith(axis)
        for axis, ref, lo, hi in (("y", sh.yref, sh.y0, sh.y1), ("x", sh.xref, sh.x0, sh.x1)):
            spec = self._layout_axis(_axis_id(ref, axis))
            if not data_ref(ref, axis) or (spec is not None and spec.range is not None):
                continue
            get_lim, set_lim = ((a.get_ylim, a.set_ylim) if axis == "y" else (a.get_xlim, a.set_xlim))
            cur = get_lim()
            vals = [v for v in (lo, hi) if v is not None]
            if vals:
                pad = 0.04 * (max(cur[1], *vals) - min(cur[0], *vals) or 1.0)
                new_lo, new_hi = min(cur[0], min(vals) - pad), max(cur[1], max(vals) + pad)
                if (new_lo, new_hi) != cur and not (axis == "y" and a.get_yscale() == "log"):
                    set_lim(new_lo if min(vals) < cur[0] else cur[0],
                            new_hi if max(vals) > cur[1] else cur[1])

    def annotation(self, an) -> None:
        if an.text is None:
            return
        xref, yref = an.xref or "x", an.yref or "y"
        if xref == "paper" and yref == "paper":
            a, tr = self.paper, self.paper.transAxes
        else:
            a = self.ax(None if xref == "paper" else xref, None if yref == "paper" else yref)
            tr = self._transform(a, xref, yref)
        ha = {"left": "left", "right": "right"}.get(an.xanchor, "center")
        va = {"top": "top", "bottom": "bottom"}.get(an.yanchor, "center")
        a.text(an.x if an.x is not None else 0.5, an.y if an.y is not None else 0.5,
               _text(an.text), transform=tr, ha=ha, va=va, fontsize=7,
               color=_color(an.font.color if an.font else None, "#2A3F5F"), clip_on=False)

    def finish(self) -> bytes:
        lay = self.fig.layout
        title = lay.title.text if lay.title else None
        if title:
            self.mfig.suptitle(_text(title), fontsize=10, y=1 - 12 / self.h_px, va="top")
        handles, labels = [], []
        for a in self.axes.values():
            for h, lbl in zip(*a.get_legend_handles_labels()):
                if lbl and not lbl.startswith("_") and lbl not in labels:
                    handles.append(h)
                    labels.append(lbl)
        if handles and lay.showlegend is not False:
            horizontal = lay.legend and lay.legend.orientation == "h"
            self.mfig.legend(handles, labels, fontsize=7, frameon=False,
                             loc="upper center" if horizontal else "upper right",
                             ncol=min(len(labels), 4) if horizontal else 1,
                             bbox_to_anchor=(0.5, 1 - 28 / self.h_px) if horizontal else (0.99, 0.95))
        buf = io.BytesIO()
        # Tight box stands in for Plotly's automargin (long tick labels, outside legends).
        self.mfig.savefig(buf, format="png", bbox_inches="tight", pad_inches=0.15)
        plt.close(self.mfig)
        return buf.getvalue()


def render_png(fig, scale: float = 2.0) -> bytes:
    """PNG bytes of a Plotly figure drawn with matplotlib (no browser needed)."""
    r = _Renderer(fig, scale)
    for i, t in enumerate(fig.data):
        r.trace(i, t)
    if not r.axes and not fig.data:
        r.ax(None, None)
    for sh in fig.layout.shapes or ():
        r.shape(sh)
    for an in fig.layout.annotations or ():
        r.annotation(an)
    return r.finish()
