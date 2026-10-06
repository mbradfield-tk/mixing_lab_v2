"""Solvent property curves across the liquid range."""
from __future__ import annotations

import numpy as np

from utils.solvent_properties import (
    SOLVENT_DB,
    boiling_point_at_pressure,
    density,
    diffusivity,
    specific_heat,
    surface_tension,
    thermal_conductivity,
    viscosity,
)

PROPERTY_CURVES = (
    ("Density ρ (kg/m³)", density),
    ("Viscosity μ (Pa·s)", viscosity),
    ("Surface tension σ (N/m)", surface_tension),
    ("Diffusivity D (m²/s)", diffusivity),
    ("Specific heat Cp (J/kg·K)", specific_heat),
    ("Thermal conductivity k (W/m·K)", thermal_conductivity),
)


def property_curves(name: str, P_atm: float, n_pts: int = 200) -> dict:
    """{T (°C, melting point to boiling point at P), series: [(title, values), ...]}."""
    sd = SOLVENT_DB[name]
    T = np.linspace(sd.mp_C, boiling_point_at_pressure(P_atm, sd), n_pts)
    return {"T": T, "series": [(title, [fn(t, sd) for t in T]) for title, fn in PROPERTY_CURVES]}
