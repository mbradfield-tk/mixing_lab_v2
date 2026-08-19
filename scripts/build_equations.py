"""Build-time generator for the Equations Reference page.

Taipy cannot render LaTeX, so every display equation is pre-rendered to a PNG
at build time. The content lives in ``data/equations_source.json`` in THIS
repo (originally snapshotted from the Streamlit ``mixing_lab`` source with all
audit corrections applied — the sibling repo is no longer needed):

    {"sections": [{"title": "Section title", "items": [
        {"type": "header", "level": 3, "text": "Reynolds Number"},
        {"type": "latex",  "latex": "Re = \\frac{\\rho N D^2}{\\mu}"},
        {"type": "md",     "text": "prose / tables; inline math as $...$"}
    ]}]}

To add or change an equation: edit ``data/equations_source.json`` (new header +
latex + md items in an existing section, or a whole new section), then re-run:

    MPLCONFIGDIR=/tmp/mplconfig python scripts/build_equations.py

Each ``latex`` item is rendered via matplotlib mathtext (a LaTeX SUBSET — no
\\text in nested contexts, aligned environments are split on \\\\; a render
failure prints a warning and the equation falls back to raw text on the page),
palette-quantized, and embedded as a base64 PNG. ``$...$`` inline math in
md/header text is converted to unicode. Output is the self-contained
``data/equations_reference.json`` that ``pages/equations_reference.py`` loads
at import — restart the app to pick it up.
"""
from __future__ import annotations

import base64
import io
import json
import os
import re
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", "/tmp/mplconfig")
import matplotlib  # noqa: E402
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

HERE = Path(__file__).resolve().parent
V2_DIR = HERE.parent

SRC = V2_DIR / "data" / "equations_source.json"
OUT = V2_DIR / "data" / "equations_reference.json"


# ---------------------------------------------------------------------------
# LaTeX -> PNG (matplotlib mathtext)
# ---------------------------------------------------------------------------
def _prep_mathtext(latex: str) -> list[str]:
    """Return one or more mathtext-ready lines for a display equation."""
    s = latex.strip()
    s = s.replace(r"\begin{aligned}", "").replace(r"\end{aligned}", "")
    s = s.replace(r"\begin{align}", "").replace(r"\end{align}", "")
    s = s.replace(r"\lvert", "|").replace(r"\rvert", "|")
    s = s.replace(r"\lVert", r"\|").replace(r"\rVert", r"\|")
    s = s.replace(r"\text", r"\mathrm").replace(r"\!", "").replace(r"&", "")
    # split multi-line equations on the LaTeX row separator
    parts = [p.strip() for p in re.split(r"\\\\", s) if p.strip()]
    return parts or [s]


def _optimize_png(data: bytes) -> bytes:
    """Palette-quantize an RGBA equation PNG (~65% smaller, keeps alpha).

    Falls back to the original bytes if Pillow is unavailable or fails.
    """
    try:
        from PIL import Image

        img = Image.open(io.BytesIO(data)).quantize(
            colors=64, method=Image.Quantize.FASTOCTREE
        )
        buf = io.BytesIO()
        img.save(buf, "PNG", optimize=True)
        return buf.getvalue() if buf.tell() < len(data) else data
    except Exception:  # noqa: BLE001
        return data


def _render_latex(latex: str) -> str | None:
    """Render *latex* to a transparent PNG and return a base64 data URI."""
    lines = _prep_mathtext(latex)
    try:
        n = len(lines)
        fig = plt.figure(figsize=(0.1, 0.1))
        y0 = 0.5
        for i, line in enumerate(lines):
            y = 1.0 - (i + 0.5) / n if n > 1 else y0
            fig.text(0.01, y, f"${line}$", fontsize=17, color="#1a2b4a",
                     ha="left", va="center")
        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=160, bbox_inches="tight",
                    pad_inches=0.06, transparent=True)
        plt.close(fig)
        data = buf.getvalue()
        if not data or data[:4] != b"\x89PNG":
            return None
        data = _optimize_png(data)
        return "data:image/png;base64," + base64.b64encode(data).decode("ascii")
    except Exception as exc:  # noqa: BLE001
        print(f"  ! could not render: {latex[:60]}  ({exc})")
        plt.close("all")
        return None


# ---------------------------------------------------------------------------
# Inline math ($...$) -> Unicode plain text (for markdown tables/prose)
# ---------------------------------------------------------------------------
_GREEK = {
    r"\rho": "ρ", r"\mu": "μ", r"\nu": "ν", r"\varepsilon": "ε", r"\epsilon": "ε",
    r"\eta": "η", r"\lambda": "λ", r"\sigma": "σ", r"\pi": "π", r"\Delta": "Δ",
    r"\delta": "δ", r"\varphi": "φ", r"\phi": "φ", r"\theta": "θ", r"\tau": "τ",
    r"\gamma": "γ", r"\alpha": "α", r"\beta": "β", r"\omega": "ω", r"\Phi": "Φ",
    r"\Sigma": "Σ", r"\Omega": "Ω", r"\kappa": "κ", r"\zeta": "ζ", r"\xi": "ξ",
    r"\approx": "≈", r"\times": "×", r"\cdot": "·", r"\leq": "≤", r"\geq": "≥",
    r"\le": "≤", r"\ge": "≥", r"\pm": "±", r"\infty": "∞", r"\rightarrow": "→",
    r"\to": "→", r"\propto": "∝", r"\partial": "∂", r"\nabla": "∇", r"\ll": "≪",
    r"\gg": "≫", r"\sim": "~", r"\cdots": "···", r"\ldots": "…", r"\sqrt": "√",
}
_SUP = {"0": "⁰", "1": "¹", "2": "²", "3": "³", "4": "⁴", "5": "⁵",
        "6": "⁶", "7": "⁷", "8": "⁸", "9": "⁹", "-": "⁻", "+": "⁺", "n": "ⁿ"}


def _math_to_text(m: str) -> str:
    s = m
    s = re.sub(r"\\frac\{([^{}]*)\}\{([^{}]*)\}", r"(\1)/(\2)", s)
    s = re.sub(r"\\sqrt\{([^{}]*)\}", r"√(\1)", s)
    s = re.sub(r"\\(?:left|right|,|;|quad|qquad)", "", s)
    s = re.sub(r"\\mathrm\{([^{}]*)\}", r"\1", s)
    s = re.sub(r"\\text\{([^{}]*)\}", r"\1", s)
    for k, v in _GREEK.items():
        s = s.replace(k, v)
    # simple ^2 / ^{2} superscripts
    s = re.sub(r"\^\{([^{}]+)\}", lambda mm: "".join(_SUP.get(c, "^" + c) for c in mm.group(1)), s)
    s = re.sub(r"\^([0-9n\-+])", lambda mm: _SUP.get(mm.group(1), "^" + mm.group(1)), s)
    s = s.replace("_{", "_").replace("{", "").replace("}", "")
    s = re.sub(r"\\[a-zA-Z]+", lambda mm: mm.group(0)[1:], s)  # strip remaining commands' backslash
    return s


def _convert_inline(text: str) -> str:
    return re.sub(r"\$([^$]+)\$", lambda mm: _math_to_text(mm.group(1)), text)


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------
def main() -> None:
    if not SRC.exists():
        raise SystemExit(f"Equations source not found: {SRC}")
    print(f"Using source: {SRC}")
    print(f"Writing output to: {OUT}")
    sections = json.loads(SRC.read_text(encoding="utf-8"))["sections"]
    n_eq = 0
    out_sections = []
    for sec in sections:
        items_out = []
        for it in sec["items"]:
            kind = it.get("type")
            if kind == "latex":
                n_eq += 1
                items_out.append({"type": "latex", "latex": it["latex"],
                                  "img": _render_latex(it["latex"])})
            elif kind == "header":
                items_out.append({"type": "header", "level": int(it.get("level", 3)),
                                  "text": _convert_inline(it["text"])})
            else:
                items_out.append({"type": "md", "text": _convert_inline(it["text"])})
        out_sections.append({"title": sec["title"], "items": items_out})
        print(f"  section '{sec['title']}': {len(items_out)} items")

    OUT.write_text(json.dumps({"sections": out_sections}, ensure_ascii=False), encoding="utf-8")
    rendered = sum(1 for s in out_sections for it in s["items"]
                   if it["type"] == "latex" and it.get("img"))
    print(f"\n{len(out_sections)} sections, {n_eq} equations ({rendered} rendered) -> {OUT}")


if __name__ == "__main__":
    main()
