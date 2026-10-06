"""Database-row access, value coercion and vessel geometry shared by all pages."""
from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

import numpy as np
import pandas as pd

from core.csv_store import fresh_csv
from utils.calculations import liquid_height_from_volume
from utils.solvent_properties import get_properties, is_known_solvent, resolve_solvent_name

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
REACTORS_CSV = DATA_DIR / "reactors.csv"
REACTIONS_CSV = DATA_DIR / "reactions.csv"
PARTICLES_CSV = DATA_DIR / "particles.csv"
FLUIDS_CSV = DATA_DIR / "fluids.csv"

DEFAULT_FLUID = {"rho": 1000.0, "mu": 0.001, "D_mol": 2.3e-9, "sigma": 0.072}


def sf(val, default: float = 0.0) -> float:
    """Safe float conversion (NaN / blank / non-numeric -> default)."""
    try:
        f = float(val)
        return default if np.isnan(f) else f
    except (TypeError, ValueError):
        return default


def range_midpoint(row: pd.Series, min_key: str, max_key: str, fallback: float) -> float:
    """Midpoint of a min/max range, else whichever positive bound exists, else fallback."""
    lo = sf(row.get(min_key), 0.0)
    hi = sf(row.get(max_key), 0.0)
    if lo > 0 and hi > 0:
        return (lo + hi) / 2.0
    if hi > 0:
        return hi
    if lo > 0:
        return lo
    return fallback


def _lookup(path: Path, key: str, name) -> pd.Series:
    df = fresh_csv(path, [key])
    row = df[df[key].astype(str) == str(name)]
    return row.iloc[0] if not row.empty else pd.Series(dtype=object)


def reactor_row(name: str) -> pd.Series:
    return _lookup(REACTORS_CSV, "reactor_name", name)


def reaction_row(name: str) -> pd.Series:
    return _lookup(REACTIONS_CSV, "reaction_name", name)


def particle_row(name: str) -> pd.Series:
    return _lookup(PARTICLES_CSV, "particle_name", name)


def fluid_row(name: str) -> pd.Series:
    return _lookup(FLUIDS_CSV, "fluid_name", name)


def reactor_id(name: str) -> str:
    row = reactor_row(name)
    return "" if row.empty else str(row.get("reactor_id", "") or "")


def fluid_props(name: str, T_C: float, P_atm: float = 1.0) -> dict:
    """{rho, mu, D_mol, sigma, in_range, note} for a library solvent at (T, P) or a custom fluid."""
    if is_known_solvent(name):
        p = get_properties(resolve_solvent_name(name) or name, T_C, P_atm)
        in_range = p.get("in_range", True)
        note = "" if in_range else (
            f"⚠️ {T_C:.1f} °C is outside the liquid range "
            f"({p.get('mp_C', 0):.0f} – {p.get('bp_at_P_C', 0):.0f} °C) for {name}.")
        return {"rho": p["rho_kg_m3"], "mu": p["mu_Pa_s"], "D_mol": p["D_mol_m2_s"],
                "sigma": p["surface_tension_N_m"], "in_range": in_range, "note": note}
    row = fluid_row(name)
    if not row.empty:
        return {"rho": sf(row.get("rho_kg_m3"), DEFAULT_FLUID["rho"]),
                "mu": sf(row.get("mu_Pa_s"), DEFAULT_FLUID["mu"]),
                "D_mol": sf(row.get("D_mol_m2_s"), DEFAULT_FLUID["D_mol"]),
                "sigma": sf(row.get("surface_tension_N_m"), DEFAULT_FLUID["sigma"]),
                "in_range": True, "note": "Custom fluid — fixed properties."}
    return {**DEFAULT_FLUID, "in_range": True, "note": ""}


def solvent_props(solvent: str, T_C: float) -> dict | None:
    """Library solvent property dict at T (None when the name is not in the library)."""
    if not solvent or not is_known_solvent(solvent):
        return None
    try:
        return get_properties(resolve_solvent_name(solvent) or solvent, T_C, 1.0)
    except Exception:  # noqa: BLE001 - property library edge cases
        return None


def bottom_dish_height(row: pd.Series) -> float:
    """Measured bottom-dish height (m) for a reactor row, 0.0 when unknown.

    The CSV column is ``H_bot_dish_m``; the legacy ``H_bottom_dish_m`` spelling is
    still accepted, then ``H_max_m - L_tan_tan_m`` is used as a derived fallback.
    """
    for key in ("H_bot_dish_m", "H_bottom_dish_m"):
        h = sf(row.get(key))
        if h > 0:
            return h
    h_max, l_tt = sf(row.get("H_max_m")), sf(row.get("L_tan_tan_m"))
    return h_max - l_tt if h_max > 0 and l_tt > 0 and h_max > l_tt else 0.0


@dataclass(frozen=True)
class VesselGeometry:
    D_tank: float
    D_imp: float
    H_max: float
    Np: float
    Nq: float
    bottom_dish: str = ""
    bottom_dish_height: float = 0.0
    shell_material: str = ""
    lining_material: str = ""
    wall_thickness_mm: float = 0.0

    @classmethod
    def from_row(cls, row: pd.Series, *, H_max_fallback: float = 0.0,
                 Np_default: float = 1.27, Nq_default: float = 0.79) -> "VesselGeometry":
        # Tan-tan length only approximates the max fill height when H_max_m is missing.
        return cls(
            D_tank=sf(row.get("D_tank_m")), D_imp=sf(row.get("D_imp_m")),
            H_max=sf(row.get("H_max_m"), sf(row.get("L_tan_tan_m"), H_max_fallback)),
            Np=sf(row.get("Np"), Np_default), Nq=sf(row.get("Nq"), Nq_default),
            bottom_dish=str(row.get("bottom_dish", "") or ""),
            bottom_dish_height=bottom_dish_height(row),
            shell_material=str(row.get("shell_material", "") or ""),
            lining_material=str(row.get("lining_material", "") or ""),
            wall_thickness_mm=sf(row.get("wall_thickness_mm")),
        )

    def with_overrides(self, **values) -> "VesselGeometry":
        return replace(self, **values)

    def liquid_height(self, V_L: float) -> float:
        return liquid_height_from_volume(
            V_L, self.D_tank, self.H_max, self.bottom_dish, self.bottom_dish_height)
