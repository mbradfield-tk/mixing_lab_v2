"""Build-time generator for the Equations Reference page.

Parses the original Streamlit ``equations_reference.py`` (in the sibling
``mixing_lab`` repo), extracts every section (``st.expander``) and its ordered
items (``st.header`` / ``st.latex`` / ``st.markdown`` / ...), pre-renders each
LaTeX equation to a PNG via matplotlib mathtext, and writes a self-contained
JSON (``data/equations_reference.json``) with the equation images embedded as
base64 data URIs.

Run once (or whenever the source changes):

    python scripts/build_equations.py

The Taipy page (``pages/equations_reference.py``) then loads the JSON at import
time — so the running app needs neither matplotlib nor the Streamlit source.
"""
from __future__ import annotations

import ast
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

# ---------------------------------------------------------------------------
# Locate the original Streamlit equations_reference.py
# ---------------------------------------------------------------------------
# 1) Explicit override via env var (highest priority):
#      MIXING_LAB_STREAMLIT_SRC=/some/path/equations_reference.py python build_equations.py
# 2) Otherwise, try a list of known locations in order (local dev first,
#    then server layout). First existing path wins.
_SRC_CANDIDATES = [
    # Local dev on Mac: sibling repo alongside mixing_lab_2
    V2_DIR.parent / "mixing_lab" / "pages" / "equations_reference.py",
    # Server layout
    Path("/opt/streamlit/mixing_lab/pages/equations_reference.py"),
]

def _resolve_src() -> Path:
    override = os.environ.get("MIXING_LAB_STREAMLIT_SRC")
    if override:
        p = Path(override).expanduser().resolve()
        if not p.exists():
            raise SystemExit(f"MIXING_LAB_STREAMLIT_SRC set but not found: {p}")
        return p
    for cand in _SRC_CANDIDATES:
        if cand.exists():
            return cand
    tried = "\n  ".join(str(c) for c in _SRC_CANDIDATES)
    raise SystemExit(
        "Could not find the Streamlit equations_reference.py.\n"
        f"Tried:\n  {tried}\n"
        "Set MIXING_LAB_STREAMLIT_SRC=/path/to/equations_reference.py to override."
    )

SRC = _resolve_src()
OUT = V2_DIR / "data" / "equations_reference.json"

_TEXT_METHODS = {"header", "subheader", "markdown", "caption", "write",
                 "info", "warning", "success", "latex"}
_PREFIX = {"info": "ℹ️ ", "warning": "⚠️ ", "success": "✅ "}


# ---------------------------------------------------------------------------
# AST extraction
# ---------------------------------------------------------------------------
def _extract_items(body: list) -> list[tuple[str, str]]:
    """Ordered (method, literal-string) pairs from a statement list.

    Recurses into ``if`` blocks; skips ``for``/``while`` (dynamic content) so we
    only capture the static reference equations."""
    items: list[tuple[str, str]] = []
    for node in body:
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
            call = node.value
            f = call.func
            if (isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name)
                    and f.value.id == "st" and f.attr in _TEXT_METHODS
                    and call.args and isinstance(call.args[0], ast.Constant)
                    and isinstance(call.args[0].value, str)):
                items.append((f.attr, call.args[0].value))
        elif isinstance(node, ast.If):
            items.extend(_extract_items(node.body))
    return items


def _parse_sections(src_path: Path) -> list[dict]:
    tree = ast.parse(src_path.read_text(encoding="utf-8"))
    sections: list[dict] = []
    for node in tree.body:
        if not isinstance(node, ast.With):
            continue
        item0 = node.items[0].context_expr
        if not (isinstance(item0, ast.Call) and isinstance(item0.func, ast.Attribute)
                and item0.func.attr == "expander"):
            continue
        if not (item0.args and isinstance(item0.args[0], ast.Constant)):
            continue
        title = re.sub(r"\*+", "", str(item0.args[0].value)).strip()
        sections.append({"title": title, "items": _extract_items(node.body)})
    return sections


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
        raise SystemExit(f"Streamlit source not found: {SRC}")
    print(f"Using Streamlit source: {SRC}")
    print(f"Writing output to: {OUT}")
    sections = _parse_sections(SRC)
    n_eq = 0
    out_sections = []
    for sec in sections:
        items_out = []
        for meth, text in sec["items"]:
            if meth == "latex":
                img = _render_latex(text)
                n_eq += 1
                items_out.append({"type": "latex", "latex": text, "img": img})
            elif meth in ("header", "subheader"):
                items_out.append({"type": "header", "level": 3 if meth == "header" else 4,
                                  "text": _convert_inline(text)})
            else:
                items_out.append({"type": "md",
                                  "text": _PREFIX.get(meth, "") + _convert_inline(text)})
        out_sections.append({"title": sec["title"], "items": items_out})
        print(f"  section '{sec['title']}': {len(items_out)} items")

    OUT.write_text(json.dumps({"sections": out_sections}, ensure_ascii=False), encoding="utf-8")
    rendered = sum(1 for s in out_sections for it in s["items"]
                   if it["type"] == "latex" and it.get("img"))
    print(f"\n{len(out_sections)} sections, {n_eq} equations ({rendered} rendered) -> {OUT}")


if __name__ == "__main__":
    main()
