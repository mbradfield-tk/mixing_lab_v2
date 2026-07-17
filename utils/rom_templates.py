"""Correlation templates for ROM / Experimental fitting.

Each template defines a functional form and lists the input columns it
requires.  The fitter checks which columns are present in the uploaded
data and offers only compatible templates.

Adding a new template
---------------------
1.  Create an instance of ``CorrTemplate``.
2.  Append it to ``TEMPLATES``.
3.  The fitting page and registry integration pick it up automatically.
"""

from __future__ import annotations

import numpy as np
from dataclasses import dataclass, field
from typing import Callable


# ═══════════════════════════════════════════════════════════════════════════
# Template data-class
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class CorrTemplate:
    """Blueprint for a fittable correlation form."""

    id: str
    """Unique machine-readable identifier, e.g. ``'kla_power_law'``."""

    param: str
    """Target parameter key (matches ``rom_registry.SUPPORTED_PARAMS``)."""

    name: str
    """Human-readable name shown in the UI."""

    required_columns: list[str]
    """Column names that must be present in the uploaded data.
    Each column is a physical variable (e.g. ``'P_V'``, ``'v_s'``)."""

    column_labels: dict[str, str]
    """Mapping of column name → description for the upload instructions."""

    n_coeffs: int
    """Number of fitted coefficients."""

    coeff_names: list[str]
    """Display names for the fitted coefficients (length == n_coeffs)."""

    initial_guess: list[float]
    """Starting values for the optimiser (length == n_coeffs)."""

    bounds_lower: list[float] = field(default_factory=list)
    """Lower bounds for each coefficient (``-np.inf`` if unconstrained)."""

    bounds_upper: list[float] = field(default_factory=list)
    """Upper bounds for each coefficient (``np.inf`` if unconstrained)."""

    latex_template: str = ""
    """LaTeX string with ``{c0}``, ``{c1}``, … placeholders for fitted values."""

    description: str = ""
    """Short description of the model form."""

    log_transform: bool = True
    """If True, the fitter takes log of model & data (linearises power-laws)."""

    def model(self, coeffs: np.ndarray, X: dict[str, np.ndarray]) -> np.ndarray:
        """Evaluate the template with *coeffs* and column arrays *X*.

        Override-friendly: subclasses may override this, but for most
        power-law forms the default implementation delegates to
        ``_model_func`` if provided.
        """
        raise NotImplementedError("Subclass must implement model()")

    def latex_filled(self, coeffs: np.ndarray) -> str:
        """Return the LaTeX string with fitted coefficient values."""
        subs = {f"c{i}": f"{c:.4g}" for i, c in enumerate(coeffs)}
        return self.latex_template.format(**subs)

    def build_func(self, coeffs: np.ndarray) -> Callable[..., float]:
        """Return a closure that can serve as a ``Correlation.func``."""
        _coeffs = coeffs.copy()
        _tmpl = self

        def _func(**kw) -> float:
            X = {}
            for col in _tmpl.required_columns:
                val = kw.get(col, 0.0)
                X[col] = np.atleast_1d(float(val))
            result = _tmpl.model(_coeffs, X)
            return float(np.clip(result, 0.0, None)[0])

        return _func


# ═══════════════════════════════════════════════════════════════════════════
# Concrete templates
# ═══════════════════════════════════════════════════════════════════════════

# ── Helpers for concise definitions ──────────────────────────────────────

class PowerLaw2(CorrTemplate):
    r"""y = A · x1^b · x2^c"""

    def model(self, coeffs, X):
        A, b, c = coeffs
        cols = self.required_columns
        return A * X[cols[0]] ** b * X[cols[1]] ** c


class PowerLaw1(CorrTemplate):
    r"""y = A · x1^b"""

    def model(self, coeffs, X):
        A, b = coeffs
        cols = self.required_columns
        return A * X[cols[0]] ** b


class PowerLaw3(CorrTemplate):
    r"""y = A · x1^b · x2^c · x3^d"""

    def model(self, coeffs, X):
        A, b, c, d = coeffs
        cols = self.required_columns
        return A * X[cols[0]] ** b * X[cols[1]] ** c * X[cols[2]] ** d


class PowerLaw4(CorrTemplate):
    r"""y = A · x1^b · x2^c · x3^d · x4^e"""

    def model(self, coeffs, X):
        A, b, c, d, e = coeffs
        cols = self.required_columns
        return A * X[cols[0]] ** b * X[cols[1]] ** c * X[cols[2]] ** d * X[cols[3]] ** e


class LinearCombo2(CorrTemplate):
    r"""y = a · x1 + b · x2 + c"""

    def model(self, coeffs, X):
        a, b, c = coeffs
        cols = self.required_columns
        return a * X[cols[0]] + b * X[cols[1]] + c

    log_transform: bool = False


class PowerLaw1Offset(CorrTemplate):
    r"""y = A · x1^b + C"""

    def model(self, coeffs, X):
        A, b, C = coeffs
        cols = self.required_columns
        return A * X[cols[0]] ** b + C

    log_transform: bool = False


# ═══════════════════════════════════════════════════════════════════════════
# Template catalogue
# ═══════════════════════════════════════════════════════════════════════════

TEMPLATES: list[CorrTemplate] = [
    # ── kLa (sparged) ────────────────────────────────────────────────────
    PowerLaw2(
        id="kla_pv_vs",
        param="kla_sparged",
        name="kLa = A·(P/V)^b·vₛ^c  (Van 't Riet form)",
        required_columns=["P_V", "v_s"],
        column_labels={"P_V": "Power per volume (W/m³)", "v_s": "Superficial gas velocity (m/s)"},
        n_coeffs=3,
        coeff_names=["A", "b", "c"],
        initial_guess=[0.03, 0.4, 0.5],
        bounds_lower=[0, 0, 0],
        bounds_upper=[np.inf, 5, 5],
        latex_template=r"k_La = {c0} \left(\frac{{P}}{{V}}\right)^{{{c1}}} v_s^{{{c2}}}",
        description="Classic Van 't Riet power-law form. Requires P/V and vₛ data.",
    ),
    PowerLaw2(
        id="kla_eps_vs",
        param="kla_sparged",
        name="kLa = A·ε^b·vₛ^c  (CFD dissipation form)",
        required_columns=["eps_kg", "v_s"],
        column_labels={"eps_kg": "Energy dissipation rate (W/kg)", "v_s": "Superficial gas velocity (m/s)"},
        n_coeffs=3,
        coeff_names=["A", "b", "c"],
        initial_guess=[0.03, 0.4, 0.5],
        bounds_lower=[0, 0, 0],
        bounds_upper=[np.inf, 5, 5],
        latex_template=r"k_La = {c0} \; \varepsilon^{{{c1}}} \; v_s^{{{c2}}}",
        description="Power-law using mass-specific energy dissipation from CFD.",
    ),
    PowerLaw1(
        id="kla_pv_only",
        param="kla_sparged",
        name="kLa = A·(P/V)^b  (surface aeration / no gas data)",
        required_columns=["P_V"],
        column_labels={"P_V": "Power per volume (W/m³)"},
        n_coeffs=2,
        coeff_names=["A", "b"],
        initial_guess=[0.01, 0.5],
        bounds_lower=[0, 0],
        bounds_upper=[np.inf, 5],
        latex_template=r"k_La = {c0} \left(\frac{{P}}{{V}}\right)^{{{c1}}}",
        description="Simple power-law for kLa without gas velocity data.",
    ),
    PowerLaw3(
        id="kla_pv_vs_mu",
        param="kla_sparged",
        name="kLa = A·(P/V)^b·vₛ^c·μ^d  (viscosity-corrected)",
        required_columns=["P_V", "v_s", "mu"],
        column_labels={
            "P_V": "Power per volume (W/m³)",
            "v_s": "Superficial gas velocity (m/s)",
            "mu": "Dynamic viscosity (Pa·s)",
        },
        n_coeffs=4,
        coeff_names=["A", "b", "c", "d"],
        initial_guess=[0.03, 0.4, 0.5, -0.3],
        bounds_lower=[0, 0, 0, -5],
        bounds_upper=[np.inf, 5, 5, 0],
        latex_template=r"k_La = {c0} \left(\frac{{P}}{{V}}\right)^{{{c1}}} v_s^{{{c2}}} \mu^{{{c3}}}",
        description="Viscosity-dependent extension of the Van 't Riet form.",
    ),

    # ── kLa (surface) ───────────────────────────────────────────────────
    PowerLaw1(
        id="kla_surf_eps",
        param="kla_surface",
        name="kLa_surf = A·ε^b  (dissipation only)",
        required_columns=["eps_kg"],
        column_labels={"eps_kg": "Mass-specific energy dissipation (W/kg)"},
        n_coeffs=2,
        coeff_names=["A", "b"],
        initial_guess=[0.4, 0.25],
        bounds_lower=[0, 0],
        bounds_upper=[np.inf, 5],
        latex_template=r"k_La_{{surf}} = {c0} \; \varepsilon^{{{c1}}}",
        description="Simple power-law surface-aeration kLa fit. Does not account for fill volume.",
    ),
    PowerLaw2(
        id="kla_surf_eps_vl",
        param="kla_surface",
        name="kLa_surf = A·ε^b·V_L^c  (dissipation + volume)",
        required_columns=["eps_kg", "V_L"],
        column_labels={
            "eps_kg": "Mass-specific energy dissipation (W/kg)",
            "V_L": "Liquid fill volume (L)",
        },
        n_coeffs=3,
        coeff_names=["A", "b", "c"],
        initial_guess=[0.4, 0.25, -0.5],
        bounds_lower=[0, 0, -5],
        bounds_upper=[np.inf, 5, 5],
        latex_template=r"k_La_{{surf}} = {c0} \; \varepsilon^{{{c1}}} \; V_L^{{{c2}}}",
        description=(
            "Surface-aeration kLa with volume dependence. The exponent c captures "
            "the change in surface-to-volume ratio with fill level. Expect c < 0 "
            "(kLa decreases as volume increases at constant ε)."
        ),
    ),
    PowerLaw2(
        id="kla_surf_pv_vl",
        param="kla_surface",
        name="kLa_surf = A·(P/V)^b·V_L^c  (power/volume + volume)",
        required_columns=["P_V", "V_L"],
        column_labels={
            "P_V": "Power per unit volume (W/m³)",
            "V_L": "Liquid fill volume (L)",
        },
        n_coeffs=3,
        coeff_names=["A", "b", "c"],
        initial_guess=[0.01, 0.4, -0.5],
        bounds_lower=[0, 0, -5],
        bounds_upper=[np.inf, 5, 5],
        latex_template=r"k_La_{{surf}} = {c0} \left(\frac{{P}}{{V}}\right)^{{{c1}}} V_L^{{{c2}}}",
        description=(
            "Surface kLa using P/V and fill volume. Useful when dissipation rate "
            "is not available from CFD."
        ),
    ),
    PowerLaw3(
        id="kla_surf_n_d_vl",
        param="kla_surface",
        name="kLa_surf = A·N^b·D^c·V_L^d  (speed + geometry + volume)",
        required_columns=["N", "D_imp", "V_L"],
        column_labels={
            "N": "Impeller speed (rev/s)",
            "D_imp": "Impeller diameter (m)",
            "V_L": "Liquid fill volume (L)",
        },
        n_coeffs=4,
        coeff_names=["A", "b", "c", "d"],
        initial_guess=[0.01, 1.5, 2.0, -0.5],
        bounds_lower=[0, 0, -5, -5],
        bounds_upper=[np.inf, 5, 5, 5],
        latex_template=r"k_La_{{surf}} = {c0} \; N^{{{c1}}} \; D^{{{c2}}} \; V_L^{{{c3}}}",
        description=(
            "Direct fit to impeller speed, diameter, and fill volume. "
            "Avoids intermediate quantities like P/V or ε. "
            "Useful for lab-scale reactors with known geometry."
        ),
    ),
    PowerLaw2(
        id="kla_surf_re_vl",
        param="kla_surface",
        name="kLa_surf = A·Re^b·V_L^c  (Reynolds + volume)",
        required_columns=["Re", "V_L"],
        column_labels={
            "Re": "Impeller Reynolds number",
            "V_L": "Liquid fill volume (L)",
        },
        n_coeffs=3,
        coeff_names=["A", "b", "c"],
        initial_guess=[1e-4, 0.7, -0.5],
        bounds_lower=[0, 0, -5],
        bounds_upper=[np.inf, 5, 5],
        latex_template=r"k_La_{{surf}} = {c0} \; Re^{{{c1}}} \; V_L^{{{c2}}}",
        description=(
            "Dimensionless-style correlation using impeller Re and fill volume. "
            "Re captures the combined effect of speed, diameter, and viscosity."
        ),
    ),
    PowerLaw1(
        id="kla_surf_n",
        param="kla_surface",
        name="kLa_surf = A·N^b  (speed only)",
        required_columns=["N"],
        column_labels={"N": "Impeller speed (rev/s)"},
        n_coeffs=2,
        coeff_names=["A", "b"],
        initial_guess=[0.01, 1.5],
        bounds_lower=[0, 0],
        bounds_upper=[np.inf, 5],
        latex_template=r"k_La_{{surf}} = {c0} \; N^{{{c1}}}",
        description=(
            "Minimal model for fixed-geometry, single-volume experiments. "
            "Only valid at the geometry and fill volume used for fitting."
        ),
    ),
    PowerLaw2(
        id="kla_surf_n_vl",
        param="kla_surface",
        name="kLa_surf = A·N^b·V_L^c  (speed + volume)",
        required_columns=["N", "V_L"],
        column_labels={
            "N": "Impeller speed (rev/s)",
            "V_L": "Liquid fill volume (L)",
        },
        n_coeffs=3,
        coeff_names=["A", "b", "c"],
        initial_guess=[0.01, 1.5, -0.5],
        bounds_lower=[0, 0, -5],
        bounds_upper=[np.inf, 5, 5],
        latex_template=r"k_La_{{surf}} = {c0} \; N^{{{c1}}} \; V_L^{{{c2}}}",
        description=(
            "Speed and fill volume power-law. Good for lab reactors where "
            "geometry is fixed but volume varies. Expect c ≈ −0.5 to −1 "
            "reflecting the surface-to-volume ratio."
        ),
    ),

    # ── Blend time ───────────────────────────────────────────────────────
    PowerLaw3(
        id="blend_re_vl_nd2",
        param="blend_time",
        name="θ₉₅ = A·Re^b·V_L^c·(N·D²)^d",
        required_columns=["Re", "V_L", "ND2"],
        column_labels={
            "Re": "Impeller Reynolds number",
            "V_L": "Liquid volume (L)",
            "ND2": "Impeller speed × diameter squared, N·D² (m²/s)",
        },
        n_coeffs=4,
        coeff_names=["A", "b", "c", "d"],
        initial_guess=[0.08, -0.08, 0.36, -1.0],
        bounds_lower=[0, -5, -5, -5],
        bounds_upper=[np.inf, 5, 5, 5],
        latex_template=r"\theta_{{95}} = {c0} \; Re^{{{c1}}} \; V_L^{{{c2}}} \; (N D^2)^{{{c3}}}",
        description="CFD-style blend time with Reynolds number and volume dependence.",
    ),
    PowerLaw2(
        id="blend_nd2_vl",
        param="blend_time",
        name="θ₉₅ = A·(N·D²)^b·V_L^c  (simplified)",
        required_columns=["ND2", "V_L"],
        column_labels={
            "ND2": "Impeller speed × diameter squared, N·D² (m²/s)",
            "V_L": "Liquid volume (L)",
        },
        n_coeffs=3,
        coeff_names=["A", "b", "c"],
        initial_guess=[1.0, -1.0, 0.33],
        bounds_lower=[0, -5, -5],
        bounds_upper=[np.inf, 5, 5],
        latex_template=r"\theta_{{95}} = {c0} \; (N D^2)^{{{c1}}} \; V_L^{{{c2}}}",
        description="Simplified blend time correlation.",
    ),
    PowerLaw1(
        id="blend_eps",
        param="blend_time",
        name="θ₉₅ = A·ε^b  (dissipation-based)",
        required_columns=["eps_kg"],
        column_labels={"eps_kg": "Mass-specific energy dissipation (W/kg)"},
        n_coeffs=2,
        coeff_names=["A", "b"],
        initial_guess=[10.0, -0.33],
        bounds_lower=[0, -5],
        bounds_upper=[np.inf, 5],
        latex_template=r"\theta_{{95}} = {c0} \; \varepsilon^{{{c1}}}",
        description="Blend time as a function of dissipation rate.",
    ),

    # ── Power number ─────────────────────────────────────────────────────
    PowerLaw1(
        id="np_re",
        param="power_number",
        name="Np = A·Re^b  (transitional regime)",
        required_columns=["Re"],
        column_labels={"Re": "Impeller Reynolds number"},
        n_coeffs=2,
        coeff_names=["A", "b"],
        initial_guess=[5.0, -0.1],
        bounds_lower=[0, -5],
        bounds_upper=[np.inf, 5],
        latex_template=r"N_p = {c0} \; Re^{{{c1}}}",
        description="Power number fit for transitional/turbulent regime.",
    ),
    PowerLaw1Offset(
        id="np_re_offset",
        param="power_number",
        name="Np = A·Re^b + C  (laminar–turbulent)",
        required_columns=["Re"],
        column_labels={"Re": "Impeller Reynolds number"},
        n_coeffs=3,
        coeff_names=["A", "b", "C"],
        initial_guess=[70.0, -1.0, 0.5],
        bounds_lower=[0, -5, 0],
        bounds_upper=[np.inf, 0, 20],
        latex_template=r"N_p = {c0} \; Re^{{{c1}}} + {c2}",
        description="Power number with asymptotic turbulent plateau C.",
        log_transform=False,
    ),

    # ── ε_max (local maximum dissipation) ────────────────────────────────
    PowerLaw1(
        id="eps_max_pv",
        param="epsilon_max",
        name="ε_max = A·(P/V)^b",
        required_columns=["P_V"],
        column_labels={"P_V": "Power per volume (W/m³)"},
        n_coeffs=2,
        coeff_names=["A", "b"],
        initial_guess=[3.0, 1.0],
        bounds_lower=[0, 0],
        bounds_upper=[np.inf, 5],
        latex_template=r"\varepsilon_{{max}} = {c0} \left(\frac{{P}}{{V}}\right)^{{{c1}}}",
        description="Local maximum dissipation vs. average P/V.",
    ),
    PowerLaw2(
        id="eps_max_n_d",
        param="epsilon_max",
        name="ε_max = A·N^b·D^c  (speed–diameter form)",
        required_columns=["N", "D_imp"],
        column_labels={"N": "Impeller speed (rev/s)", "D_imp": "Impeller diameter (m)"},
        n_coeffs=3,
        coeff_names=["A", "b", "c"],
        initial_guess=[1.0, 3.0, 2.0],
        bounds_lower=[0, 0, -5],
        bounds_upper=[np.inf, 10, 10],
        latex_template=r"\varepsilon_{{max}} = {c0} \; N^{{{c1}}} \; D^{{{c2}}}",
        description="Direct fit to impeller speed and diameter.",
    ),

    # ── Micromixing time ─────────────────────────────────────────────────
    PowerLaw2(
        id="tmicro_nu_eps",
        param="micromixing_time",
        name="t_E = A·(ν/ε)^b  (Engulfment form)",
        required_columns=["nu_over_eps"],
        column_labels={"nu_over_eps": "ν/ε (s)"},
        n_coeffs=2,
        coeff_names=["A", "b"],
        initial_guess=[17.3, 0.5],
        bounds_lower=[0, 0],
        bounds_upper=[np.inf, 5],
        latex_template=r"t_E = {c0} \left(\frac{{\nu}}{{\varepsilon}}\right)^{{{c1}}}",
        description="Generalised engulfment model with fitted prefactor and exponent.",
    ),
    PowerLaw1(
        id="tmicro_eps",
        param="micromixing_time",
        name="t_E = A·ε^b  (simplified)",
        required_columns=["eps_kg"],
        column_labels={"eps_kg": "Mass-specific dissipation (W/kg)"},
        n_coeffs=2,
        coeff_names=["A", "b"],
        initial_guess=[1.0, -0.5],
        bounds_lower=[0, -5],
        bounds_upper=[np.inf, 0],
        latex_template=r"t_E = {c0} \; \varepsilon^{{{c1}}}",
        description="Simplified micromixing time as power-law in ε.",
    ),
]

# Micromixing template using nu_over_eps is actually a PowerLaw1 form
# (single independent variable), fix the class:
# Replace the tmicro_nu_eps entry
_tmicro_idx = next(i for i, t in enumerate(TEMPLATES) if t.id == "tmicro_nu_eps")
TEMPLATES[_tmicro_idx] = PowerLaw1(
    id="tmicro_nu_eps",
    param="micromixing_time",
    name="t_E = A·(ν/ε)^b  (Engulfment form)",
    required_columns=["nu_over_eps"],
    column_labels={"nu_over_eps": "ν/ε (s)"},
    n_coeffs=2,
    coeff_names=["A", "b"],
    initial_guess=[17.3, 0.5],
    bounds_lower=[0, 0],
    bounds_upper=[np.inf, 5],
    latex_template=r"t_E = {c0} \left(\frac{{\nu}}{{\varepsilon}}\right)^{{{c1}}}",
    description="Generalised engulfment model with fitted prefactor and exponent.",
)


# ═══════════════════════════════════════════════════════════════════════════
#  Lookup helpers
# ═══════════════════════════════════════════════════════════════════════════

def templates_for_param(param: str) -> list[CorrTemplate]:
    """Return all templates targeting *param*."""
    return [t for t in TEMPLATES if t.param == param]


def compatible_templates(param: str, available_columns: set[str]) -> list[CorrTemplate]:
    """Return templates whose required columns are all present."""
    return [
        t for t in templates_for_param(param)
        if set(t.required_columns).issubset(available_columns)
    ]


def template_by_id(tid: str) -> CorrTemplate | None:
    """Look up a template by its ``id`` string."""
    for t in TEMPLATES:
        if t.id == tid:
            return t
    return None
