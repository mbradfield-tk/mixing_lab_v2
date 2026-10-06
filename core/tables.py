"""DataFrame helpers for the database tables: tolerant CSV import, inline edits,
search and the friendly column labels. Framework-free (shared by Taipy pages and the API)."""
from __future__ import annotations

import io
import re
from pathlib import Path

import pandas as pd


def load_csv(path: Path, columns: list[str]) -> pd.DataFrame:
    """Load ``path`` if it exists, else return an empty frame with ``columns``."""
    if path.exists():
        return pd.read_csv(path).reset_index(drop=True)
    return pd.DataFrame(columns=columns)


def fix_mojibake(value):
    """Repair double-encoded UTF-8 text (e.g. ``35Â°`` -> ``35°``).

    Some exports (Excel) re-save UTF-8 as if it were Latin-1, mangling accented
    characters. Only strings carrying the tell-tale ``Â``/``Ã`` markers are
    round-tripped back through latin-1/utf-8; everything else is left untouched.
    """
    if not isinstance(value, str) or ("Â" not in value and "Ã" not in value):
        return value
    try:
        return value.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return value


def clean_uploaded_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Strip mojibake from every text cell of a freshly-read import frame."""
    result = df.copy()
    for col in result.columns:
        if result[col].dtype == object:
            result[col] = result[col].map(fix_mojibake)
    return result


def read_upload_csv(source: str | Path | bytes, **read_kwargs) -> pd.DataFrame:
    """Read a user-uploaded CSV (path or raw bytes) tolerantly and repair mojibake.

    Tries UTF-8 (with BOM), then the common Excel export encodings (Excel for
    Mac's plain CSV is Mac-Roman, Windows exports are cp1252) and finally
    latin-1, which never fails. Parse errors other than decoding propagate.
    """
    def _read(enc):
        src = io.BytesIO(source) if isinstance(source, bytes) else source
        return pd.read_csv(src, encoding=enc, **read_kwargs)

    df = None
    for enc in ("utf-8-sig", "mac_roman", "cp1252"):
        try:
            df = _read(enc)
            break
        except UnicodeDecodeError:
            continue
    if df is None:
        df = _read("latin-1")
    return clean_uploaded_frame(df)


def reaction_names(df: pd.DataFrame, class_value: str | None = None) -> list[str]:
    """Return sorted reaction names, optionally filtered by class flag.

    ``class=yes`` denotes a general reaction class; every other value denotes
    measured or project-specific kinetics for backwards-compatible imports.
    """
    if "reaction_name" not in df.columns:
        return []
    names = df["reaction_name"].dropna().astype(str)
    if class_value is not None:
        values = (df["class"].fillna("no").astype(str).str.strip().str.lower()
                  if "class" in df.columns else pd.Series("no", index=df.index))
        names = df.loc[values.eq(class_value.lower()), "reaction_name"].dropna().astype(str)
    return sorted(names.unique().tolist())


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
    """Apply an inline table edit ``{"index", "col", "value"}`` and return the frame."""
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


def numeric_series(series: pd.Series) -> pd.Series:
    """Coerce a column to numbers, tolerating thousands separators like ``14,774``."""
    cleaned = series.astype(str).str.replace(",", "", regex=False).str.strip()
    return pd.to_numeric(cleaned, errors="coerce")


SEARCH_CONTAINS = "contains"
NUMERIC_OPS = {
    "=": lambda series, value: series == value,
    "<": lambda series, value: series < value,
    "<=": lambda series, value: series <= value,
    ">": lambda series, value: series > value,
    ">=": lambda series, value: series >= value,
}
SEARCH_OPS = [SEARCH_CONTAINS, *NUMERIC_OPS]


def search(df: pd.DataFrame, query: str, columns: list[str] | None = None,
           op: str = SEARCH_CONTAINS, noun: str = "rows") -> tuple[pd.DataFrame, str]:
    """(matching rows, status note). ``contains`` searches ``columns`` (None = all);
    a numeric ``op`` compares the single column in ``columns`` with ``query``.
    Unusable numeric searches return the full frame and say why."""
    query = (query or "").strip()
    if not query:
        return df, ""
    if op == SEARCH_CONTAINS:
        return filter_rows(df, query, columns=columns), ""
    if op not in NUMERIC_OPS:
        raise ValueError(f"Unknown search operator '{op}'.")
    if not columns or len(columns) != 1:
        return df, f"Pick a single field to compare with {op}."
    try:
        value = float(query)
    except ValueError:
        return df, f"Enter a number to compare with {op}."
    field = columns[0]
    result = reset(df[NUMERIC_OPS[op](numeric_series(df[field]), value)])
    return result, f"{len(result)} of {len(df)} {noun} where {field} {op} {query}."


# ---------------------------------------------------------------------------
# Friendly column labels (shared across all database tables)
# ---------------------------------------------------------------------------
# Maps raw CSV column names to display names in "Name [unit]" format. Any column
# not listed here falls back to its raw name.
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
    "L_tan_tan_m": "Tan-Tan Length [m]",
    "H_max_m": "Max Fill Height [m]",
    "H_bot_dish_m": "Bottom Dish Height [m]",
    "H_m": "Full Height [m]",
    "D_imp_m": "Impeller Diameter [m]",
    "H_bottom_dish_m": "Bottom Dish Height [m]",
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
    "class": "Reaction Class",
    "type": "Reaction Type",
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
