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

# Equations whose backing functions were removed from utils/calculations
# (2026-08 unused-code cleanup).  Each entry names a header in the source;
# the header and everything under it (until the next same-or-higher-level
# header) is dropped from the generated reference.
EXCLUDED_HEADERS = {
    "Batchelor Length Scale",
    "Gas Holdup (Hughmark)",
    "Sauter Mean Bubble Diameter (Calderbank)",
    "Gas Flooding Speed",
    "Impeller Weber Number (Liquid-Liquid)",
    "Sauter Mean Drop Diameter (Hinze-Kolmogorov)",
    "Minimum Dispersion Speed (Skelland & Seksaria)",
    "Liquid-Liquid Mass-Transfer Coefficient",
    "Phase Separation Time Estimate",
    "Archimedes Number",
    "Cooling Rate",
    "Common Scale-Up Rules",
    "Turbulent Dispersion",          # tau_D mesomixing scale not implemented
}

# Whole sections with no backing implementation in mixing_lab_v2.
EXCLUDED_SECTIONS = {
    "Crystallization",
}

# Corrections applied to the raw source text (audited 2026-08 against the
# mixing_lab_v2 implementation).  Each (old, new) must match at least once.
OVERRIDES: list[tuple[str, str]] = [
    # GMB N_js exponent: dimensional consistency (and gmb_njs code) require 0.5
    (r"\rho_L}\right)^{0.45} X_v^{0.154}",
     r"\rho_L}\right)^{0.5} X_v^{0.154}"),
    # NTU jacket outlet: jacket loses the heat it gives the batch
    (r"T_{j,\text{out}} = T_{j,\text{in}} + \frac{Q_{\text{jacket}}}",
     r"T_{j,\text{out}} = T_{j,\text{in}} - \frac{Q_{\text{jacket}}}"),
    # Instantaneous rate: sign convention matches heat_transfer_core
    (r"\frac{dT}{dt} = \frac{Q_{\text{jacket}} - P_{\text{agitator}} - Q_{\text{rxn}}}",
     r"\frac{dT}{dt} = \frac{Q_{\text{jacket}} + P_{\text{agitator}} + Q_{\text{rxn}}}"),
    ("(positive = cooling)",
     "(= U A (T_jacket - T); positive when the jacket heats the batch)"),
    # Dished-head area factors (fixed 2026-08: were applied to pi/4 D^2 by mistake)
    ("| 2:1 Elliptical | 1.09 |", "| 2:1 Elliptical | 1.38 |"),
    ("| Torispherical / DIN | 1.06 |", "| Torispherical / DIN | 1.26 |"),
    ("| Conical (~60\u00b0) | 1.20 |", "| Conical | 1 / cos \u03b8 (1.41 at 45\u00b0) |"),
    (r"$1.09 \cdot \pi/4 \cdot D_T^2$", r"$1.084 \cdot D_T^2$"),
    (r"$1.06 \cdot \pi/4 \cdot D_T^2$", r"$0.99 \cdot D_T^2$"),
    (r"$1.20 \cdot \pi/4 \cdot D_T^2$", r"$\sqrt{2} \cdot \pi/4 \cdot D_T^2$"),
    (r"A_{\text{cyl}} = \pi \, D_T \, H",
     r"A_{\text{cyl}} = \pi \, D_T \, (H - h_{\text{dish}})"),
    # Reference corrections
    ("Seider, E.N. & Tate", "Sieder, E.N. & Tate"),
    ("**Reference:** Sieder, E.N. & Tate, G.E. (1936). *Ind. Eng. Chem.* 28(12):1429.",
     "**Reference:** Hausen, H. (1943). *VDI Z., Beiheft Verfahrenstechnik*, 4, 91\u201398."),
    # gamma = sqrt(eps/nu) is the standard dissipation identity, not from Kresta & Wood
    ("**Reference:** Kresta & Wood (1993), as above.",
     "**Reference:** standard turbulence dissipation relation \u03b5 = \u03bd \u03b3\u0307\u00b2 "
     "(e.g. Tennekes, H. & Lumley, J.L. (1972). *A First Course in Turbulence*, MIT Press, Ch. 3); "
     "\u03b5_max estimate from Kresta & Wood (1993), as above."),
    # Blend time: implemented as the circulation-model form, not the published Grenville form
    ("Grenville correlation for turbulent blending in a baffled stirred tank.",
     "Circulation-model blend time \u2014 \u2248 5.2 circulation times, t_c = V/(N_Q N D\u00b3) \u2014 for "
     "turbulent blending in a baffled stirred tank. The published Grenville correlation is "
     "N \u03b8\u2089\u2085 = 5.2 Po^(\u22121/3) (T/D)\u00b2; this circulation form approximates it "
     "(typically conservatively, predicting longer times)."),
    # Only the inertial-convective mesomixing scale is implemented
    ("The slower of the two governs feed-plume dispersion.",
     "Mixing Lab implements the inertial-convective (disintegration) scale below."),
    # ROM registry is populated in this app
    ("No reactor-specific correlations have been registered yet.",
     "Reactor-specific correlations are registered in `utils/rom_registry.py` (demo entries plus "
     "fitted correlations loaded from `data/fitted_correlations.json`) and become selectable on "
     "the Vessel Assessment / Vessel Comparison pages."),
    # --- Link corrections (audited 2026-08 via Crossref / OpenLibrary) ---
    # Lamont & Scott (1970) AIChE J 16, 513: DOI pointed to an unrelated fuel-cell paper
    ("https://doi.org/10.1002/aic.690160410", "https://doi.org/10.1002/aic.690160403"),
    # Grenville, Mak & Brown (2015) ChERD 100, 282: DOI pointed to a catalysis paper
    ("https://doi.org/10.1016/j.cherd.2015.07.009", "https://doi.org/10.1016/j.cherd.2015.05.026"),
    # Stoessel 2nd ed (2020): old DOI 404s
    ("https://doi.org/10.1002/9783527697854", "https://doi.org/10.1002/9783527696918"),
    # Dead OpenLibrary ISBN-10 records -> working ISBN-13 records
    ("https://openlibrary.org/isbn/012176950X", "https://openlibrary.org/isbn/9780121769505"),
    ("https://openlibrary.org/isbn/047125424X", "https://openlibrary.org/isbn/9780471254249"),
    # Wikipedia articles that do not exist -> plain-text citations
    ("[*J. Boston Soc. Civil Eng.*](https://en.wikipedia.org/wiki/Camp%E2%80%93Stein_equation)",
     "*J. Boston Soc. Civil Eng.*"),
    ("[*Chem. Eng. Prog.*](https://en.wikipedia.org/wiki/Ranz%E2%80%93Marshall_correlation)",
     "*Chem. Eng. Prog.*"),
    # Percent-encode parentheses in DOI URLs (unencoded parens break markdown links)
    ("https://doi.org/10.1016/0009-2509(93)80346-R",
     "https://doi.org/10.1016/0009-2509%2893%2980346-R"),
    ("https://doi.org/10.1016/S0009-2509(97)00072-9",
     "https://doi.org/10.1016/S0009-2509%2897%2900072-9"),
    ("https://doi.org/10.1016/0009-2509(58)85031-9",
     "https://doi.org/10.1016/0009-2509%2858%2985031-9"),
]


def filter_excluded(items: list[dict]) -> list[dict]:
    """Drop excluded headers and their sub-content (level-aware)."""
    out: list[dict] = []
    skip_level: int | None = None
    for it in items:
        if it["type"] == "header":
            lvl = int(it.get("level", 3))
            if skip_level is not None and lvl > skip_level:
                continue          # sub-header of an excluded block
            skip_level = None
            if it.get("text", "").strip() in EXCLUDED_HEADERS:
                skip_level = lvl
                continue
        elif skip_level is not None:
            continue
        out.append(it)
    return out


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


def _optimize_png(data: bytes) -> bytes:
    """Palette-quantize an RGBA equation PNG (~65% smaller, keeps alpha).

    Falls back to the original bytes if Pillow is unavailable or fails.
    """
    try:
        from PIL import Image

        img = Image.open(io.BytesIO(data)).quantize(colors=64, method=Image.FASTOCTREE)
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
        raise SystemExit(f"Streamlit source not found: {SRC}")
    print(f"Using Streamlit source: {SRC}")
    print(f"Writing output to: {OUT}")
    sections = _parse_sections(SRC)
    n_eq = 0
    out_sections = []
    override_hits = {old: 0 for old, _ in OVERRIDES}
    for sec in sections:
        if sec["title"] in EXCLUDED_SECTIONS:
            print(f"  section '{sec['title']}': EXCLUDED (no backing implementation)")
            continue
        items_out = []
        for meth, text in sec["items"]:
            for old, new in OVERRIDES:
                if old in text:
                    text = text.replace(old, new)
                    override_hits[old] += 1
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
        items_out = filter_excluded(items_out)
        out_sections.append({"title": sec["title"], "items": items_out})
        print(f"  section '{sec['title']}': {len(items_out)} items")

    OUT.write_text(json.dumps({"sections": out_sections}, ensure_ascii=False), encoding="utf-8")
    unmatched = [old for old, n in override_hits.items() if n == 0]
    if unmatched:
        print("\nWARNING - overrides that matched nothing (source may have changed):")
        for old in unmatched:
            print(f"  {old[:80]!r}")
    rendered = sum(1 for s in out_sections for it in s["items"]
                   if it["type"] == "latex" and it.get("img"))
    print(f"\n{len(out_sections)} sections, {n_eq} equations ({rendered} rendered) -> {OUT}")


if __name__ == "__main__":
    main()
