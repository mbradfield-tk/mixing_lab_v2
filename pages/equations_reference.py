"""Equations Reference page (Taipy).

Ported from the Streamlit ``equations_reference.py``. Taipy GUI cannot render
LaTeX, so every equation is pre-rendered to a PNG image at build time (see
``scripts/build_equations.py``) and embedded as a base64 data URI in
``data/equations_reference.json``. This page loads that JSON and lays the
content out with one expandable section per topic; inline symbols in the prose
and tables are shown as Unicode text.

To refresh after editing the source equations, re-run::

    python scripts/build_equations.py
"""
from __future__ import annotations

import json
from pathlib import Path

from taipy.gui import Markdown

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
_JSON = DATA_DIR / "equations_reference.json"


def _esc(s: str) -> str:
    """Escape characters that break Taipy's markdown -> JSX conversion.

    Literal ``<`` / ``>`` (e.g. "Re < 10 000") and ``{`` / ``}`` are otherwise
    interpreted as JSX tags/expressions and raise a SyntaxError."""
    return (s.replace("<", "&lt;").replace(">", "&gt;")
             .replace("{", "&#123;").replace("}", "&#125;"))


def _build_markdown() -> str:
    md = [
        "# 📐 Equations Reference",
        "",
        "Reference correlations and equations used throughout Mixing Lab. Each "
        "equation is rendered as an image (Taipy cannot display LaTeX directly); "
        "symbols in the tables are shown as plain text. Expand a section for details.",
        "",
    ]
    if not _JSON.exists():
        md.append("_Equation data not found — run `python scripts/build_equations.py` to generate it._")
        return "\n".join(md)

    data = json.loads(_JSON.read_text(encoding="utf-8"))
    for sec in data.get("sections", []):
        title = str(sec.get("title", "Section"))
        md.append("<|part|class_name=va-card|")
        md.append(f"<|{title}|expandable|expanded=False|")
        md.append("")
        for item in sec.get("items", []):
            itype = item.get("type")
            if itype == "header":
                hashes = "#" * int(item.get("level", 3))
                md.append(f"{hashes} {_esc(item.get('text', ''))}")
                md.append("")
            elif itype == "latex":
                img = item.get("img")
                if img:
                    md.append("<|part|class_name=eq-img|")
                    md.append(f"![equation]({img})")
                    md.append("|>")
                else:
                    md.append(f"`{item.get('latex', '')}`")
                md.append("")
            else:  # md / prose / tables
                md.append(_esc(item.get("text", "")))
                md.append("")
        md.append("|>")
        md.append("|>")
        md.append("")
    return "\n".join(md)


page = Markdown(_build_markdown())
