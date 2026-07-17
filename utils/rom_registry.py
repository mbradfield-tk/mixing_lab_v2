"""Reduced Order Model (ROM) and Experimental Correlation Registry.

Stores reactor-specific correlations that can override literature
correlations for mixing parameters (blend time, kLa, micromixing
time, etc.).

Usage
-----
1. Register correlations using ``register()``.
2. Query available modes for a reactor with ``available_modes()``.
3. Compute hydro parameters using ``compute_reactor_hydro_with_mode()``.
   In "Literature" mode it delegates to the standard function;
   in "ROM" or "Experimental" mode it overrides parameters that have
   a matching registration.
"""

from __future__ import annotations

import numpy as np
from dataclasses import dataclass, field
from typing import Callable

from utils.calculations import (
    compute_reactor_hydro,
    compute_damkohler_numbers,
    blend_time_turbulent,
    micromixing_time_engulfment,
    micromixing_time_local,
    kla_vant_riet,
    kla_surface,
    power_number_correlation,
    epsilon_max_estimate,
    impeller_power,
    power_per_volume,
    kolmogorov_length,
    average_shear_rate,
    maximum_shear_rate,
    shear_stress,
    tip_speed,
    pumping_rate,
    reynolds_number,
    circulation_time,
    torque,
    torque_per_volume,
    edcf,
    froude_number,
)


# ═══════════════════════════════════════════════════════════════════════════
# Data structures
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class Correlation:
    """A single reactor-specific correlation."""

    name: str
    """Human-readable name, e.g. 'Blend time – CFD power-law'."""

    param: str
    """Parameter key that this correlation computes.
    Must be one of SUPPORTED_PARAMS."""

    corr_type: str
    """'ROM' or 'Experimental'."""

    func: Callable[..., float]
    """Callable that receives **kwargs of operating conditions and returns
    the computed value.  All registered kwargs are passed; the function
    should accept **kwargs and pick out what it needs."""

    latex: str
    """LaTeX string for display on equation pages (raw, no $ delimiters)."""

    source: str
    """Citation or short description of the model origin."""

    description: str = ""
    """Optional longer description shown in equation-page expanders."""

    input_params: dict[str, str] = field(default_factory=dict)
    """Mapping of input-parameter name → description for documentation."""


# Parameters that can be overridden by ROMs / experimental correlations.
SUPPORTED_PARAMS: list[str] = [
    "blend_time",
    "micromixing_time",
    "kla_sparged",
    "kla_surface",
    "power_number",
    "epsilon_max",
]

# Friendly display names used in UI / equations pages.
PARAM_DISPLAY: dict[str, str] = {
    "blend_time": "Blend time θ₉₅ (s)",
    "micromixing_time": "Engulfment micromixing time t_E (s)",
    "kla_sparged": "Sparged kLa (1/s)",
    "kla_surface": "Surface kLa (1/s)",
    "power_number": "Power number Np",
    "epsilon_max": "Maximum local energy dissipation ε_max (W/kg)",
}


# ═══════════════════════════════════════════════════════════════════════════
# Registry
# ═══════════════════════════════════════════════════════════════════════════

# reactor_name → list[Correlation]
_REGISTRY: dict[str, list[Correlation]] = {}


def register(reactor_name: str, corr: Correlation) -> None:
    """Register a correlation for *reactor_name*."""
    if corr.param not in SUPPORTED_PARAMS:
        raise ValueError(
            f"Unknown param '{corr.param}'. Must be one of {SUPPORTED_PARAMS}"
        )
    if corr.corr_type not in ("ROM", "Experimental"):
        raise ValueError("corr_type must be 'ROM' or 'Experimental'")
    _REGISTRY.setdefault(reactor_name, []).append(corr)


def get_correlations(
    reactor_name: str,
    param: str | None = None,
    corr_type: str | None = None,
) -> list[Correlation]:
    """Return registered correlations, optionally filtered."""
    corrs = _REGISTRY.get(reactor_name, [])
    if param is not None:
        corrs = [c for c in corrs if c.param == param]
    if corr_type is not None:
        corrs = [c for c in corrs if c.corr_type == corr_type]
    return corrs


def available_modes(reactor_name: str) -> list[str]:
    """Return available correlation modes for *reactor_name*.

    Always includes ``'Literature'``; adds ``'ROM'`` and/or
    ``'Experimental'`` if at least one correlation of that type is
    registered.
    """
    modes = ["Literature"]
    corrs = _REGISTRY.get(reactor_name, [])
    types = {c.corr_type for c in corrs}
    if "ROM" in types:
        modes.append("ROM")
    if "Experimental" in types:
        modes.append("Experimental")
    return modes


def available_modes_multi(reactor_names: list[str]) -> list[str]:
    """Return the *intersection* of available modes across multiple reactors.

    Used on the comparison page where all reactors must support the
    chosen mode.
    """
    if not reactor_names:
        return ["Literature"]
    sets = [set(available_modes(n)) for n in reactor_names]
    common = sets[0]
    for s in sets[1:]:
        common &= s
    # Keep deterministic order
    ordered = []
    for m in ("Literature", "ROM", "Experimental"):
        if m in common:
            ordered.append(m)
    return ordered or ["Literature"]


def get_all_registered_reactors() -> list[str]:
    """Return a list of reactor names that have any correlations registered."""
    return list(_REGISTRY.keys())


def get_all_correlations() -> dict[str, list[Correlation]]:
    """Return the full registry (read-only view)."""
    return dict(_REGISTRY)


def available_param_modes(reactor_name: str) -> dict[str, list[str]]:
    """Return, per supported parameter, a list of available modes.

    Always includes ``'Literature'``.  Adds ``'ROM'`` / ``'Experimental'``
    if a matching correlation is registered for that parameter.

    Returns
    -------
    dict[str, list[str]]
        e.g. ``{'blend_time': ['Literature', 'ROM'], ...}``
    """
    corrs = _REGISTRY.get(reactor_name, [])
    result: dict[str, list[str]] = {}
    for p in SUPPORTED_PARAMS:
        modes = ["Literature"]
        types = {c.corr_type for c in corrs if c.param == p}
        if "ROM" in types:
            modes.append("ROM")
        if "Experimental" in types:
            modes.append("Experimental")
        result[p] = modes
    return result


def has_any_alt_correlations(reactor_name: str) -> bool:
    """True if *reactor_name* has at least one ROM or Experimental correlation."""
    return len(_REGISTRY.get(reactor_name, [])) > 0


# ═══════════════════════════════════════════════════════════════════════════
# Compute with mode
# ═══════════════════════════════════════════════════════════════════════════

def _build_kwargs(
    N, D_imp, D_tank, H, rho, mu, V, nu, Re, P, eps, eps_kg,
    Np, Nq, v_s, D_mol, coalescing,
) -> dict:
    """Assemble a broad kwargs dict so ROM functions can pick what they need."""
    return dict(
        N=N, D_imp=D_imp, D_tank=D_tank, H=H,
        rho=rho, mu=mu, nu=nu, Re=Re,
        V=V, V_L=V * 1000,  # m³ and litres
        P=P, P_V=eps, eps=eps_kg, eps_kg=eps_kg,  # P_V is W/m³; eps/eps_kg are W/kg
        Np=Np, Nq=Nq,
        v_s=v_s, D_mol=D_mol,
        coalescing=coalescing,
    )


def compute_reactor_hydro_with_mode(
    mode: str | dict[str, str],
    reactor_name: str,
    *,
    N: float,
    D_imp: float,
    D_tank: float,
    H: float,
    rho: float,
    mu: float,
    Np: float = None,
    Nq: float = None,
    v_s: float = 0.0,
    coalescing: bool = True,
    D_mol: float = 2.3e-9,
) -> tuple[dict, dict[str, str]]:
    """Compute hydrodynamic parameters using selected correlation mode(s).

    Parameters
    ----------
    mode : str or dict[str, str]
        Either a single mode string (``'Literature'``, ``'ROM'``, or
        ``'Experimental'``) applied to all parameters, **or** a dict
        mapping each parameter key (e.g. ``'blend_time'``) to its
        chosen mode.  Parameters absent from the dict default to
        ``'Literature'``.

    Returns
    -------
    hydro : dict
        The same dictionary structure as ``compute_reactor_hydro``.
    sources : dict[str, str]
        Mapping of parameter name → source description for each value
        that was overridden by a ROM/Experimental correlation.
    """
    # Normalise to a per-param dict
    if isinstance(mode, str):
        param_modes: dict[str, str] = {p: mode for p in SUPPORTED_PARAMS}
    else:
        param_modes = {p: mode.get(p, "Literature") for p in SUPPORTED_PARAMS}

    # --- Basics ---
    V = np.pi / 4 * D_tank**2 * H
    nu = mu / rho if rho > 0 else 0.0
    Re = reynolds_number(N, D_imp, rho, mu) if mu > 0 else 0.0

    if Np is None or (isinstance(Np, float) and np.isnan(Np)):
        Np_val = power_number_correlation(Re)
    else:
        Np_val = Np
    if Nq is None or (isinstance(Nq, float) and np.isnan(Nq)):
        from utils.calculations import pumping_number_default
        Nq_val = pumping_number_default()
    else:
        Nq_val = Nq

    # Fast path: if every param is Literature, delegate entirely
    if all(m == "Literature" for m in param_modes.values()):
        hydro = compute_reactor_hydro(
            N=N, D_imp=D_imp, D_tank=D_tank, H=H,
            rho=rho, mu=mu, Np=Np, Nq=Nq,
            v_s=v_s, coalescing=coalescing, D_mol=D_mol,
        )
        return hydro, {}

    sources: dict[str, str] = {}

    # Pre-build correlation lookup: param → Correlation (or None)
    # This avoids repeated get_correlations() calls in hot loops.
    _corr_cache: dict[str, Correlation | None] = {}
    for p in SUPPORTED_PARAMS:
        m = param_modes.get(p, "Literature")
        if m == "Literature":
            _corr_cache[p] = None
        else:
            corrs = get_correlations(reactor_name, param=p, corr_type=m)
            _corr_cache[p] = corrs[0] if corrs else None

    P = impeller_power(Np_val, rho, N, D_imp)
    eps = power_per_volume(P, V) if V > 0 else 0.0
    eps_kg = eps / rho if rho > 0 else 0.0

    kw = _build_kwargs(N, D_imp, D_tank, H, rho, mu, V, nu, Re, P, eps, eps_kg,
                        Np_val, Nq_val, v_s, D_mol, coalescing)

    # -- Power number --
    c = _corr_cache["power_number"]
    if c:
        Np_val = c.func(**kw)
        sources["power_number"] = c.name
        P = impeller_power(Np_val, rho, N, D_imp)
        eps = power_per_volume(P, V) if V > 0 else 0.0
        eps_kg = eps / rho if rho > 0 else 0.0
        kw.update(Np=Np_val, P=P, P_V=eps, eps=eps_kg, eps_kg=eps_kg)

    # -- Blend time --
    c = _corr_cache["blend_time"]
    if c:
        t_blend = c.func(**kw)
        sources["blend_time"] = c.name
    else:
        t_blend = blend_time_turbulent(Nq_val, V, D_imp, N)

    # -- eps_max --
    c = _corr_cache["epsilon_max"]
    if c:
        eps_max_val = c.func(**kw)
        sources["epsilon_max"] = c.name
    else:
        eps_max_val = epsilon_max_estimate(P, rho, D_imp, N)

    # -- Micromixing time --
    c = _corr_cache["micromixing_time"]
    if c:
        t_micro = c.func(**kw)
        sources["micromixing_time"] = c.name
    else:
        t_micro = micromixing_time_engulfment(eps_kg, nu)

    # -- kLa sparged --
    c = _corr_cache["kla_sparged"]
    if c:
        kla = c.func(**kw)
        sources["kla_sparged"] = c.name
    else:
        kla = kla_vant_riet(eps, v_s, coalescing=coalescing)

    # -- kLa surface --
    c = _corr_cache["kla_surface"]
    if c:
        kla_surf = c.func(**kw)
        sources["kla_surface"] = c.name
    else:
        kla_surf = kla_surface(eps_kg, nu, D_mol, D_tank, V)

    # -- Remaining literature calculations (always) --
    eta = kolmogorov_length(nu, eps_kg)
    u_tip = tip_speed(N, D_imp)
    Q = pumping_rate(Nq_val, N, D_imp)
    t_micro_local = micromixing_time_local(eps_max_val, nu)
    gamma_avg = average_shear_rate(P, mu, V)
    gamma_max = maximum_shear_rate(eps_max_val, nu)
    tau_avg = shear_stress(mu, gamma_avg)
    t_c = circulation_time(Nq_val, V, D_imp, N)
    _torque = torque(P, N)
    _torque_per_vol = torque_per_volume(P, N, V)
    _edcf = edcf(eps_max_val, t_c)
    Fr = froude_number(N, D_imp)

    hydro = {
        "Volume (L)": V * 1000,
        "Re": Re,
        "Np": Np_val,
        "Power (W)": P,
        "P/V (W/m³)": eps,
        "P/V (W/kg)": eps_kg,
        "P/V (W/L)": eps / 1000,
        "Tip speed (m/s)": u_tip,
        "Pumping rate (m³/s)": Q,
        "Blend time 95% (s)": t_blend,
        "Circulation time (s)": t_c,
        "Micromix time t_E (s)": t_micro,
        "Micromix time t_E_local (s)": t_micro_local,
        "Kolmogorov η (µm)": eta * 1e6,
        "ε_max (W/kg)": eps_max_val,
        "EDCF (W/kg/s)": _edcf,
        "Torque (N·m)": _torque,
        "Torque/V (N·m/m³)": _torque_per_vol,
        "Froude number": Fr,
        "Avg shear rate (1/s)": gamma_avg,
        "Max shear rate (1/s)": gamma_max,
        "Avg shear stress (Pa)": tau_avg,
        "kLa (1/s)": kla,
        "kLa_surface (1/s)": kla_surf,
        "ν (m²/s)": nu,
    }
    return hydro, sources


# ═══════════════════════════════════════════════════════════════════════════
# Dummy ROM registrations – "Nalas – EasyMax 102"
# ═══════════════════════════════════════════════════════════════════════════
# These demonstrate the system.  Replace or augment with real fits.

_DEMO_REACTOR = "Nalas – EasyMax 102"


def _demo_blend_time(**kw) -> float:
    r"""CFD-fitted blend time for EasyMax 102.

    θ95 = 0.08 · Re^{-0.08} · V_L^{0.36} / (N · D²)

    Includes a weak viscosity dependence (via Re) not captured by
    the Grenville literature correlation.
    V_L in litres, N in rev/s, D in m.
    """
    N = kw["N"]
    D = kw["D_imp"]
    V_L = kw.get("V_L", kw.get("V", 0) * 1000)
    Re = kw.get("Re", kw["rho"] * N * D**2 / kw["mu"])
    denom = N * D**2
    if denom == 0 or Re <= 0:
        return 0.0
    return 0.08 * Re**(-0.08) * V_L**0.36 / denom


register(_DEMO_REACTOR, Correlation(
    name="Blend time – CFD power-law (EasyMax 102)",
    param="blend_time",
    corr_type="ROM",
    func=_demo_blend_time,
    latex=r"\theta_{95} = 0.08 \; Re^{-0.08} \; V_L^{\,0.36} \; (N \, D^2)^{-1}",
    source="Internal CFD parametric study (2025), Nalas R&D.",
    description=(
        "Power-law fit to 48-case RANS CFD sweep over the EasyMax 102 "
        "geometry.  Includes a weak viscosity dependence (via Re) not "
        "captured by the standard Grenville correlation.  Valid for "
        "0.02 – 0.10 L, 100 – 800 RPM, water-like fluids (Re > 5 000)."
    ),
    input_params={
        "V_L": "Liquid volume (L)",
        "N": "Impeller speed (rev/s)",
        "D_imp": "Impeller diameter (m)",
        "Re": "Impeller Reynolds number",
    },
))


def _demo_kla(**kw) -> float:
    r"""Experimentally fitted kLa for EasyMax 102.

    kLa = 0.032 · (P/V)^0.45 · v_s^0.55

    P/V in W/m³, v_s in m/s.
    """
    P_V = kw.get("P_V", kw.get("eps", 0.0))
    v_s = kw.get("v_s", 0.0)
    if v_s <= 0 or P_V <= 0:
        return 0.0
    return 0.032 * P_V**0.45 * v_s**0.55


register(_DEMO_REACTOR, Correlation(
    name="kLa – Experimental fit (EasyMax 102)",
    param="kla_sparged",
    corr_type="Experimental",
    func=_demo_kla,
    latex=r"k_L a = 0.032 \; \left(\frac{P}{V}\right)^{0.45} v_s^{\,0.55}",
    source="O₂ transfer experiments, Nalas lab (2024).",
    description=(
        "Fit to dynamic gassing-out O₂ transfer measurements in the "
        "EasyMax 102 (water, 20 °C).  Valid for P/V = 50 – 2000 W/m³, "
        "v_s = 0.001 – 0.03 m/s."
    ),
    input_params={
        "P_V": "Power per unit volume (W/m³)",
        "v_s": "Superficial gas velocity (m/s)",
    },
))


def _demo_micromixing(**kw) -> float:
    r"""CFD-fitted micromixing time for EasyMax 102.

    t_E = 12.5 · (ν / ε)^0.48

    ε in W/kg, ν in m²/s.
    """
    nu = kw.get("nu", 1e-6)
    eps_kg = kw.get("eps_kg", 1.0)
    if eps_kg <= 0:
        return 0.0
    return 12.5 * (nu / eps_kg) ** 0.48


register(_DEMO_REACTOR, Correlation(
    name="Micromixing time – CFD fitted (EasyMax 102)",
    param="micromixing_time",
    corr_type="ROM",
    func=_demo_micromixing,
    latex=r"t_E = 12.5 \left(\frac{\nu}{\varepsilon}\right)^{0.48}",
    source="LES iodide-iodate simulations, Nalas R&D (2025).",
    description=(
        "Engulfment time derived from LES simulations of the Villermaux-"
        "Dushman (iodide-iodate) reaction in the EasyMax 102.  Valid for "
        "Re > 5 000, water-like viscosity."
    ),
    input_params={
        "nu": "Kinematic viscosity (m²/s)",
        "eps_kg": "Mass-specific energy dissipation rate (W/kg)",
    },
))


# ═══════════════════════════════════════════════════════════════════════════
# Auto-load saved fitted correlations from JSON
# ═══════════════════════════════════════════════════════════════════════════

_saved_correlations_loaded = False


def _load_saved_correlations() -> None:
    """Load fitted correlations persisted by the ROM Fitting page."""
    global _saved_correlations_loaded
    if _saved_correlations_loaded:
        return
    _saved_correlations_loaded = True

    import json
    import pathlib

    saved_file = (
        pathlib.Path(__file__).resolve().parent.parent
        / "data" / "fitted_correlations.json"
    )
    if not saved_file.exists():
        return

    # Late import to avoid circular dependency
    from utils.rom_templates import template_by_id

    try:
        with open(saved_file, "r") as f:
            entries = json.load(f)
    except (json.JSONDecodeError, OSError):
        return

    for entry in entries:
        tmpl = template_by_id(entry.get("template_id", ""))
        if tmpl is None:
            continue
        coeffs = np.array(entry["coeffs"])
        func = tmpl.build_func(coeffs)
        latex = tmpl.latex_filled(coeffs)
        register(
            entry["reactor_name"],
            Correlation(
                name=entry["name"],
                param=entry["param"],
                corr_type=entry["corr_type"],
                func=func,
                latex=latex,
                source=entry.get("source", "Fitted in Mixing Lab"),
                description=entry.get("description", ""),
                input_params=tmpl.column_labels,
            ),
        )


_load_saved_correlations()
