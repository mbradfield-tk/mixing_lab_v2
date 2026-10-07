"""Shared figure helpers."""
from __future__ import annotations

import plotly.graph_objects as go


def empty(title: str | None = None, x_title: str | None = None, y_title: str | None = None,
          height: int | None = None) -> go.Figure:
    """Blank placeholder figure (only the given layout fields are set)."""
    fig = go.Figure()
    layout = {"title": title, "xaxis_title": x_title, "yaxis_title": y_title, "height": height}
    layout = {k: v for k, v in layout.items() if v is not None}
    if layout:
        fig.update_layout(**layout)
    return fig
