"""Takeda chart theme: one colour set and layout for every web chart and PDF figure.

Builders pick colours from the constants here; :func:`apply` adds the shared layout
(fonts, axes, legend outside the plot area so it never covers data) at output time.
"""
from __future__ import annotations

import plotly.graph_objects as go

PRIMARY = "#E1251B"      # Takeda red
DARK_RED = "#9B1B14"
SLATE = "#5C6670"        # Takeda secondary grey
TEXT = "#2A2E33"
MUTED = "#6B7280"
AXIS = "#C9CED3"
GRID = "#ECEEF0"
FONT = "Segoe UI, Roboto, Helvetica Neue, Arial, sans-serif"

# Ordered series colours: brand red and slate first, then muted complementary hues.
SERIES = ["#E1251B", "#5C6670", "#1F5F99", "#E8A33D", "#2E7D5B", "#7B4F9E", "#00838F", "#A0522D"]
BLUE, AMBER, GREEN = SERIES[2], SERIES[3], SERIES[4]

# Damköhler regime thresholds (0.1 transitional, 1 mixing-limited) and other limits.
DA_THRESHOLDS = ((0.1, AMBER), (1.0, PRIMARY))
LIMIT = PRIMARY
REFERENCE = SLATE

# The current operating point is always a red star with a dark outline.
OP_MARKER = {"symbol": "star", "size": 15, "color": PRIMARY, "line": {"width": 1, "color": TEXT}}
OP_MARKER_3D = {"symbol": "diamond", "size": 6, "color": PRIMARY, "line": {"width": 1, "color": TEXT}}

# Sequential scale for surfaces / heatmaps: slate (low) through rose to Takeda red and dark red (high).
# No near-white stop, so low values stay visible against the light scene background.
SEQUENTIAL = [[0.0, "#3F4A54"], [0.3, "#8A939B"], [0.55, "#D99A93"], [0.78, "#E1251B"], [1.0, "#7A1008"]]

_LEGEND = {
    "orientation": "v", "x": 1.02, "xanchor": "left", "y": 1.0, "yanchor": "top",
    "bgcolor": "rgba(255,255,255,0)", "borderwidth": 0,
    "font": {"size": 11, "color": TEXT}, "itemsizing": "constant", "tracegroupgap": 4,
}
_AXIS = {
    "showline": True, "linecolor": AXIS, "linewidth": 1, "mirror": False,
    "gridcolor": GRID, "gridwidth": 1, "zeroline": False,
    "ticks": "outside", "tickcolor": AXIS, "ticklen": 4,
    "tickfont": {"size": 11, "color": MUTED}, "title": {"font": {"size": 12, "color": SLATE}, "standoff": 8},
    "automargin": True,
}
_SCENE_AXIS = {"backgroundcolor": "#F7F8F9", "gridcolor": AXIS, "zerolinecolor": AXIS,
               "showbackground": True, "tickfont": {"size": 10, "color": MUTED},
               "title": {"font": {"size": 11, "color": SLATE}}}


def apply(fig: go.Figure) -> go.Figure:
    """Apply the shared Takeda layout in place (and return the figure)."""
    lay = fig.layout
    has_title = bool(lay.title and lay.title.text)
    scenes_only = bool(fig.data) and all(t.type in ("surface", "scatter3d", "mesh3d") for t in fig.data)
    legend_title = lay.legend.title.text if lay.legend and lay.legend.title else None
    margin = ({"l": 10, "r": 10, "t": 60 if has_title else 40, "b": 10} if scenes_only
              else {"l": 60, "r": 20, "t": 64 if has_title else 40, "b": 50})
    fig.update_layout(
        template="plotly_white",
        font={"family": FONT, "size": 12, "color": TEXT},
        paper_bgcolor="#FFFFFF", plot_bgcolor="#FFFFFF",
        colorway=SERIES,
        margin={**margin, "pad": 2},
        legend={**_LEGEND, "title": {"text": legend_title, "font": {"size": 11, "color": SLATE}}},
        hoverlabel={"bgcolor": "#FFFFFF", "bordercolor": AXIS, "font": {"family": FONT, "color": TEXT}},
        modebar={"bgcolor": "rgba(255,255,255,0)", "color": MUTED, "activecolor": PRIMARY},
    )
    if has_title:
        fig.update_layout(title={"x": 0.0, "xref": "paper", "xanchor": "left", "y": 0.98, "yanchor": "top",
                                 "font": {"size": 15, "color": TEXT}})
    fig.update_xaxes(**_AXIS)
    fig.update_yaxes(**_AXIS)
    # Log axes: decades as powers of ten; in-between ticks stay unlabelled.
    log = {"exponentformat": "power", "minorloglabels": "none"}
    fig.update_xaxes(**log, selector={"type": "log"})
    fig.update_yaxes(**log, selector={"type": "log"})
    fig.update_scenes(xaxis=_SCENE_AXIS, yaxis=_SCENE_AXIS, zaxis=_SCENE_AXIS)
    for scene in fig.select_scenes():
        for ax in (scene.xaxis, scene.yaxis, scene.zaxis):
            if ax.type == "log":
                ax.update(dtick=1, exponentformat="power")
    for ann in fig.layout.annotations or ():
        ann.font.family = FONT
        if ann.font.color is None:
            ann.font.color = TEXT
        if ann.font.size is None:
            ann.font.size = 12
    for trace in fig.data:
        colorbar = getattr(trace, "colorbar", None)
        if colorbar is not None and getattr(trace, "showscale", None) is not False:
            # Keep a colour bar clear of the legend column.
            colorbar.update(thickness=14, outlinewidth=0, tickfont={"size": 10, "color": MUTED},
                            x=1.0 if not any(t.showlegend for t in fig.data) else 1.18)
    return fig
