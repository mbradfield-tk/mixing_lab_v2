"""Vessel-database import: diff an uploaded table against the database and apply
approved changes. Reactor IDs and search names are derived here too."""
from __future__ import annotations

from typing import Callable

import pandas as pd

# Derived/auto-managed columns are never offered as per-cell import changes; they
# are recomputed automatically after the merge instead.
AUTO_COLS = {"reactor_id", "search_name"}


def assign_missing_reactor_ids(df: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """Assign sequential RX IDs to rows whose reactor ID is missing."""
    result = df.copy()
    if "reactor_id" not in result.columns:
        result.insert(0, "reactor_id", "")

    reactor_ids = result["reactor_id"].astype("string").str.strip()
    rx_numbers = pd.to_numeric(
        reactor_ids.str.extract(r"^RX-(\d+)$", expand=False), errors="coerce"
    )
    next_number = int(rx_numbers.max()) + 1 if rx_numbers.notna().any() else 1
    missing = reactor_ids.isna() | reactor_ids.eq("")

    for index in result.index[missing]:
        result.at[index, "reactor_id"] = f"RX-{next_number:03d}"
        next_number += 1

    return result, int(missing.sum())


def search_name_for(row: pd.Series) -> str:
    """Build the searchable vessel label from its identifying fields."""
    def clean(value) -> str:
        return "" if pd.isna(value) else str(value).strip()

    owner = clean(row.get("owner"))
    reactor_name = clean(row.get("reactor_name"))
    impeller_type = clean(row.get("impeller_type"))
    impeller_count = clean(row.get("impeller_count"))
    try:
        numeric_count = float(impeller_count)
        if numeric_count.is_integer():
            impeller_count = str(int(numeric_count))
    except ValueError:
        pass

    vessel = " ".join(part for part in (owner, reactor_name) if part)
    impeller = ", ".join(part for part in (impeller_type, impeller_count) if part)
    return f"{vessel} ({impeller})" if vessel and impeller else vessel or impeller


def refresh_search_names(df: pd.DataFrame) -> pd.DataFrame:
    """Create or refresh the derived search name for every vessel."""
    result = df.copy()
    result["search_name"] = result.apply(search_name_for, axis=1)
    return result


def fill_missing_search_names(df: pd.DataFrame) -> pd.DataFrame:
    """Fill only the blank/missing search names, leaving existing ones intact."""
    result = df.copy()
    if "search_name" not in result.columns:
        result["search_name"] = ""
    names = result["search_name"].astype("string").str.strip()
    missing = names.isna() | names.eq("")
    for index in result.index[missing]:
        result.at[index, "search_name"] = search_name_for(result.loc[index])
    return result


def is_blank(value) -> bool:
    return pd.isna(value) or str(value).strip() == ""


def values_differ(old, new) -> bool:
    """True when ``new`` carries a real change over ``old`` (blanks never wipe)."""
    if is_blank(new):
        return False
    if is_blank(old):
        return True
    try:
        return float(old) != float(new)
    except (TypeError, ValueError):
        return str(old).strip() != str(new).strip()


def disp_value(value) -> str:
    """Format a cell value for the review dialog (markdown)."""
    return "*(empty)*" if is_blank(value) else f"`{str(value).strip()}`"


def build_import_changes(existing: pd.DataFrame, new_df: pd.DataFrame,
                         label: Callable[[str], str] = str) -> list[dict]:
    """Diff an uploaded frame against the current database.

    Returns an ordered list of change descriptors (``add`` for new vessels,
    ``update`` for a single differing cell of an existing vessel), each carrying
    a pre-built markdown description for the approval dialog. Rows are matched to
    an existing vessel by ``reactor_id`` first (the stable key), falling back to
    ``reactor_name`` (both case-insensitive). ``label`` maps a column name to its
    display label.
    """
    changes: list[dict] = []
    if "reactor_name" not in new_df.columns:
        return changes

    id_index: dict[str, int] = {}
    if "reactor_id" in existing.columns:
        for idx, rid in existing["reactor_id"].items():
            if not is_blank(rid):
                id_index[str(rid).strip().lower()] = idx
    name_index: dict[str, int] = {}
    for idx, name in existing["reactor_name"].items():
        if not is_blank(name):
            name_index[str(name).strip().lower()] = idx

    # reactor_name IS diffable so a rename of an id-matched vessel can be reviewed.
    shared_cols = [
        c for c in new_df.columns
        if c in existing.columns and c not in AUTO_COLS
    ]

    for _, new_row in new_df.iterrows():
        raw_name = new_row.get("reactor_name")
        raw_id = new_row.get("reactor_id")
        display_name = "" if is_blank(raw_name) else str(raw_name).strip()

        old_idx = None
        match_by = None
        if not is_blank(raw_id) and str(raw_id).strip().lower() in id_index:
            key = str(raw_id).strip().lower()
            old_idx = id_index[key]
            match_by = ("reactor_id", key)
        elif display_name and display_name.lower() in name_index:
            key = display_name.lower()
            old_idx = name_index[key]
            match_by = ("reactor_name", key)

        if old_idx is None and not display_name:
            continue  # nothing identifies this row

        if old_idx is not None:
            label_name = str(existing.at[old_idx, "reactor_name"]).strip() or display_name
            for col in shared_cols:
                old_val = existing.at[old_idx, col]
                new_val = new_row[col]
                if values_differ(old_val, new_val):
                    changes.append({
                        "kind": "update",
                        "reactor_name": label_name,
                        "match_by": match_by,
                        "col": col,
                        "new": new_val,
                        "desc": (
                            f"**Update vessel:** {label_name}\n\n"
                            f"**Field:** {label(col)}\n\n"
                            f"**Current:** {disp_value(old_val)}\n\n"
                            f"**New:** {disp_value(new_val)}"
                        ),
                    })
        else:
            row = {c: new_row.get(c, "") for c in existing.columns}
            row["reactor_name"] = display_name
            summary_keys = ["owner", "scale", "impeller_type", "V_L_max"]
            summary = [
                f"**{label(k)}:** {str(row.get(k, '')).strip()}"
                for k in summary_keys if not is_blank(row.get(k))
            ]
            desc = f"**Add new vessel:** {display_name}"
            if summary:
                desc += "\n\n" + "  \n".join(summary)
            changes.append({
                "kind": "add",
                "reactor_name": display_name,
                "row": row,
                "desc": desc,
            })

    return changes


def apply_import_change(df: pd.DataFrame, change: dict) -> pd.DataFrame:
    """Apply a single approved change to the working frame."""
    result = df.copy()
    if change["kind"] == "add":
        row = {c: change["row"].get(c, "") for c in result.columns}
        result = pd.concat([result, pd.DataFrame([row])], ignore_index=True)
    else:
        field, key = change["match_by"]
        mask = result[field].astype(str).str.strip().str.lower() == key
        if mask.any():
            idx = result.index[mask][0]
            col = change["col"]
            value = change["new"]
            if pd.api.types.is_numeric_dtype(result[col].dtype):
                try:
                    value = float(value)
                except (TypeError, ValueError):
                    result[col] = result[col].astype(object)  # column now holds text
            result.at[idx, col] = value
    return result.reset_index(drop=True)
