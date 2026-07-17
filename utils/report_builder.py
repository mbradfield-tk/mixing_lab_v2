"""
Shared PDF report builder for Mixing Lab pages.
=================================================
Provides the MixingReport FPDF subclass and helper functions used by
Pages 5, 7 and 10 to generate downloadable PDF reports.
"""

import pathlib
import io
import datetime
import re
import warnings
import numpy as np

from fpdf import FPDF

_ROOT = pathlib.Path(__file__).resolve().parent.parent
_LOGO = _ROOT / "images" / "general" / "logo.png"

# DejaVu Sans – Unicode-capable TTF bundled with matplotlib
def _find_dejavu() -> pathlib.Path | None:
    """Locate DejaVuSans.ttf from the matplotlib package."""
    try:
        import matplotlib
        d = pathlib.Path(matplotlib.__file__).parent / "mpl-data" / "fonts" / "ttf"
        if (d / "DejaVuSans.ttf").exists():
            return d
    except ImportError:
        pass
    return None

_DEJAVU_DIR = _find_dejavu()

# Unicode → ASCII substitution map (used when falling back to Helvetica)
_UNICODE_MAP = str.maketrans({
    "\u2014": "--",   # em dash
    "\u2013": "-",    # en dash
    "\u00b7": ".",    # middle dot
    "\u00b0": "deg",  # degree
    "\u00b2": "2",    # superscript 2
    "\u00b3": "3",    # superscript 3
    "\u00b5": "u",    # micro sign
    "\u03b7": "eta",  # eta
    "\u03b5": "eps",  # epsilon
    "\u03bb": "lambda",
    "\u03c1": "rho",
    "\u03c6": "phi",
    "\u0394": "D",    # Delta
})

def _safe_text(text: str, is_unicode_font: bool) -> str:
    """If using a non-Unicode font, replace special characters with ASCII."""
    if is_unicode_font:
        return text
    return text.translate(_UNICODE_MAP).encode("latin-1", errors="replace").decode("latin-1")


def _fmt_sig(value, sig: int = 4) -> str:
    """Format a number to ``sig`` significant figures without scientific
    notation, stripping trailing zeros.

    Fixed-decimal formats (e.g. ``:.2f``) silently drop precision for small
    magnitudes — 0.014 renders as "0.01". This keeps the significant digits
    regardless of magnitude: 0.014 -> "0.014", 1500 -> "1500", 250.5 -> "250.5".
    """
    import math
    try:
        v = float(value)
    except (TypeError, ValueError):
        return str(value)
    if not math.isfinite(v):
        return str(value)
    if v == 0:
        return "0"
    digits = max(sig - 1 - int(math.floor(math.log10(abs(v)))), 0)
    s = f"{v:.{digits}f}"
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s


DISPLAY_NAMES = {
    "Da_macro": "Macromixing (Da_macro)",
    "Da_micro": "Micromixing (Da_micro)",
    "Da_GL": "Gas-Liquid Mass Transfer (Da_GL)",
    "Q_gen/Q_cool (%)": "Heat Capacity (Q_gen/Q_cool %)",
}

MODE_COLORS = {"Literature": "#3366CC", "ROM": "#33AA66", "Experimental": "#FF8800"}


def da_text(Da: float) -> str:
    if Da < 0.01:
        return "Not sensitive"
    if Da < 0.1:
        return "Likely not sensitive"
    if Da < 1:
        return "Potentially sensitive"
    if Da < 10:
        return "Likely sensitive"
    return "Highly sensitive"


def da_symbol(Da: float) -> str:
    if Da < 0.1:
        return "GREEN"
    if Da < 1:
        return "AMBER"
    return "RED"


def fig_to_png_bytes(fig) -> bytes:
    return fig.to_image(format="png", scale=2)


# ── MixingReport FPDF class ─────────────────────────────────────────────
class MixingReport(FPDF):
    """Custom FPDF subclass with header/footer branding."""

    _FONT = "DejaVu"
    _unicode_font = True

    def __init__(self, report_title: str, logo_path: str | None = None, **kw):
        super().__init__(**kw)
        if logo_path is None:
            logo_path = str(_LOGO) if _LOGO.exists() else None
        self._logo_path = logo_path
        self._report_title = report_title
        self.set_auto_page_break(auto=True, margin=25)
        if _DEJAVU_DIR:
            try:
                self.add_font("DejaVu", "",  str(_DEJAVU_DIR / "DejaVuSans.ttf"))
                self.add_font("DejaVu", "B", str(_DEJAVU_DIR / "DejaVuSans-Bold.ttf"))
                self.add_font("DejaVu", "I", str(_DEJAVU_DIR / "DejaVuSans-Oblique.ttf"))
                self.add_font("DejaVu", "BI", str(_DEJAVU_DIR / "DejaVuSans-BoldOblique.ttf"))
            except Exception:
                self._FONT = "Helvetica"
                self._unicode_font = False
        else:
            self._FONT = "Helvetica"
            self._unicode_font = False

    def header(self):
        if self._logo_path and pathlib.Path(self._logo_path).exists():
            self.image(self._logo_path, x=10, y=8, h=12)
        self.set_font(self._FONT, "B", 10)
        self.set_text_color(100, 100, 100)
        self.cell(0, 10, self._s(self._report_title), align="R")
        self.ln(14)
        self.set_draw_color(200, 200, 200)
        self.line(10, self.get_y(), self.w - 10, self.get_y())
        self.ln(4)

    def footer(self):
        self.set_y(-20)
        self.set_draw_color(200, 200, 200)
        self.line(10, self.get_y(), self.w - 10, self.get_y())
        self.set_y(-15)
        self.set_font(self._FONT, "I", 8)
        self.set_text_color(140, 140, 140)
        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        self.cell(0, 10, f"Generated {ts}", align="L")
        self.cell(0, 10, f"Page {self.page_no()}/{{nb}}", align="R")

    # ── convenience methods ──────────────────────────────────────────────
    def _s(self, text: str) -> str:
        return _safe_text(text, self._unicode_font)

    def section_title(self, text: str):
        self.set_font(self._FONT, "B", 13)
        self.set_text_color(30, 30, 80)
        self.cell(0, 9, self._s(text))
        self.ln(10)

    def sub_title(self, text: str):
        self.set_font(self._FONT, "B", 11)
        self.set_text_color(50, 50, 50)
        self.cell(0, 8, self._s(text))
        self.ln(8)

    def kv(self, key: str, value: str, bold_val: bool = False):
        self.set_font(self._FONT, "", 10)
        self.set_text_color(60, 60, 60)
        self.cell(70, 6, self._s(key))
        style = "B" if bold_val else ""
        self.set_font(self._FONT, style, 10)
        self.set_text_color(20, 20, 20)
        self.cell(0, 6, self._s(value))
        self.ln(6)

    def body_text(self, text: str):
        """Multi-line body text block."""
        self.set_font(self._FONT, "", 10)
        self.set_text_color(40, 40, 40)
        self.multi_cell(0, 5, self._s(text))
        self.ln(3)

    def metric_table(self, rows: list[tuple[str, str]], cols: int = 2):
        col_w = (self.w - 20) / cols / 2
        self.set_font(self._FONT, "", 9)
        for i, (k, v) in enumerate(rows):
            if i > 0 and i % cols == 0:
                self.ln(6)
            self.set_text_color(80, 80, 80)
            self.cell(col_w, 6, self._s(k))
            self.set_text_color(20, 20, 20)
            self.set_font(self._FONT, "B", 9)
            self.cell(col_w, 6, self._s(v))
            self.set_font(self._FONT, "", 9)
        self.ln(8)

    def assessment_box(self, text: str, colour: str = "GREEN"):
        if colour == "GREEN":
            r, g, b = 34, 139, 34
            br, bg, bb = 220, 245, 220
        elif colour == "AMBER":
            r, g, b = 180, 130, 0
            br, bg, bb = 255, 245, 210
        else:
            r, g, b = 200, 30, 30
            br, bg, bb = 255, 220, 220
        self.set_fill_color(br, bg, bb)
        self.set_text_color(r, g, b)
        self.set_font(self._FONT, "B", 10)
        # Use multi_cell so long text wraps onto multiple lines instead of
        # being clipped; a small left indent keeps the original look.
        indent = 2.0
        x0 = self.get_x()
        self.set_x(x0 + indent)
        self.multi_cell(self.w - self.l_margin - self.r_margin - indent, 6,
                        self._s(text), fill=True)
        self.set_x(x0)
        self.ln(1)
        self.set_text_color(0, 0, 0)

    def data_table(self, headers: list[str], rows: list[list[str]],
                   col_widths: list[float] | None = None,
                   wrap: bool = True):
        """Render a bordered table with a header row and data rows.

        Cell text that is wider than its column is always wrapped onto
        multiple lines and the row grows in height to fit, so no content is
        ever clipped by the column border. The *wrap* argument is retained
        for backward compatibility but wrapping is now always applied.
        """
        usable = self.w - 20
        n = len(headers)
        if col_widths is None:
            col_widths = [usable / n] * n

        # ── Wrapped rendering (always applied) ─────────────────────────
        line_h = 4.5
        pad = 1.0

        def _cell_lines(text: str, width: float) -> list[str]:
            """Split *text* into lines that fit within *width* mm."""
            text = self._s(str(text))
            avail = max(1.0, width - 2 * pad)
            lines: list[str] = []
            for para in text.split("\n"):
                if para == "":
                    lines.append("")
                    continue
                words = para.split(" ")
                cur = ""
                for word in words:
                    # Hard-break words that are too long on their own.
                    while self.get_string_width(word) > avail:
                        cut = len(word)
                        while cut > 1 and self.get_string_width(word[:cut]) > avail:
                            cut -= 1
                        piece = word[:cut]
                        if cur:
                            lines.append(cur)
                            cur = ""
                        lines.append(piece)
                        word = word[cut:]
                    trial = word if not cur else f"{cur} {word}"
                    if self.get_string_width(trial) <= avail:
                        cur = trial
                    else:
                        if cur:
                            lines.append(cur)
                        cur = word
                lines.append(cur)
            return lines or [""]

        def _render_row(cells, fill_rgb, bold):
            self.set_font(self._FONT, "B" if bold else "", 8)
            self.set_fill_color(*fill_rgb)
            wrapped = [_cell_lines(c, col_widths[i]) for i, c in enumerate(cells)]
            max_lines = max(len(w) for w in wrapped)
            cell_h = max_lines * line_h + 2 * pad
            # Page break if the row would overflow the page.
            if self.get_y() + cell_h > self.h - self.b_margin:
                self.add_page()
            x0 = self.get_x()
            y0 = self.get_y()
            x = x0
            for i, w in enumerate(wrapped):
                cw = col_widths[i]
                self.rect(x, y0, cw, cell_h, style="DF")
                ty = y0 + pad
                for ln in w:
                    self.set_xy(x + pad, ty)
                    self.cell(cw - 2 * pad, line_h, ln, border=0)
                    ty += line_h
                x += cw
            self.set_xy(x0, y0 + cell_h)

        # Header
        self.set_text_color(30, 30, 80)
        _render_row(headers, (230, 230, 240), bold=True)
        # Data rows
        self.set_text_color(40, 40, 40)
        _alt = False
        for row in rows:
            fill = (245, 245, 250) if _alt else (255, 255, 255)
            _render_row([str(v) for v in row], fill, bold=False)
            _alt = not _alt
        self.ln(4)

    def findings_table(self, findings: list[tuple[str, str, str]]):
        """Render a list of (mechanism, status_icon, detail) rows."""
        self.set_font(self._FONT, "B", 9)
        self.set_fill_color(230, 230, 240)
        self.set_text_color(30, 30, 80)
        col_w1, col_w2, col_w3 = 45, 40, self.w - 20 - 85
        self.cell(col_w1, 7, self._s("Mechanism"), border=1, fill=True)
        self.cell(col_w2, 7, self._s("Status"), border=1, fill=True)
        self.cell(col_w3, 7, self._s("Detail"), border=1, fill=True)
        self.ln(7)
        self.set_font(self._FONT, "", 8)
        self.set_text_color(40, 40, 40)
        for mechanism, status, detail in findings:
            # Determine row height based on detail text length
            _detail_clean = self._s(detail)
            _status_clean = self._s(status)
            x_before = self.get_x()
            y_before = self.get_y()
            # Estimate lines needed
            _lines = max(1, len(_detail_clean) // int(col_w3 / 1.8) + 1)
            row_h = max(6, _lines * 5)
            self.cell(col_w1, row_h, self._s(mechanism), border=1)
            self.cell(col_w2, row_h, _status_clean, border=1)
            # Use multi_cell for detail (wraps text)
            x_mc = self.get_x()
            y_mc = self.get_y()
            self.multi_cell(col_w3, 5, _detail_clean, border=1)
            # Ensure we move to correct y
            _y_after = self.get_y()
            if _y_after < y_mc + row_h:
                self.set_y(y_mc + row_h)
        self.ln(4)


def new_report(title: str) -> MixingReport:
    """Create a new MixingReport with standard settings."""
    pdf = MixingReport(title, orientation="P", unit="mm", format="A4")
    pdf.alias_nb_pages()
    return pdf


def report_bytes(pdf: MixingReport) -> bytes:
    """Finalize and return the PDF as bytes."""
    return bytes(pdf.output())


def report_filename(prefix: str, label: str = "") -> str:
    """Generate a timestamped filename."""
    clean = label.replace(" ", "_").replace("/", "_") if label else ""
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M")
    parts = [prefix]
    if clean:
        parts.append(clean)
    parts.append(ts)
    return "_".join(parts) + ".pdf"


def build_envelope_fig(param: str, envelope: dict, V_L: float = 0.0):
    """Build a single operating-envelope Plotly figure for *param*."""
    import plotly.graph_objects as go

    if envelope is None:
        return None
    curve_data = envelope["curve_data"]
    pct_arr = np.array(envelope["pct_arr"])
    active_modes = envelope["active_modes"]
    priority_mode_label = envelope["priority_mode_label"]
    current_pct = envelope["current_pct"]
    env_V_max = envelope["env_V_max"]
    env_V_min = envelope["env_V_min"]
    rpm_max = envelope["rpm_max"]

    first_mode = list(curve_data.keys())[0]
    if param not in curve_data[first_mode]["maxV"]:
        return None

    fig = go.Figure()
    for mode_label in active_modes:
        if mode_label not in curve_data:
            continue
        color = MODE_COLORS.get(mode_label, "#999999")
        mc = curve_data[mode_label]
        y_max = np.array(mc["maxV"][param])
        y_min = np.array(mc["minV"][param])
        poly_x = np.concatenate([pct_arr, pct_arr[::-1], [pct_arr[0]]])
        poly_y = np.concatenate([y_max, y_min[::-1], [y_max[0]]])
        fig.add_trace(go.Scatter(
            x=poly_x, y=poly_y, fill="toself", fillcolor=color, opacity=0.15,
            line=dict(color=color, width=1), mode="lines",
            name=f"{mode_label} envelope", legendgroup=mode_label,
            hoverinfo="skip",
        ))
        fig.add_trace(go.Scatter(
            x=pct_arr, y=y_max, mode="lines",
            line=dict(color=color, width=2),
            name=f"{mode_label} max V ({env_V_max:.1f} L)",
            legendgroup=mode_label,
        ))
        fig.add_trace(go.Scatter(
            x=pct_arr, y=y_min, mode="lines",
            line=dict(color=color, width=2, dash="dot"),
            name=f"{mode_label} min V ({env_V_min:.1f} L)",
            legendgroup=mode_label,
        ))

    if priority_mode_label in curve_data:
        pc = curve_data[priority_mode_label]
        y_maxp = np.array(pc["maxV"][param])
        y_minp = np.array(pc["minV"][param])
        if abs(env_V_max - env_V_min) > 1e-6:
            frac = max(0.0, min(1.0, (V_L - env_V_min) / (env_V_max - env_V_min)))
            y_interp = (np.interp(current_pct, pct_arr, y_minp) * (1 - frac)
                        + np.interp(current_pct, pct_arr, y_maxp) * frac)
        else:
            y_interp = np.interp(current_pct, pct_arr, y_maxp)
        fig.add_trace(go.Scatter(
            x=[current_pct], y=[y_interp],
            mode="markers", marker=dict(size=12, color="red", symbol="star",
                                         line=dict(width=1, color="white")),
            name="Current",
        ))

    if param in ("Da_macro", "Da_micro", "Da_GL"):
        for da_val, da_color, label in [
            (0.1, "orange", "Da=0.1"), (1.0, "red", "Da=1"),
        ]:
            fig.add_shape(type="line", x0=0, x1=1, y0=da_val, y1=da_val,
                          xref="paper", yref="y",
                          line=dict(color=da_color, width=1.5, dash="dash"))
        fig.update_yaxes(type="log")
    if param == "Q_gen/Q_cool (%)":
        fig.add_shape(type="line", x0=0, x1=1, y0=100, y1=100,
                      xref="paper", yref="y",
                      line=dict(color="red", width=1.5, dash="dash"))

    display = DISPLAY_NAMES.get(param, param)
    fig.update_layout(
        title=display, xaxis_title=f"Stir speed (% of max RPM = {rpm_max:.0f})",
        yaxis_title=display,
        xaxis=dict(range=[0, 105], dtick=10),
        height=400, width=700, margin=dict(t=50, b=50),
    )
    return fig


def add_envelope_charts(pdf: MixingReport, envelope: dict, V_L: float,
                        report_params: list[str]):
    """Add operating envelope chart pages to the PDF."""
    pdf.add_page()
    pdf.section_title("Operating Envelopes")
    pdf.set_font(pdf._FONT, "", 9)
    pdf.set_text_color(80, 80, 80)
    pdf.cell(0, 6, pdf._s(
             f"RPM range: {envelope['rpm_min']:.0f} - {envelope['rpm_max']:.0f}  |  "
             f"Volume range: {envelope['env_V_min']:.1f} - {envelope['env_V_max']:.1f} L"))
    pdf.ln(10)

    _chart_count_on_page = 0
    for param in report_params:
        fig = build_envelope_fig(param, envelope, V_L)
        if fig is None:
            continue
        try:
            png = fig_to_png_bytes(fig)
        except Exception as exc:
            warnings.warn(f"Skipping '{param}' chart in report: {exc}")
            continue
        if not png or png[:4] != b"\x89PNG":
            warnings.warn(f"Skipping '{param}' chart in report: invalid PNG output.")
            continue
        if _chart_count_on_page >= 2:
            pdf.add_page()
            _chart_count_on_page = 0
        pdf.image(io.BytesIO(png), x=15, w=180)
        pdf.ln(5)
        _chart_count_on_page += 1


# ── Page-specific report builders ────────────────────────────────────────

def build_mixing_assessment_pdf(snap: dict) -> bytes:
    """Build PDF report for Page 5 – Vessel Assessment."""
    reactor_name = snap["reactor"]
    reaction_name = snap["reaction"]
    fluid_name = snap["fluid"]
    fluid_T_C = snap["fluid_T_C"]
    N_rpm = snap["N_rpm"]
    V_L = snap["V_L"]
    hydro = snap["hydro"]
    da = snap["da"]
    t_rxn = snap["t_rxn"]
    heat_results = snap.get("heat_results", {})
    particle_results = snap.get("particle_results", {})
    particle_meta = snap.get("particle_meta", {})
    batchelor_um = snap.get("batchelor_um", 0.0)
    envelope = snap.get("envelope")

    title = f"Vessel Assessment \u2014 {reactor_name}"
    pdf = new_report(title)

    # ── Page 1: Title & System Info ──────────────────────────────────────
    pdf.add_page()
    pdf.set_font(pdf._FONT, "B", 20)
    pdf.set_text_color(30, 30, 80)
    pdf.cell(0, 14, pdf._s("Vessel Assessment Report"), align="C")
    pdf.ln(18)

    pdf.section_title("System Configuration")
    pdf.kv("Reactor", reactor_name, bold_val=True)
    pdf.kv("Reaction", reaction_name, bold_val=True)
    pdf.kv("Fluid", f"{fluid_name}  ({fluid_T_C:.1f} deg C)", bold_val=True)
    pdf.kv("Stir speed", f"{N_rpm:.0f} RPM")
    pdf.kv("Liquid volume", f"{_fmt_sig(V_L)} L")
    pdf.kv("Reaction time (t_rxn)", f"{t_rxn:.4g} s")
    pdf.ln(4)

    # ── Hydrodynamic metrics ─────────────────────────────────────────────
    pdf.section_title("Hydrodynamic & Mixing Metrics")
    _hydro_headers = ["Parameter", "Value"]
    _hydro_rows = [
        ["Re", f"{hydro['Re']:.0f}"],
        ["P/V (W/L)", f"{hydro['P/V (W/L)']:.3g}"],
        ["Blend time 95% (s)", f"{hydro['Blend time 95% (s)']:.2f}"],
        ["Micromix t_E (s)", f"{hydro['Micromix time t_E (s)']:.4g}"],
        ["Tip speed (m/s)", f"{hydro['Tip speed (m/s)']:.2f}"],
        ["Kolmogorov eta (um)", f"{hydro['Kolmogorov η (µm)']:.1f}"],
        ["Batchelor lambda_B (um)", f"{batchelor_um:.2f}"],
        ["Circulation time (s)", f"{hydro['Circulation time (s)']:.2f}"],
        ["Avg shear rate (1/s)", f"{hydro['Avg shear rate (1/s)']:.1f}"],
        ["Max shear rate (1/s)", f"{hydro['Max shear rate (1/s)']:.0f}"],
        ["Avg shear stress (Pa)", f"{hydro['Avg shear stress (Pa)']:.3g}"],
        ["EDCF (W/kg/s)", f"{hydro['EDCF (W/kg/s)']:.3g}"],
        ["Torque (N.m)", f"{hydro['Torque (N·m)']:.3g}"],
        ["Froude number", f"{hydro['Froude number']:.4g}"],
    ]
    pdf.data_table(_hydro_headers, _hydro_rows, col_widths=[90, 80])
    pdf.ln(2)

    pdf.sub_title("Mass Transfer")
    _mt_rows = []
    if hydro.get("kLa (1/s)", 0) > 0:
        _mt_rows.append(["kLa sparged (1/s)", f"{hydro['kLa (1/s)']:.4g}"])
    _mt_rows.append(["kLa surface (1/s)", f"{hydro['kLa_surface (1/s)']:.4g}"])
    pdf.data_table(["Parameter", "Value"], _mt_rows, col_widths=[90, 80])

    if heat_results:
        pdf.sub_title("Heat Transfer")
        _ht_rows = [
            ["Q_gen (W)", f"{heat_results['Q_gen (W)']:.1f}"],
            ["Q_cool (W)", f"{heat_results['Q_cool (W)']:.1f}"],
            ["U (W/m2.K)", f"{heat_results['U (W/m²·K)']:.0f}"],
            ["A_ht (m2)", f"{heat_results['A_ht (m²)']:.3f}"],
            ["Q_gen/Q_cool (%)", f"{heat_results['Q_gen/Q_cool (%)']:.1f}%"],
        ]
        pdf.data_table(["Parameter", "Value"], _ht_rows, col_widths=[90, 80])

    if particle_results:
        pdf.sub_title("Solid Particles")
        _sp_rows = [
            ["Particle", particle_meta.get("Particle", "")],
            ["d50 (um)", f"{particle_results['d50 (µm)']:.1f}"],
            ["rho_p (kg/m3)", f"{particle_results['ρ_p (kg/m³)']:.0f}"],
            ["N_js design (RPM)", f"{particle_results['N_js (RPM)']:.1f}"],
            ["v_t (m/s)", f"{particle_results['v_t (m/s)']:.3e}"],
            ["k_SL (m/s)", f"{particle_results['k_SL (m/s)']:.3e}"],
        ]
        pdf.data_table(["Parameter", "Value"], _sp_rows, col_widths=[90, 80])
        susp = particle_meta.get("Suspension", "")
        _susp_col = "GREEN" if "Well" in susp or "Just" in susp else ("AMBER" if "Partial" in susp else "RED")
        pdf.assessment_box(susp, _susp_col)

    # ── Page 2: Sensitivity Assessment ───────────────────────────────────
    pdf.add_page()
    pdf.section_title("Mixing Sensitivity Assessment")

    da_macro = da["Da_macro"]
    da_micro = da["Da_micro"]
    da_gl = da["Da_GL"]

    pdf.kv("Da_macro", f"{da_macro:.3g}")
    pdf.assessment_box(
        f"Macromixing: {da_text(da_macro)} (Da = {da_macro:.3g})",
        da_symbol(da_macro),
    )
    pdf.kv("Da_micro", f"{da_micro:.3g}")
    pdf.assessment_box(
        f"Micromixing: {da_text(da_micro)} (Da = {da_micro:.3g})",
        da_symbol(da_micro),
    )
    if da_gl > 0:
        pdf.kv("Da_GL", f"{da_gl:.3g}")
        pdf.assessment_box(
            f"Gas-liquid: {da_text(da_gl)} (Da = {da_gl:.3g})",
            da_symbol(da_gl),
        )
    if heat_results:
        ratio = heat_results["Q_gen/Q_cool (%)"]
        heat_col = "GREEN" if ratio < 100 else "RED"
        pdf.assessment_box(
            f"Heat balance: Q_gen/Q_cool = {ratio:.1f}%",
            heat_col,
        )

    overall = da.get("Assessment", "")
    if overall:
        pdf.ln(4)
        pdf.sub_title("Overall Assessment")
        if "not" in overall.lower():
            _oc = "GREEN"
        elif "potentially" in overall.lower():
            _oc = "AMBER"
        else:
            _oc = "RED"
        pdf.assessment_box(overall, _oc)

    # ── Recommendations ──────────────────────────────────────────────────
    pdf.ln(4)
    pdf.section_title("Recommendations")
    recs = []
    if da_macro >= 1:
        recs.append("Macromixing is limiting -- consider increasing agitation or reducing reaction volume.")
    elif da_macro >= 0.1:
        recs.append("Macromixing is potentially sensitive -- verify at target scale with Da_macro monitoring.")
    if da_micro >= 1:
        recs.append("Micromixing is limiting -- feed near the impeller, increase tip speed, or use higher shear impeller.")
    elif da_micro >= 0.1:
        recs.append("Micromixing is potentially sensitive -- consider feed location and addition rate at scale.")
    if da_gl >= 1:
        recs.append("Gas-liquid mass transfer is limiting -- increase kLa via higher gas flow or agitation.")
    if heat_results and heat_results.get("Q_gen/Q_cool (%)", 0) >= 100:
        recs.append("Cooling capacity is insufficient -- reduce feed rate, increase jacket area, or lower coolant temperature.")
    if not recs:
        recs.append("No mixing limitations identified at the current operating point. Standard scale-up practices apply.")
    for rec in recs:
        pdf.body_text(f"- {rec}")

    # ── Envelope Charts ──────────────────────────────────────────────────
    if envelope is not None:
        report_params = ["Da_micro", "Da_macro", "Da_GL", "Blend time 95% (s)", "P/V (W/L)"]
        if heat_results:
            report_params.append("Q_gen/Q_cool (%)")
        add_envelope_charts(pdf, envelope, V_L, report_params)

    return report_bytes(pdf)


def build_comparison_envelope_fig(param: str, curve_data: dict,
                                  env_df, reactor_info: dict) -> "go.Figure | None":
    """Build a multi-reactor operating-envelope Plotly figure for *param*."""
    import plotly.graph_objects as go

    _PALETTE = [
        "#1f77b4", "#ff7f0e", "#2ca02c", "#d62728",
        "#9467bd", "#8c564b", "#e377c2", "#7f7f7f",
        "#bcbd22", "#17becf",
    ]

    reactor_names = list(curve_data.keys())
    if not reactor_names:
        return None

    # Check param exists in curve data
    first = reactor_names[0]
    if param not in curve_data[first].get("maxV", {}):
        return None

    fig = go.Figure()

    for i, rname in enumerate(reactor_names):
        color = _PALETTE[i % len(_PALETTE)]
        curves = curve_data[rname]
        pct_arr = np.array(curves["pct_arr"])
        y_maxV = np.array(curves["maxV"][param])
        y_minV = np.array(curves["minV"][param])

        # Filled polygon
        poly_x = np.concatenate([pct_arr, pct_arr[::-1], [pct_arr[0]]])
        poly_y = np.concatenate([y_maxV, y_minV[::-1], [y_maxV[0]]])
        fig.add_trace(go.Scatter(
            x=poly_x, y=poly_y,
            fill="toself", fillcolor=color, opacity=0.20,
            line=dict(color=color, width=1), mode="lines",
            name=rname, showlegend=True, legendgroup=rname,
            hoverinfo="skip",
        ))
        # Max-volume boundary (solid)
        fig.add_trace(go.Scatter(
            x=pct_arr, y=y_maxV,
            mode="lines", line=dict(color=color, width=2),
            showlegend=False, legendgroup=rname,
        ))
        # Min-volume boundary (dotted)
        fig.add_trace(go.Scatter(
            x=pct_arr, y=y_minV,
            mode="lines", line=dict(color=color, width=2, dash="dot"),
            showlegend=False, legendgroup=rname,
        ))

    # Reference lines
    if param in ("Da_macro", "Da_micro", "Da_GL", "Da_SL"):
        import math
        for da_val, da_color, label in [
            (0.1, "orange", "Da=0.1"), (1.0, "red", "Da=1"),
        ]:
            fig.add_shape(
                type="line", x0=0, x1=1, y0=da_val, y1=da_val,
                xref="paper", yref="y",
                line=dict(color=da_color, width=1.5, dash="dash"),
            )
        fig.update_yaxes(type="log")

    if param == "Q_gen/Q_cool (%)":
        fig.add_shape(
            type="line", x0=0, x1=1, y0=100.0, y1=100.0,
            xref="paper", yref="y",
            line=dict(color="red", width=1.5, dash="dash"),
        )

    display = DISPLAY_NAMES.get(param, param)
    fig.update_layout(
        title=display,
        xaxis_title="Stir speed (% of vessel max RPM)",
        yaxis_title=display,
        xaxis=dict(range=[0, 105], dtick=10),
        height=400, width=700,
        margin=dict(t=50, b=50),
        legend=dict(title="Reactor"),
    )
    return fig


def add_comparison_charts(pdf: MixingReport, curve_data: dict,
                          env_df, reactor_info: dict,
                          report_params: list[str]):
    """Add multi-reactor operating envelope chart pages to the PDF."""
    pdf.add_page()
    pdf.section_title("Operating Envelope Charts")
    pdf.body_text(
        "Each reactor's operational region is shown as a filled polygon. "
        "Solid lines = max fill volume; dotted lines = min fill volume."
    )

    _chart_count_on_page = 0
    for param in report_params:
        fig = build_comparison_envelope_fig(param, curve_data, env_df, reactor_info)
        if fig is None:
            continue
        try:
            png = fig_to_png_bytes(fig)
        except Exception as exc:
            warnings.warn(f"Skipping '{param}' comparison chart in report: {exc}")
            continue
        if not png or png[:4] != b"\x89PNG":
            warnings.warn(f"Skipping '{param}' comparison chart in report: invalid PNG output.")
            continue
        if _chart_count_on_page >= 2:
            pdf.add_page()
            _chart_count_on_page = 0
        pdf.image(io.BytesIO(png), x=15, w=180)
        pdf.ln(5)
        _chart_count_on_page += 1


def build_reactor_comparison_pdf(snap: dict) -> bytes:
    """Build PDF report for Page 7 – Vessel Comparison."""
    selected_names = snap["selected_names"]
    fluid_name = snap["fluid"]
    fluid_T_C = snap["fluid_T_C"]
    rxn_name = snap.get("reaction", "N/A")
    t_rxn = snap.get("t_rxn", 0.0)
    env_df = snap.get("env_df")  # DataFrame with all corner data
    agg_df = snap.get("agg_df")  # Aggregated summary
    reactor_info = snap.get("reactor_info", {})
    include_heat = snap.get("include_heat", False)
    include_particles = snap.get("include_particles", False)

    title = f"Vessel Comparison \u2014 {', '.join(selected_names[:3])}"
    if len(selected_names) > 3:
        title += f" + {len(selected_names) - 3} more"
    pdf = new_report(title)

    # ── Page 1: Title & System Info ──────────────────────────────────────
    pdf.add_page()
    pdf.set_font(pdf._FONT, "B", 20)
    pdf.set_text_color(30, 30, 80)
    pdf.cell(0, 14, pdf._s("Vessel Comparison Report"), align="C")
    pdf.ln(18)

    pdf.section_title("System Configuration")
    pdf.kv("Reactors compared", ", ".join(selected_names), bold_val=True)
    pdf.kv("Fluid", f"{fluid_name}  ({fluid_T_C:.1f} deg C)", bold_val=True)
    pdf.kv("Reaction", rxn_name, bold_val=True)
    pdf.kv("Reaction time (t_rxn)", f"{t_rxn:.4g} s")
    if include_heat:
        pdf.kv("Heat balance", "Included")
    if include_particles:
        pdf.kv("Solid particles", "Included")
    pdf.ln(4)

    # ── Per-reactor summary ──────────────────────────────────────────────
    pdf.section_title("Operating Envelope Summary")
    if agg_df is not None and not agg_df.empty:
        _key_params = ["P/V (W/L)", "Blend time 95% (s)", "Tip speed (m/s)",
                       "Da_macro", "Da_micro", "Re"]
        for _, a in agg_df.iterrows():
            rname = a["Reactor"]
            pdf.sub_title(rname)
            vol_min = a.get("Volume (L)_min", 0)
            vol_max = a.get("Volume (L)_max", 0)
            pdf.kv("Volume range (L)", f"{vol_min:.1f} - {vol_max:.1f}")
            _env_rows = []
            for p in _key_params:
                p_min_col = f"{p}_min"
                p_max_col = f"{p}_max"
                if p_min_col in a.index and p_max_col in a.index:
                    lo = a[p_min_col]
                    hi = a[p_max_col]
                    if np.isfinite(lo) and np.isfinite(hi):
                        _env_rows.append([p, f"{lo:.3g}", f"{hi:.3g}"])
            if _env_rows:
                pdf.data_table(["Parameter", "Min", "Max"], _env_rows,
                               col_widths=[70, 50, 50])
            pdf.ln(2)

    # ── Scale-up ratios page ─────────────────────────────────────────────
    if env_df is not None and not env_df.empty and len(selected_names) >= 2:
        pdf.add_page()
        pdf.section_title("Scale-Up Impact Summary")
        pdf.body_text(
            "Ratios use midpoint (average of 4 corners) for each parameter, "
            "relative to the first selected reactor."
        )
        _su_params = ["P/V (W/L)", "Blend time 95% (s)", "Tip speed (m/s)",
                      "Da_macro", "Da_micro", "Re"]
        mid_df = env_df.groupby("Reactor", sort=False)[_su_params + ["Volume (L)"]].mean().reset_index()
        if len(mid_df) >= 2:
            ref = mid_df.iloc[0]
            for _, row in mid_df.iloc[1:].iterrows():
                pdf.sub_title(f"{row['Reactor']} vs {ref['Reactor']}")
                _ratio_rows = []
                for p in _su_params:
                    ref_val = ref[p]
                    row_val = row[p]
                    if np.isfinite(ref_val) and np.isfinite(row_val) and ref_val != 0:
                        _ratio_rows.append([p, f"{ref_val:.3g}", f"{row_val:.3g}",
                                            f"{row_val / ref_val:.2f}x"])
                if _ratio_rows:
                    pdf.data_table(["Parameter", ref['Reactor'], row['Reactor'], "Ratio"],
                                   _ratio_rows, col_widths=[50, 35, 35, 25])

    # ── Scale-Up Matching Results ────────────────────────────────────────
    scaling_results = snap.get("scaling_results", [])
    scaling_all_params = snap.get("scaling_all_params", [])
    scale_param = snap.get("scale_param", "")
    scale_basis_reactor = snap.get("scale_basis_reactor", "")

    if scaling_results and scale_param:
        pdf.add_page()
        pdf.section_title("Scale-Up Matching Results")
        pdf.body_text(
            f"Operating conditions were determined for each target reactor "
            f"to match the basis reactor's value of '{scale_param}'."
        )
        pdf.kv("Basis reactor", scale_basis_reactor, bold_val=True)
        # Find basis value from results
        _basis_entry = [r for r in scaling_results if r.get("Role") == "Basis"]
        if _basis_entry:
            _bv = _basis_entry[0].get(scale_param, 0)
            if np.isfinite(_bv):
                pdf.kv("Target value", f"{_bv:.6g}")
            _brpm = _basis_entry[0].get("RPM", 0)
            _bvol = _basis_entry[0].get("Volume (L)", 0)
            pdf.kv("Basis conditions", f"{_brpm:.0f} RPM, {_bvol:.1f} L")
        pdf.ln(4)

        # Matched conditions table
        _scale_headers = ["Reactor", "Role", "RPM", "Volume (L)", scale_param, "Status"]
        _scale_rows = []
        for sr in scaling_results:
            _r_rpm = sr.get("RPM", 0)
            _r_vol = sr.get("Volume (L)", 0)
            _r_val = sr.get(scale_param, 0)
            _scale_rows.append([
                str(sr.get("Reactor", "")),
                str(sr.get("Role", "")),
                f"{_r_rpm:.1f}" if np.isfinite(_r_rpm) else "N/A",
                f"{_r_vol:.2f}" if np.isfinite(_r_vol) else "N/A",
                f"{_r_val:.6g}" if np.isfinite(_r_val) else "N/A",
                str(sr.get("Status", "")),
            ])
        pdf.data_table(_scale_headers, _scale_rows,
                       col_widths=[30, 18, 20, 22, 30, 50])
        pdf.ln(4)

        # Full comparison table at matched conditions
        if scaling_all_params:
            pdf.sub_title("Full Parameter Comparison at Matched Conditions")
            _compare_params = [
                "Re", "P/V (W/L)", "Tip speed (m/s)", "Blend time 95% (s)",
                "Micromix time t_E (s)", "Avg shear rate (1/s)",
                "kLa (1/s)", "Torque/V (N.m/m3)",
            ]
            _cp_headers = ["Parameter"] + [sp.get("Reactor", "") for sp in scaling_all_params]
            _cp_rows = []
            for p in _compare_params:
                row = [p]
                for sp in scaling_all_params:
                    val = sp.get(p, 0)
                    row.append(f"{val:.4g}" if isinstance(val, (int, float)) and np.isfinite(val) else "N/A")
                _cp_rows.append(row)
            _n_cols = len(_cp_headers)
            _col_w = [40] + [int(130 / max(_n_cols - 1, 1))] * (_n_cols - 1)
            pdf.data_table(_cp_headers, _cp_rows, col_widths=_col_w)

            # Percentage difference table
            if len(scaling_all_params) >= 2:
                pdf.sub_title("Percentage Difference vs. Basis Reactor")
                _basis_sp = scaling_all_params[0]
                _pct_rows = []
                for p in _compare_params:
                    row = [p]
                    for sp in scaling_all_params:
                        b_val = _basis_sp.get(p, 0)
                        t_val = sp.get(p, 0)
                        if (isinstance(b_val, (int, float)) and np.isfinite(b_val)
                                and b_val != 0 and isinstance(t_val, (int, float))
                                and np.isfinite(t_val)):
                            pct = (t_val - b_val) / abs(b_val) * 100
                            row.append(f"{pct:+.1f}%")
                        else:
                            row.append("N/A")
                    _pct_rows.append(row)
                pdf.data_table(_cp_headers, _pct_rows, col_widths=_col_w)

    # ── Operating Envelope Charts ────────────────────────────────────────
    _curve_data = snap.get("curve_data")
    _report_chart_params = snap.get("report_chart_params", [])
    if _curve_data and _report_chart_params:
        add_comparison_charts(pdf, _curve_data, env_df, reactor_info,
                              _report_chart_params)

    # ── Recommendations ──────────────────────────────────────────────────
    pdf.add_page()
    pdf.section_title("Recommendations")
    recs = []
    if agg_df is not None and not agg_df.empty:
        for _, a in agg_df.iterrows():
            rname = a["Reactor"]
            da_macro_max = a.get("Da_macro_max", 0)
            da_micro_max = a.get("Da_micro_max", 0)
            if np.isfinite(da_macro_max) and da_macro_max >= 1:
                recs.append(f"{rname}: Macromixing-sensitive at worst case (Da_macro = {da_macro_max:.2g}).")
            if np.isfinite(da_micro_max) and da_micro_max >= 1:
                recs.append(f"{rname}: Micromixing-sensitive at worst case (Da_micro = {da_micro_max:.2g}).")
    if not recs:
        recs.append("No mixing limitations identified across the compared reactors at the evaluated conditions.")
    for rec in recs:
        pdf.body_text(f"- {rec}")

    return report_bytes(pdf)


def build_protocol_pdf(snap: dict) -> bytes:
    """Build PDF report for Page 10 – Mixing Sensitivity Protocol."""
    rxn_name = snap["reaction"]
    t_rxn = snap.get("t_rxn")
    rxn_delta_H = snap.get("rxn_delta_H", 0.0)
    phases = snap.get("phases", [])
    findings = snap.get("findings", [])  # list of (mechanism, status, detail)
    next_steps = snap.get("next_steps", [])  # list of {Area, Action}
    bourne_result = snap.get("bourne_result", "Not performed")
    competing = snap.get("competing", "Not assessed")
    overall_verdict = snap.get("overall_verdict", "")
    using_approximate = snap.get("using_approximate", False)
    bourne_meta = snap.get("bourne_meta", {})
    bourne_tests = snap.get("bourne_tests", [])
    bourne_mechanism = snap.get("bourne_mechanism", "")
    bourne_only = snap.get("bourne_only", False)
    caveat = snap.get("caveat", "")

    title = f"Sensitivity Protocol \u2014 {rxn_name}"
    pdf = new_report(title)

    # ── Page 1: Title & Inputs ───────────────────────────────────────────
    pdf.add_page()
    pdf.set_font(pdf._FONT, "B", 20)
    pdf.set_text_color(30, 30, 80)
    _title_text = (
        "Bourne Protocol Result Report" if bourne_only
        else "Reaction Sensitivity Protocol Report"
    )
    pdf.cell(0, 14, pdf._s(_title_text), align="C")
    pdf.ln(18)

    pdf.section_title("Reaction Input")
    pdf.kv("Reaction", rxn_name, bold_val=True)
    if t_rxn is not None:
        pdf.kv("Reaction time (t_rxn)", f"{t_rxn:.4g} s")
    else:
        pdf.kv("Reaction time (t_rxn)", "Not assessed (no kinetics data)")
    pdf.kv("Delta H (kJ/mol)", f"{rxn_delta_H:.1f}" if rxn_delta_H != 0 else "N/A")
    pdf.kv("Phases", ", ".join(phases) if phases
           else ("Not assessed" if bourne_only else "Liquid (single phase)"))
    if using_approximate:
        pdf.assessment_box("Approximate kinetics used -- results are indicative", "AMBER")
    if caveat:
        pdf.assessment_box("Caveat: " + caveat.replace("**", ""), "AMBER")
    pdf.ln(4)

    # ── Protocol findings ────────────────────────────────────────────────
    pdf.section_title("Protocol Findings")
    pdf.kv("Bourne pre-screen", bourne_result)
    pdf.kv("Competing reactions", competing)
    pdf.ln(4)

    # ── Imported Bourne Protocol experimental findings ───────────────────
    if bourne_tests:
        pdf.sub_title("Bourne Protocol Experimental Findings")
        if bourne_meta:
            _meta_line = "  |  ".join(f"{_k}: {_v}" for _k, _v in bourne_meta.items())
            pdf.body_text(_meta_line)
            pdf.ln(1)
        _b_rows = []
        for _t in bourne_tests:
            _b_rows.append([
                str(_t.get("Test", "")),
                str(_t.get("Finding", "")),
                str(_t.get("Sensitive KPI(s)", "")),
            ])
        pdf.data_table(
            ["Test", "Finding", "Sensitive KPI(s)"], _b_rows,
            col_widths=[45, 70, 55], wrap=True,
        )
        if bourne_mechanism:
            pdf.ln(1)
            pdf.body_text(
                f"Controlling scale identified by the Bourne Protocol: {bourne_mechanism}."
            )
        pdf.ln(4)

    # Overall verdict
    if overall_verdict:
        if "high" in overall_verdict.lower():
            _oc = "RED"
        elif "moderate" in overall_verdict.lower() or "low-to-moderate" in overall_verdict.lower():
            _oc = "AMBER"
        else:
            _oc = "GREEN"
        pdf.assessment_box(overall_verdict, _oc)
        pdf.ln(4)

    # Findings table
    if findings:
        pdf.sub_title("Detailed Findings")
        _find_rows = []
        for mechanism, status, detail in findings:
            status_clean = status.replace("🔴", "[RED]").replace("🟡", "[AMBER]").replace("🟢", "[GREEN]").replace("⚪", "[N/A]")
            status_short = status_clean.split(" — ")[0].strip() if " — " in status_clean else status_clean
            _find_rows.append([mechanism, status_short, detail])
        pdf.data_table(["Mechanism", "Status", "Detail"], _find_rows,
                       col_widths=[35, 40, 95])
        pdf.ln(4)

    # ── Recommendations page ─────────────────────────────────────────────
    pdf.add_page()
    pdf.section_title("Recommended Next Steps")
    if next_steps:
        _step_rows = [[step.get("Area", ""), step.get("Action", "")]
                      for step in next_steps]
        pdf.data_table(["Area", "Recommended Action"], _step_rows,
                       col_widths=[40, 130])
    else:
        pdf.body_text(
            "The reaction appears low risk for mixing sensitivity. "
            "Standard scale-up practices should be sufficient."
        )

    return report_bytes(pdf)


def _bourne_t2_short_labels(responses) -> list[str]:
    """Return concise, basis-aware column labels for a Test 2 response table.

    Uses the condition labels stored in the assessment snapshot (which reflect
    the feed-rate/feed-time basis and the slow -> center -> fast ordering
    chosen in the app), shortened for the narrow PDF columns. Falls back to a
    generic slow/center/fast set for legacy snapshots without stored labels.
    """
    labels = responses.get("labels") if isinstance(responses, dict) else None
    if not labels:
        return ["Slow (3x)", "Center (1x)", "Fast (1/3x)"]
    short = []
    for lbl in labels:
        s = str(lbl).replace("feed ", "").replace("  ", " ").strip()
        short.append(s)
    return short


def _bourne_later_test_responses(pdf, responses, short_labels,
                                 sensitive_text, insensitive_text, may_text):
    """Render a later Bourne test's responses (multi-KPI aware) + verdict box.

    Mirrors the Test 1 KPI rendering so Tests 2 & 3 show the same set of KPIs.
    Falls back to the legacy single-KPI layout for older snapshots.
    """
    kpi_results = responses.get("kpi_results", [])
    if kpi_results:
        pdf.sub_title("Responses")
        _hdr = ["KPI", "Mode"] + list(short_labels) + ["Max change", "Sensitive?"]
        _rows = []
        for r in kpi_results:
            _is_qual = r.get("qualitative", False)
            if _is_qual:
                _vals = [(str(v) if str(v).strip() else "--") for v in r.get("resp", [])]
                _delta = "--"
            else:
                _vals = [f"{v:.4g}" for v in r.get("resp", [])]
                _delta = f"{r.get('max_pct', 0):.1f}%"
            _rows.append(
                [r.get("name", ""), "Qual" if _is_qual else "Quant"]
                + _vals + [_delta, "Yes" if r.get("sensitive") else "No"]
            )
        pdf.data_table(_hdr, _rows, col_widths=[40, 14, 22, 22, 22, 20, 18], wrap=True)
        n_sensitive = responses.get("n_sensitive", 0)
        n_total = responses.get("n_total", len(kpi_results))
        _status = responses.get(
            "status", "sensitive" if n_sensitive > 0 else "not_sensitive")
        if _status == "not_sensitive":
            colour, verdict = "GREEN", insensitive_text
        elif _status == "may_be_sensitive":
            colour, verdict = "AMBER", may_text
        else:
            colour, verdict = "RED", sensitive_text
        pdf.assessment_box(
            f"{verdict}  ({n_sensitive} / {n_total} KPIs sensitive)", colour)
    else:
        # Legacy single-KPI snapshot (older sessions)
        pdf.sub_title(f"Responses ({responses.get('resp_name', '')})")
        resp = responses.get("resp", [])
        _qualitative = responses.get("qualitative", False)
        if _qualitative:
            _rows = [[lbl, (str(val) if val else "--")]
                     for lbl, val in zip(short_labels, resp)]
        else:
            _rows = [[lbl, f"{val:.4g}"] for lbl, val in zip(short_labels, resp)]
        pdf.data_table(["Condition", "Response"], _rows, col_widths=[80, 60], wrap=True)
        sensitive = responses.get("sensitive", False)
        colour = "RED" if sensitive else "GREEN"
        if _qualitative:
            pdf.assessment_box(
                f"{sensitive_text if sensitive else insensitive_text}  (qualitative)",
                colour)
        else:
            max_pct = responses.get("max_pct", 0)
            pdf.assessment_box(
                f"{sensitive_text if sensitive else insensitive_text}"
                f"  (max change = {max_pct:.1f}%)",
                colour)


def build_bourne_protocol_pdf(snap: dict) -> bytes:
    """Build PDF report for Page 6 – Bourne Protocol."""
    reactor_name = snap.get("reactor", "Manual entry")
    fluid_name = snap.get("fluid", "")
    V_L = snap.get("V_L", 0.0)
    dominant = snap.get("dominant", "Unknown")
    conclusions = snap.get("conclusions", [])
    scaleup_notes = snap.get("scaleup_notes", [])
    t1_conditions = snap.get("t1_conditions", [])
    t1_responses = snap.get("t1_responses")
    t2_responses = snap.get("t2_responses")
    t3_responses = snap.get("t3_responses")
    centerpoint_metrics = snap.get("centerpoint_metrics", {})

    title = f"Bourne Protocol \u2014 {reactor_name}"
    pdf = new_report(title)

    # ── Page 1: Title & System ───────────────────────────────────────────
    pdf.add_page()
    pdf.set_font(pdf._FONT, "B", 20)
    pdf.set_text_color(30, 30, 80)
    pdf.cell(0, 14, pdf._s("Bourne Protocol Report"), align="C")
    pdf.ln(18)

    _project_name = snap.get("project_name", "")
    _step_number = snap.get("step_number", "")
    _unit_operation = snap.get("unit_operation", "")
    if _project_name or _step_number or _unit_operation:
        pdf.section_title("Project Information")
        if _project_name:
            pdf.kv("Project", _project_name, bold_val=True)
        if _step_number:
            pdf.kv("Step number", _step_number, bold_val=True)
        if _unit_operation:
            pdf.kv("Unit operation", _unit_operation, bold_val=True)
        pdf.ln(2)

    pdf.section_title("System Configuration")
    pdf.kv("Reactor", reactor_name, bold_val=True)
    pdf.kv("Fluid", fluid_name, bold_val=True)
    pdf.kv("Working volume", f"{V_L:.3f} L")
    if centerpoint_metrics:
        pdf.ln(2)
        pdf.sub_title("Centerpoint Hydrodynamics")
        cm_rows = []
        for k, v in centerpoint_metrics.items():
            cm_rows.append((k, f"{v:.4g}" if isinstance(v, float) else str(v)))
        pdf.metric_table(cm_rows, cols=2)
    pdf.ln(4)

    # ── Test 1 ───────────────────────────────────────────────────────────
    pdf.section_title("Test 1 -- Impeller Speed")
    pdf.sub_title("Conditions")
    if t1_conditions:
        _t1_cond_headers = ["Condition", "Volume (L)", "N (RPM)", "P/m (W/kg)", "P/V (W/L)", "Tip speed (m/s)"]
        _t1_cond_rows = []
        for cond in t1_conditions:
            _t1_cond_rows.append([
                cond.get("Condition", ""),
                _fmt_sig(cond.get('Volume (L)', 0)),
                f"{cond.get('N (RPM)', 0):.0f}",
                f"{cond.get('P/m (W/kg)', 0):.4g}",
                f"{cond.get('P/V (W/L)', 0):.4g}",
                f"{cond.get('Tip speed (m/s)', 0):.3f}",
            ])
        pdf.data_table(_t1_cond_headers, _t1_cond_rows, col_widths=[50, 25, 25, 30, 25, 30])
        pdf.ln(1)
        pdf.body_text("Feed rate and feed location held constant.")
    if t1_responses:
        pdf.ln(2)
        labels = t1_responses.get("labels", [])
        _short_labels = [str(l).split("(")[0].strip() for l in labels]
        kpi_results = t1_responses.get("kpi_results", [])
        if kpi_results:
            pdf.sub_title("Responses")
            _hdr = ["KPI", "Mode"] + list(_short_labels) + ["Max change", "Sensitive?"]
            _rows = []
            for r in kpi_results:
                _is_qual = r.get("qualitative", False)
                if _is_qual:
                    _vals = [(str(v) if str(v).strip() else "--") for v in r.get("resp", [])]
                    _delta = "--"
                else:
                    _vals = [f"{v:.4g}" for v in r.get("resp", [])]
                    _delta = f"{r.get('max_pct', 0):.1f}%"
                _rows.append(
                    [r.get("name", ""), "Qual" if _is_qual else "Quant"]
                    + _vals + [_delta, "Yes" if r.get("sensitive") else "No"]
                )
            pdf.data_table(_hdr, _rows,
                           col_widths=[40, 14, 22, 22, 22, 20, 18], wrap=True)
            n_sensitive = t1_responses.get("n_sensitive", 0)
            n_total = t1_responses.get("n_total", len(kpi_results))
            colour = "RED" if n_sensitive > 0 else "GREEN"
            pdf.assessment_box(
                f"{n_sensitive} / {n_total} KPIs sensitive", colour,
            )
        else:
            # Legacy single-KPI snapshot (older sessions)
            pdf.sub_title(f"Responses ({t1_responses.get('resp_name', '')})")
            resp = t1_responses.get("resp", [])
            _qualitative = t1_responses.get("qualitative", False)
            if _qualitative:
                _t1_resp_rows = [[lbl, (str(val) if val else "--")]
                                 for lbl, val in zip(_short_labels, resp)]
            else:
                _t1_resp_rows = [[lbl, f"{val:.4g}"] for lbl, val in zip(_short_labels, resp)]
            pdf.data_table(["Condition", "Response"], _t1_resp_rows,
                           col_widths=[80, 60], wrap=True)
            sensitive = t1_responses.get("sensitive", False)
            colour = "RED" if sensitive else "GREEN"
            if _qualitative:
                pdf.assessment_box(
                    f"Qualitative -- {'Sensitive' if sensitive else 'Not sensitive'}",
                    colour,
                )
            else:
                max_pct = t1_responses.get("max_pct", 0)
                pdf.assessment_box(
                    f"Max change = {max_pct:.1f}% -- {'Sensitive' if sensitive else 'Not sensitive'}",
                    colour,
                )

    # ── Test 2 ───────────────────────────────────────────────────────────
    if t2_responses:
        pdf.section_title("Test 2 -- Feed Rate / Feed Time")
        pdf.sub_title("Conditions")
        t2_conds = snap.get("t2_conditions", {})
        if t2_conds:
            pdf.body_text(
                f"Impeller speed held at N = {t2_conds.get('N_RPM', 0):.0f} RPM.  "
                f"Volume = {V_L:.3f} L.  "
                f"Feed location: {t2_conds.get('feed_location', 'constant')}."
            )
            pdf.ln(1)
            _t2_cond_headers = ["Condition", "Feed time (min)", "Flow rate (mL/min)"]
            _t2_cond_rows = []
            for row in t2_conds.get("rows", []):
                _t2_cond_rows.append([
                    row.get("Condition", ""),
                    f"{row.get('Feed time (min)', 0):.2f}",
                    f"{row.get('Flow rate (mL/min)', 0):.2f}",
                ])
            if _t2_cond_rows:
                pdf.data_table(_t2_cond_headers, _t2_cond_rows, col_widths=[65, 45, 45])
            pdf.ln(1)
            pdf.body_text(f"Total feed volume: {t2_conds.get('feed_vol_mL', 0):.1f} mL.")
        pdf.ln(2)
        _t2_short = _bourne_t2_short_labels(t2_responses)
        _bourne_later_test_responses(
            pdf, t2_responses,
            _t2_short,
            "Sensitive (mesomixing involved)",
            "Not sensitive (micromixing controls)",
            "May be sensitive (mesomixing involved)",
        )

    # ── Test 3 ───────────────────────────────────────────────────────────
    if t3_responses:
        pdf.section_title("Test 3 -- Feed Location")
        pdf.sub_title("Conditions")
        t3_conds = snap.get("t3_conditions", {})
        if t3_conds:
            pdf.body_text(
                f"Impeller speed held at N = {t3_conds.get('N_RPM', 0):.0f} RPM.  "
                f"Volume = {V_L:.3f} L.  "
                f"Feed time = {t3_conds.get('feed_time_min', 0):.1f} min (centerpoint)."
            )
            pdf.ln(1)
            _t3_cond_headers = ["Feed Location", "eps_loc/eps_avg", "eps_loc (W/m3)"]
            _t3_cond_rows = []
            for row in t3_conds.get("rows", []):
                _t3_cond_rows.append([
                    row.get("Feed Location", ""),
                    f"{row.get('eps_loc/eps_avg', 0):.1f}",
                    f"{row.get('eps_loc (W/m3)', 0):.1f}",
                ])
            if _t3_cond_rows:
                pdf.data_table(_t3_cond_headers, _t3_cond_rows, col_widths=[65, 40, 40])
        pdf.ln(2)
        _bourne_later_test_responses(
            pdf, t3_responses,
            ["Surface", "Sub-surface (mid)", "Impeller zone"],
            "Sensitive (mesomixing controls)",
            "Not sensitive (macromixing controls)",
            "May be sensitive (mesomixing controls)",
        )

    # ── Conclusion & Recommendations ─────────────────────────────────────
    pdf.add_page()
    pdf.section_title("Conclusion")

    if conclusions:
        _concl_rows = []
        for test_name, result, icon in conclusions:
            # ``result`` looks like "**Sensitive** (max 88.9% change) -> Mixing matters".
            # Split the bold verdict into the Result column and keep the rest as Detail.
            _m = re.match(r"\s*\*\*(.+?)\*\*\s*(.*)", result)
            if _m:
                _verdict = _m.group(1).strip()
                _detail = _m.group(2).strip()
            else:
                _verdict = ""
                _detail = result
            # Strip any remaining markdown emphasis markers.
            _verdict = _verdict.replace("**", "")
            _detail = _detail.replace("**", "")
            _concl_rows.append([test_name, _verdict, _detail])
        pdf.data_table(["Test", "Result", "Detail"], _concl_rows,
                       col_widths=[45, 38, 87])
        pdf.ln(4)

    if dominant == "Micromixing":
        colour = "GREEN"
    elif dominant == "Mesomixing":
        colour = "AMBER"
    else:
        colour = "RED"
    pdf.assessment_box(f"Dominant mixing limitation: {dominant}", colour)
    pdf.ln(4)

    pdf.section_title("Scale-Up Recommendations")
    if dominant == "Micromixing":
        pdf.body_text(
            "The molecular-scale engulfment step is rate-limiting. "
            "Maintain constant local energy dissipation (eps_loc) at the feed point on scale-up. "
            "Consider impeller type and feed-point proximity to the impeller."
        )
    elif dominant == "Mesomixing":
        pdf.body_text(
            "Feed-plume disintegration is rate-limiting. "
            "Hold the local energy dissipation (eps_loc) constant at the feed point on scale-up "
            "by matching power per unit volume (P/V) -- this means a LOWER rotational speed at larger "
            "scale (constant RPM is neither achievable nor correct). Also reduce the local feed rate: "
            "extend the feed time, use multiple feed points, and/or reduce the feed-pipe diameter to "
            "shrink the feed plume."
        )
    elif dominant == "Macromixing":
        pdf.body_text(
            "Bulk blending / circulation is rate-limiting. "
            "Focus on blend time reduction: high-efficiency impellers, multiple impellers, or static mixers. "
            "Consider continuous-flow alternatives with in-line mixing."
        )
    if scaleup_notes:
        pdf.ln(2)
        for note in scaleup_notes:
            pdf.body_text(f"- {note}")

    return report_bytes(pdf)


def build_bourne_step_pdf(snap: dict) -> bytes:
    """Build a focused single-step PDF for the Bourne Protocol (Page 6).

    Renders the system configuration plus one test step (1, 2, or 3) with its
    conditions and recorded responses. Complements the full end-of-protocol
    report produced by ``build_bourne_protocol_pdf``.
    """
    step = int(snap.get("step", 1))
    reactor_name = snap.get("reactor", "Manual entry")
    fluid_name = snap.get("fluid", "")
    V_L = snap.get("V_L", 0.0)
    centerpoint_metrics = snap.get("centerpoint_metrics", {})

    _step_titles = {
        1: "Test 1 -- Impeller Speed",
        2: "Test 2 -- Feed Rate / Feed Time",
        3: "Test 3 -- Feed Location",
    }
    step_title = _step_titles.get(step, f"Test {step}")

    title = f"Bourne Protocol {step_title} \u2014 {reactor_name}"
    pdf = new_report(title)

    # ── Title & System ───────────────────────────────────────────────────
    pdf.add_page()
    pdf.set_font(pdf._FONT, "B", 18)
    pdf.set_text_color(30, 30, 80)
    pdf.cell(0, 12, pdf._s(f"Bourne Protocol -- {step_title}"), align="C")
    pdf.ln(16)

    _project_name = snap.get("project_name", "")
    _step_number = snap.get("step_number", "")
    _unit_operation = snap.get("unit_operation", "")
    if _project_name or _step_number or _unit_operation:
        pdf.section_title("Project Information")
        if _project_name:
            pdf.kv("Project", _project_name, bold_val=True)
        if _step_number:
            pdf.kv("Step number", _step_number, bold_val=True)
        if _unit_operation:
            pdf.kv("Unit operation", _unit_operation, bold_val=True)
        pdf.ln(2)

    pdf.section_title("System Configuration")
    pdf.kv("Reactor", reactor_name, bold_val=True)
    pdf.kv("Fluid", fluid_name, bold_val=True)
    pdf.kv("Working volume", f"{V_L:.3f} L")
    if centerpoint_metrics:
        pdf.ln(2)
        pdf.sub_title("Centerpoint Hydrodynamics")
        cm_rows = []
        for k, v in centerpoint_metrics.items():
            cm_rows.append((k, f"{v:.4g}" if isinstance(v, float) else str(v)))
        pdf.metric_table(cm_rows, cols=2)
    pdf.ln(4)

    # ── Step 1 ───────────────────────────────────────────────────────────
    if step == 1:
        t1_conditions = snap.get("t1_conditions", [])
        t1_responses = snap.get("t1_responses")
        pdf.section_title(step_title)
        pdf.sub_title("Conditions")
        if t1_conditions:
            _t1_cond_headers = ["Condition", "Volume (L)", "N (RPM)", "P/m (W/kg)", "P/V (W/L)", "Tip speed (m/s)"]
            _t1_cond_rows = []
            for cond in t1_conditions:
                _t1_cond_rows.append([
                    cond.get("Condition", ""),
                    _fmt_sig(cond.get('Volume (L)', 0)),
                    f"{cond.get('N (RPM)', 0):.0f}",
                    f"{cond.get('P/m (W/kg)', 0):.4g}",
                    f"{cond.get('P/V (W/L)', 0):.4g}",
                    f"{cond.get('Tip speed (m/s)', 0):.3f}",
                ])
            pdf.data_table(_t1_cond_headers, _t1_cond_rows, col_widths=[50, 25, 25, 30, 25, 30])
            pdf.ln(1)
            pdf.body_text("Feed rate and feed location held constant.")
        if t1_responses:
            pdf.ln(2)
            labels = t1_responses.get("labels", [])
            _short_labels = [str(l).split("(")[0].strip() for l in labels]
            kpi_results = t1_responses.get("kpi_results", [])
            if kpi_results:
                pdf.sub_title("Responses")
                _hdr = ["KPI", "Mode"] + list(_short_labels) + ["Max change", "Sensitive?"]
                _rows = []
                for r in kpi_results:
                    _is_qual = r.get("qualitative", False)
                    if _is_qual:
                        _vals = [(str(v) if str(v).strip() else "--") for v in r.get("resp", [])]
                        _delta = "--"
                    else:
                        _vals = [f"{v:.4g}" for v in r.get("resp", [])]
                        _delta = f"{r.get('max_pct', 0):.1f}%"
                    _rows.append(
                        [r.get("name", ""), "Qual" if _is_qual else "Quant"]
                        + _vals + [_delta, "Yes" if r.get("sensitive") else "No"]
                    )
                pdf.data_table(_hdr, _rows, col_widths=[40, 14, 22, 22, 22, 20, 18], wrap=True)
                n_sensitive = t1_responses.get("n_sensitive", 0)
                n_total = t1_responses.get("n_total", len(kpi_results))
                _status = t1_responses.get(
                    "status", "sensitive" if n_sensitive > 0 else "not_sensitive")
                if _status == "not_sensitive":
                    _verdict = "Mixing does NOT matter -- process insensitive to impeller speed"
                    colour = "GREEN"
                elif _status == "may_be_sensitive":
                    _verdict = "Mixing MAY matter -- proceed to Test 2 with caution"
                    colour = "AMBER"
                else:
                    _verdict = "Mixing MATTERS -- proceed to Test 2"
                    colour = "RED"
                pdf.assessment_box(
                    f"{_verdict}  ({n_sensitive} / {n_total} KPIs sensitive)", colour)
            else:
                pdf.sub_title(f"Responses ({t1_responses.get('resp_name', '')})")
                resp = t1_responses.get("resp", [])
                _qualitative = t1_responses.get("qualitative", False)
                if _qualitative:
                    _t1_resp_rows = [[lbl, (str(val) if val else "--")]
                                     for lbl, val in zip(_short_labels, resp)]
                else:
                    _t1_resp_rows = [[lbl, f"{val:.4g}"] for lbl, val in zip(_short_labels, resp)]
                pdf.data_table(["Condition", "Response"], _t1_resp_rows, col_widths=[80, 60], wrap=True)
                sensitive = t1_responses.get("sensitive", False)
                colour = "RED" if sensitive else "GREEN"
                _verdict = ("Mixing MATTERS -- proceed to Test 2" if sensitive
                            else "Mixing does NOT matter -- process insensitive to impeller speed")
                if _qualitative:
                    pdf.assessment_box(
                        f"{_verdict}  (qualitative judgment)", colour)
                else:
                    max_pct = t1_responses.get("max_pct", 0)
                    pdf.assessment_box(
                        f"{_verdict}  (max change = {max_pct:.1f}%)", colour)

    # ── Step 2 ───────────────────────────────────────────────────────────
    elif step == 2:
        t2_responses = snap.get("t2_responses")
        pdf.section_title(step_title)
        pdf.sub_title("Conditions")
        t2_conds = snap.get("t2_conditions", {})
        if t2_conds:
            pdf.body_text(
                f"Impeller speed held at N = {t2_conds.get('N_RPM', 0):.0f} RPM.  "
                f"Volume = {V_L:.3f} L.  "
                f"Feed location: {t2_conds.get('feed_location', 'constant')}."
            )
            pdf.ln(1)
            _t2_cond_headers = ["Condition", "Feed time (min)", "Flow rate (mL/min)"]
            _t2_cond_rows = []
            for row in t2_conds.get("rows", []):
                _t2_cond_rows.append([
                    row.get("Condition", ""),
                    f"{row.get('Feed time (min)', 0):.2f}",
                    f"{row.get('Flow rate (mL/min)', 0):.2f}",
                ])
            if _t2_cond_rows:
                pdf.data_table(_t2_cond_headers, _t2_cond_rows, col_widths=[65, 45, 45])
            pdf.ln(1)
            pdf.body_text(f"Total feed volume: {t2_conds.get('feed_vol_mL', 0):.1f} mL.")
        if t2_responses:
            pdf.ln(2)
            _t2_short = _bourne_t2_short_labels(t2_responses)
            _bourne_later_test_responses(
                pdf, t2_responses,
                _t2_short,
                "Sensitive (mesomixing involved)",
                "Not sensitive (micromixing controls)",
                "May be sensitive (mesomixing involved)",
            )

    # ── Step 3 ───────────────────────────────────────────────────────────
    elif step == 3:
        t3_responses = snap.get("t3_responses")
        pdf.section_title(step_title)
        pdf.sub_title("Conditions")
        t3_conds = snap.get("t3_conditions", {})
        if t3_conds:
            pdf.body_text(
                f"Impeller speed held at N = {t3_conds.get('N_RPM', 0):.0f} RPM.  "
                f"Volume = {V_L:.3f} L.  "
                f"Feed time = {t3_conds.get('feed_time_min', 0):.1f} min (centerpoint)."
            )
            pdf.ln(1)
            _t3_cond_headers = ["Feed Location", "eps_loc/eps_avg", "eps_loc (W/m3)"]
            _t3_cond_rows = []
            for row in t3_conds.get("rows", []):
                _t3_cond_rows.append([
                    row.get("Feed Location", ""),
                    f"{row.get('eps_loc/eps_avg', 0):.1f}",
                    f"{row.get('eps_loc (W/m3)', 0):.1f}",
                ])
            if _t3_cond_rows:
                pdf.data_table(_t3_cond_headers, _t3_cond_rows, col_widths=[65, 40, 40])
        if t3_responses:
            pdf.ln(2)
            _bourne_later_test_responses(
                pdf, t3_responses,
                ["Surface", "Sub-surface (mid)", "Impeller zone"],
                "Sensitive (mesomixing controls)",
                "Not sensitive (macromixing controls)",
                "May be sensitive (mesomixing controls)",
            )

    return report_bytes(pdf)


def build_heat_transfer_pdf(snap: dict) -> bytes:
    reactor_name = snap["reactor"]
    fluid_name = snap["fluid"]
    fluid_T_C = snap["fluid_T_C"]
    N_rpm = snap["N_rpm"]
    V_L = snap["V_L"]
    htm_name = snap["htm_name"]
    nu_corr = snap["nu_corr"]
    T_start = snap["T_start"]
    T_target = snap["T_target"]
    T_jacket_in = snap["T_jacket_in"]
    wall_material = snap["wall_material"]
    wall_mm = snap["wall_mm"]
    lining_material = snap["lining_material"]
    fouling_R = snap["fouling_R"]

    coefficients = snap["coefficients"]
    resistances = snap["resistances"]
    time_estimates = snap["time_estimates"]
    rpm_sensitivity = snap.get("rpm_sensitivity")
    nusselt_comparison = snap.get("nusselt_comparison", [])
    htm_comparison = snap.get("htm_comparison", [])

    fig_T_png = snap.get("fig_T_png")
    fig_Q_png = snap.get("fig_Q_png")
    fig_rate_png = snap.get("fig_rate_png")
    fig_rpm_png = snap.get("fig_rpm_U_png")
    fig_trpm_png = snap.get("fig_rpm_time_png")
    fig_res_png = snap.get("fig_resistance_png")

    _is_cooling = T_target < T_start
    _mode_label = "Cooling" if _is_cooling else "Heating"

    title = f"Heat Transfer -- {reactor_name}"
    pdf = new_report(title)

    # ── Page 1: Title & System Info ──────────────────────────────────────
    pdf.add_page()
    pdf.set_font(pdf._FONT, "B", 20)
    pdf.set_text_color(30, 30, 80)
    pdf.cell(0, 14, pdf._s("Heat Transfer Report"), align="C")
    pdf.ln(18)

    pdf.section_title("System Configuration")
    pdf.kv("Reactor", reactor_name, bold_val=True)
    pdf.kv("Fluid", f"{fluid_name}  ({fluid_T_C:.1f} deg C)", bold_val=True)
    pdf.kv("Stir speed", f"{N_rpm:.0f} RPM")
    pdf.kv("Liquid volume", f"{_fmt_sig(V_L)} L")
    pdf.kv("Heat transfer medium", htm_name, bold_val=True)
    pdf.kv("Nusselt correlation", nu_corr)
    pdf.kv("Mode", _mode_label)
    pdf.kv("T_start", f"{T_start:.1f} deg C")
    pdf.kv("T_target", f"{T_target:.1f} deg C")
    pdf.kv("T_jacket inlet", f"{T_jacket_in:.1f} deg C")
    pdf.ln(2)

    pdf.sub_title("Wall & Lining")
    pdf.kv("Wall material", wall_material)
    pdf.kv("Wall thickness", f"{wall_mm:.1f} mm")
    pdf.kv("Lining", lining_material)
    pdf.kv("Fouling resistance", f"{fouling_R:.5f} m2.K/W")
    pdf.ln(4)

    # ── Heat Transfer Coefficients ───────────────────────────────────────
    pdf.section_title("Heat Transfer Coefficients")
    coeff_rows = [
        ("h_i (process side)", f"{coefficients['h_i']:.1f} W/(m2.K)"),
        ("h_o (jacket side)", f"{coefficients['h_o']:.1f} W/(m2.K)"),
        ("U (overall)", f"{coefficients['U']:.1f} W/(m2.K)"),
        ("Nu (process side)", f"{coefficients['Nu']:.1f}"),
        ("Re (impeller)", f"{coefficients['Re']:.0f}"),
        ("Pr (process)", f"{coefficients['Pr']:.1f}"),
        ("A_ht (m2)", f"{coefficients['A_ht']:.4f}"),
        ("P_agitator (W)", f"{coefficients['P_agitator']:.2f}"),
    ]
    pdf.metric_table(coeff_rows, cols=2)
    pdf.ln(2)

    # ── Resistance Breakdown ─────────────────────────────────────────────
    pdf.section_title("Thermal Resistance Breakdown")
    if resistances:
        _res_headers = ["Layer", "R (m2.K/W)", "% of Total"]
        _res_rows = [[name, f"{value:.5f}", f"{pct:.1f}%"] for name, value, pct in resistances]
        pdf.data_table(_res_headers, _res_rows, col_widths=[70, 55, 45])
    _ctrl = snap.get("controlling_resistance", "")
    if _ctrl:
        pdf.body_text(f"Controlling resistance: {_ctrl}")

    if fig_res_png:
        pdf.ln(2)
        pdf.image(io.BytesIO(fig_res_png), x=15, w=180)
        pdf.ln(5)

    # ── Time Estimates ───────────────────────────────────────────────────
    pdf.add_page()
    pdf.section_title("Time Estimates")
    te_rows = [
        ("Q_max initial (W)", f"{time_estimates['Q_max']:.1f}"),
        ("Initial dT/dt (deg C/min)", f"{time_estimates['dT_dt_init']:.3f}"),
        ("Analytical time (log-mean)", f"{time_estimates['t_analytical_min']:.1f} min"
         if time_estimates["t_analytical_min"] < 1e6 else "inf"),
        ("Simulated (const. jacket)", f"{time_estimates['t_sim_const_min']:.1f} min"),
        ("Simulated (variable jacket)", f"{time_estimates['t_sim_var_min']:.1f} min"),
    ]
    pdf.metric_table(te_rows, cols=1)
    pdf.ln(4)

    # ── Temperature Profile Charts ───────────────────────────────────────
    if fig_T_png:
        pdf.section_title("Temperature Profile")
        pdf.image(io.BytesIO(fig_T_png), x=15, w=180)
        pdf.ln(5)

    if fig_Q_png:
        pdf.add_page()
        pdf.section_title("Jacket Heat Duty vs. Time")
        pdf.image(io.BytesIO(fig_Q_png), x=15, w=180)
        pdf.ln(5)

    if fig_rate_png:
        pdf.section_title("Rate of Change vs. Time")
        pdf.image(io.BytesIO(fig_rate_png), x=15, w=180)
        pdf.ln(5)

    # ── U vs Time (temperature-dependent) ────────────────────────────────
    fig_U_png = snap.get("fig_U_png")
    if fig_U_png:
        pdf.add_page()
        pdf.section_title("Overall U vs. Time (Temperature-Dependent Properties)")
        pdf.image(io.BytesIO(fig_U_png), x=15, w=180)
        pdf.ln(5)

    # ── RPM Sensitivity ──────────────────────────────────────────────────
    if fig_rpm_png or fig_trpm_png:
        pdf.add_page()
        pdf.section_title("RPM Sensitivity")
        if fig_rpm_png:
            pdf.image(io.BytesIO(fig_rpm_png), x=15, w=180)
            pdf.ln(5)
        if fig_trpm_png:
            pdf.image(io.BytesIO(fig_trpm_png), x=15, w=180)
            pdf.ln(5)

    # ── Nusselt Correlation Comparison ────────────────────────────────────
    if nusselt_comparison:
        pdf.add_page()
        pdf.section_title("Nusselt Correlation Comparison")
        _nu_headers = ["Correlation", "Nu", "h_i (W/(m2.K))", "U (W/(m2.K))", "Time (min)"]
        _nu_rows = [
            [r["Correlation"], r["Nu"], r["h_i (W/(m2.K))"], r["U (W/(m2.K))"], r["Time (min)"]]
            for r in nusselt_comparison
        ]
        pdf.data_table(_nu_headers, _nu_rows, col_widths=[52, 22, 35, 35, 26])
        pdf.ln(4)

    # ── HTM Comparison ───────────────────────────────────────────────────
    if htm_comparison:
        pdf.section_title("Heat Transfer Media Comparison")
        _htm_headers = ["Medium", "h_o (W/(m2.K))", "U (W/(m2.K))", "Time (min)", "In range?"]
        _htm_rows = [
            [r["Medium"], r["h_o (W/(m2.K))"], r["U (W/(m2.K))"], r["Time (min)"], r.get("In range?", "")]
            for r in htm_comparison
        ]
        pdf.data_table(_htm_headers, _htm_rows, col_widths=[52, 35, 35, 28, 20])
        pdf.ln(4)

    return report_bytes(pdf)
