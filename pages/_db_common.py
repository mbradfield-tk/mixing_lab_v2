"""Shared CRUD helpers for the database pages (Taipy).

Each database page (Vessels, Reactions, Particles, Fluids) is a self-contained
module that owns its state variables and handlers. To avoid duplicating the
load / save / edit / delete / import / export plumbing, that logic lives here as
pure functions operating on ``pandas`` DataFrames and CSV files. The per-page
modules provide thin handlers that call into these helpers.

Taipy table CRUD payloads
-------------------------
* ``on_edit(state, var, payload)``   -> payload ``{"index", "col", "value"}``
* ``on_delete(state, var, payload)`` -> payload ``{"index"}``
* ``on_add(state, var, payload)``    -> payload ``{"index"}`` (may be ``None``)

The ``index`` is the DataFrame index label. Pages keep a contiguous
``RangeIndex`` (via :func:`reset` after every mutation) so the label equals the
row position even after deletions.
"""
from __future__ import annotations

import os
import re
import tempfile
import threading
from pathlib import Path

import pandas as pd

# One lock guards all CSV I/O so concurrent sessions can't interleave writes;
# writes go to a temp file + os.replace so a crash never corrupts the database.
_io_lock = threading.Lock()
# fresh_csv cache: str(path) -> (mtime, DataFrame)
_fresh_cache: dict[str, tuple[float, pd.DataFrame]] = {}


def load_csv(path: Path, columns: list[str]) -> pd.DataFrame:
    """Load ``path`` if it exists, else return an empty frame with ``columns``."""
    if path.exists():
        return pd.read_csv(path).reset_index(drop=True)
    return pd.DataFrame(columns=columns)


def _atomic_write(df: pd.DataFrame, path: Path) -> None:
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.stem}_", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", newline="", encoding="utf-8") as fh:
            df.to_csv(fh, index=False)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    _fresh_cache.pop(str(path), None)


def save_csv(df: pd.DataFrame, path: Path) -> None:
    """Persist ``df`` to ``path`` atomically (lock-guarded temp file + replace)."""
    with _io_lock:
        _atomic_write(df, path)


def append_csv(new_df: pd.DataFrame, path: Path) -> int:
    """Append rows to a CSV atomically; returns the resulting row count."""
    with _io_lock:
        out = (pd.concat([pd.read_csv(path), new_df], ignore_index=True)
               if path.exists() else new_df)
        _atomic_write(out, path)
        return len(out)


def fresh_csv(path: Path, columns: list[str] | None = None) -> pd.DataFrame:
    """Latest contents of ``path``, re-read only when its mtime changes.

    Analysis pages resolve reactor/reaction/particle/fluid rows through this so
    edits made in the database pages are picked up without a server restart.
    The returned frame is shared across sessions — treat it as read-only.
    ``columns`` are guaranteed present (added empty when missing) so lookups
    never raise ``KeyError`` on a malformed or missing file.
    """
    key = str(path)
    with _io_lock:
        try:
            mtime = path.stat().st_mtime
        except OSError:
            return pd.DataFrame(columns=columns or [])
        cached = _fresh_cache.get(key)
        if cached is not None and cached[0] == mtime:
            for c in columns or []:
                if c not in cached[1].columns:
                    cached[1][c] = pd.NA
            return cached[1]
        try:
            df = pd.read_csv(path).reset_index(drop=True)
        except Exception:  # unreadable/half-synced file — keep serving the last good copy
            return cached[1] if cached is not None else pd.DataFrame(columns=columns or [])
        for c in columns or []:
            if c not in df.columns:
                df[c] = pd.NA
        _fresh_cache[key] = (mtime, df)
        return df


def csv_bytes(df: pd.DataFrame) -> bytes:
    """Return ``df`` encoded as UTF-8 CSV bytes (for file downloads)."""
    return df.to_csv(index=False).encode("utf-8")


def reset(df: pd.DataFrame) -> pd.DataFrame:
    """Return ``df`` with a fresh contiguous index."""
    return df.reset_index(drop=True)


def _coerce(df: pd.DataFrame, col: str, value):
    """Coerce ``value`` to the dtype of ``df[col]`` where sensible."""
    if col in df.columns and pd.api.types.is_numeric_dtype(df[col].dtype):
        try:
            return float(value)
        except (TypeError, ValueError):
            return value
    return value


def apply_edit(df: pd.DataFrame, payload: dict) -> pd.DataFrame:
    """Apply an inline table edit and return the updated frame."""
    idx = payload["index"]
    col = payload["col"]
    value = _coerce(df, col, payload["value"])
    df.at[idx, col] = value
    return df


def delete_row(df: pd.DataFrame, payload: dict) -> pd.DataFrame:
    """Delete the row identified by ``payload['index']``."""
    return reset(df.drop(index=payload["index"], errors="ignore"))


def add_blank(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    """Append a blank row (0.0 for numeric columns, "" otherwise)."""
    blank = {}
    for c in columns:
        is_num = c in df.columns and pd.api.types.is_numeric_dtype(df[c].dtype)
        blank[c] = 0.0 if is_num else ""
    return reset(pd.concat([df, pd.DataFrame([blank])], ignore_index=True))


def name_taken(df: pd.DataFrame, name_col: str, name: str) -> bool:
    """Return True if ``name`` already exists in ``df[name_col]`` (case-insensitive)."""
    if df.empty or name_col not in df.columns:
        return False
    existing = df[name_col].dropna().astype(str).str.strip().str.lower()
    return name.strip().lower() in set(existing)


def filter_rows(df: pd.DataFrame, query: str, columns: list[str] | None = None) -> pd.DataFrame:
    """Return rows where any cell contains ``query`` (case-insensitive).

    When ``columns`` is given, only those columns are searched (names not present
    in ``df`` are ignored).
    """
    q = (query or "").strip().lower()
    if not q:
        return df.copy()
    search_df = df
    if columns:
        present = [c for c in columns if c in df.columns]
        if present:
            search_df = df[present]
    mask = search_df.apply(
        lambda r: r.astype(str).str.lower().str.contains(q, na=False).any(), axis=1
    )
    return reset(df[mask])


# ---------------------------------------------------------------------------
# Friendly column labels (shared across all database pages)
# ---------------------------------------------------------------------------
# Maps raw CSV column names to display names in "Name [unit]" format. Any column
# not listed here falls back to its raw name. Adjust freely if a guess is wrong.
COLUMN_LABELS: dict[str, str] = {
    # --- Reactors / Vessels ---
    "reactor_id": "Reactor ID",
    "reactor_name": "Reactor Name",
    "owner": "Owner",
    "tag": "Tag",
    "location": "Location",
    "manufacturer": "Manufacturer",
    "manufacturer_model": "Manufacturer Model",
    "type": "Type",
    "scale": "Scale",
    "D_tank_m": "Tank Diameter [m]",
    "H_m": "Tank Height [m]",
    "H_max_m": "Max Liquid Height [m]",
    "D_imp_m": "Impeller Diameter [m]",
    "impeller_type": "Impeller Type",
    "Np": "Power Number",
    "Nq": "Flow Number",
    "N_rpm_min": "Min Speed [rpm]",
    "N_rpm_max": "Max Speed [rpm]",
    "N_rps": "Speed [rps]",
    "V_L_min": "Min Volume [L]",
    "V_L_max": "Max Volume [L]",
    "V_L": "Working Volume [L]",
    "shell_material": "Shell Material",
    "lining": "Lining",
    "lining_material": "Lining Material",
    "baffles": "Baffles",
    "bottom_dish": "Bottom Dish",
    "top_dish": "Top Dish",
    "impeller_count": "Impeller Count",
    "imp1_clearance_m": "Impeller 1 Clearance [m]",
    "imp1_height_m": "Impeller 1 Height [m]",
    "D_imp2_m": "Impeller 2 Diameter [m]",
    "Np2": "Power Number 2",
    "imp2_clearance_m": "Impeller 2 Clearance [m]",
    "imp2_height_m": "Impeller 2 Height [m]",
    "D_imp3_m": "Impeller 3 Diameter [m]",
    "Np3": "Power Number 3",
    "imp3_clearance_m": "Impeller 3 Clearance [m]",
    "imp3_height_m": "Impeller 3 Height [m]",
    "Zwietering_S": "Zwietering S Constant",
    "GMB_z": "GMB z",
    "wall_thickness_mm": "Wall Thickness [mm]",
    "OD_m": "Outer Diameter [m]",
    "knuckle_radius_m": "Knuckle Radius [m]",
    "instrumentation": "Instrumentation",
    "discharge_location": "Discharge Location",
    "insulated": "Insulated",
    "gas_addition": "Gas Addition",
    "gas_feed_control": "Gas Feed Control",
    "no_ports": "Number of Ports",
    "motor_power_kW": "Motor Power [kW]",
    "aux_units": "Auxiliary Units",
    "cip": "CIP",
    "heating_cooling": "Heating / Cooling",
    "heat_transfer_medium": "Heat Transfer Medium",
    "heat_exchanger": "Heat Exchanger",
    "T_max_C": "Max Temperature [°C]",
    "P_max_atm": "Max Pressure [atm]",
    "impeller_type2": "Impeller Type 2",
    "impeller_type3": "Impeller Type 3",
    "impeller_flow": "Impeller Flow",
    "impeller_model": "Impeller Model",
    "impeller_flow2": "Impeller Flow 2",
    "impeller_model2": "Impeller Model 2",
    "impeller_flow3": "Impeller Flow 3",
    "impeller_model3": "Impeller Model 3",
    "probes": "Probes",
    "search_name": "Search Name",
    # --- Fluids ---
    "fluid_name": "Fluid Name",
    "rho_kg_m3": "Density [kg/m³]",
    "mu_Pa_s": "Viscosity [Pa·s]",
    "D_mol_m2_s": "Molecular Diffusivity [m²/s]",
    "surface_tension_N_m": "Surface Tension [N/m]",
    "Cp_J_per_kgK": "Heat Capacity [J/kg·K]",
    "k_W_per_mK": "Thermal Conductivity [W/m·K]",
    "hsp_d": "Hansen δD [MPa^0.5]",
    "hsp_p": "Hansen δP [MPa^0.5]",
    "hsp_h": "Hansen δH [MPa^0.5]",
    # --- Reactions ---
    "reaction_name": "Reaction Name",
    "order": "Reaction Order",
    "k_value": "Rate Constant",
    "k_units": "Rate Constant Units",
    "C0_mol_L": "Initial Concentration [mol/L]",
    "t_rxn_s": "Reaction Time [s]",
    "T_C": "Temperature [°C]",
    "solvent": "Solvent",
    "delta_H_kJ_mol": "Heat of Reaction [kJ/mol]",
    "reaction_scheme": "Reaction Scheme",
    # --- Particles ---
    "particle_name": "Particle Name",
    "rho_p_kg_m3": "Particle Density [kg/m³]",
    "d10_um": "D10 [µm]",
    "d50_um": "D50 [µm]",
    "d90_um": "D90 [µm]",
    "shape_description": "Shape Description",
    "shape_factor": "Shape Factor",
    # --- Shared ---
    "notes": "Notes",
}


def friendly_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Return a copy of ``df`` with columns renamed to friendly display labels."""
    return df.rename(columns={c: COLUMN_LABELS.get(c, c) for c in df.columns})


def friendly(col: str) -> str:
    """Friendly label for a single column name (raw name if unmapped)."""
    return COLUMN_LABELS.get(col, col)


_UNIT_RE = re.compile(r"^(.*?)\s*\[([^\]]+)\]\s*$")


def split_label(label: str) -> tuple[str, str]:
    """Split a ``"Name [unit]"`` label into ``(name, unit)``.

    Labels without a trailing bracketed unit return ``(label, "")``.
    """
    match = _UNIT_RE.match(label or "")
    if match:
        return match.group(1).strip(), match.group(2).strip()
    return label, ""


def detail_table(df: pd.DataFrame, name_col: str, name: str) -> pd.DataFrame:
    """Return a Property/Value/Units table for the row named ``name``."""
    cols = ["Property", "Value", "Units"]
    if not name:
        return pd.DataFrame(columns=cols)
    match = df[df[name_col].astype(str) == str(name)]
    if match.empty:
        return pd.DataFrame(columns=cols)
    row = match.iloc[0]
    records = []
    for col in df.columns:
        val = row.get(col)
        if pd.isna(val) or str(val).strip() == "":
            continue
        prop, unit = split_label(friendly(col))
        records.append({"Property": prop, "Value": str(val), "Units": unit or "–"})
    return pd.DataFrame(records)
