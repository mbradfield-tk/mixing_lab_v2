"""Vessel (Reactor) Database page (Taipy) — browse, edit, add, import/export.

Ported from the Streamlit ``1_Reactor_Database.py`` page (reactor images
deferred). The table displays friendly column labels while persisting the raw
CSV schema to ``data/reactors.csv``. Editing is locked by default and unlocked
with admin credentials to guard against accidental changes.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
from taipy.gui import Markdown, notify

from pages import _db_common as db
from vessel_media import build_vessel_viewer_html, media_caption
from vessel_schematic import brim_volume, build_vessel_schematic

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
REACTOR_CSV = DATA_DIR / "reactors.csv"

# Lightweight gate against accidental edits (not a real security boundary — the
# credentials live in source, matching the Streamlit app's admin pattern).
ADMIN_USER = "admin"
ADMIN_PW = "admin_tak_2026"


def _reverse_map(columns: list[str]) -> dict[str, str]:
    """Map friendly display labels back to their raw CSV column names."""
    return {db.friendly(c): c for c in columns}


def _assign_missing_reactor_ids(df: pd.DataFrame) -> tuple[pd.DataFrame, int]:
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


def _search_name_for(row: pd.Series) -> str:
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


def _refresh_search_names(df: pd.DataFrame) -> pd.DataFrame:
    """Create or refresh the derived search name for every vessel."""
    result = df.copy()
    result["search_name"] = result.apply(_search_name_for, axis=1)
    return result


def _fill_missing_search_names(df: pd.DataFrame) -> pd.DataFrame:
    """Fill only the blank/missing search names, leaving existing ones intact."""
    result = df.copy()
    if "search_name" not in result.columns:
        result["search_name"] = ""
    names = result["search_name"].astype("string").str.strip()
    missing = names.isna() | names.eq("")
    for index in result.index[missing]:
        result.at[index, "search_name"] = _search_name_for(result.loc[index])
    return result


# Derived/auto-managed columns are never offered as per-cell import changes; they
# are recomputed automatically after the merge instead.
_IMPORT_AUTO_COLS = {"reactor_id", "search_name"}


def _is_blank(value) -> bool:
    return pd.isna(value) or str(value).strip() == ""


def _fix_mojibake(value):
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


def _clean_uploaded_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Strip mojibake from every text cell of a freshly-read import frame."""
    result = df.copy()
    for col in result.columns:
        if result[col].dtype == object:
            result[col] = result[col].map(_fix_mojibake)
    return result


def _values_differ(old, new) -> bool:
    """True when ``new`` carries a real change over ``old`` (blanks never wipe)."""
    if _is_blank(new):
        return False  # don't propose overwriting existing data with a blank cell
    if _is_blank(old):
        return True
    try:
        return float(old) != float(new)
    except (TypeError, ValueError):
        return str(old).strip() != str(new).strip()


def _disp_value(value) -> str:
    """Format a cell value for the review dialog (markdown)."""
    return "*(empty)*" if _is_blank(value) else f"`{str(value).strip()}`"


def _build_import_changes(existing: pd.DataFrame, new_df: pd.DataFrame) -> list[dict]:
    """Diff an uploaded frame against the current database.

    Returns an ordered list of change descriptors (``add`` for new vessels,
    ``update`` for a single differing cell of an existing vessel), each carrying
    a pre-built markdown description for the approval dialog. Rows are matched to
    an existing vessel by ``reactor_id`` first (the stable key), falling back to
    ``reactor_name`` (both case-insensitive).
    """
    changes: list[dict] = []
    if "reactor_name" not in new_df.columns:
        return changes

    id_index: dict[str, int] = {}
    if "reactor_id" in existing.columns:
        for idx, rid in existing["reactor_id"].items():
            if not _is_blank(rid):
                id_index[str(rid).strip().lower()] = idx
    name_index: dict[str, int] = {}
    for idx, name in existing["reactor_name"].items():
        if not _is_blank(name):
            name_index[str(name).strip().lower()] = idx

    # reactor_id / search_name are auto-managed; reactor_name IS diffable so a
    # rename (e.g. an id-matched vessel with a different name) can be reviewed.
    shared_cols = [
        c for c in new_df.columns
        if c in existing.columns and c not in _IMPORT_AUTO_COLS
    ]

    for _, new_row in new_df.iterrows():
        raw_name = new_row.get("reactor_name")
        raw_id = new_row.get("reactor_id")
        display_name = "" if _is_blank(raw_name) else str(raw_name).strip()

        old_idx = None
        match_by = None
        if not _is_blank(raw_id) and str(raw_id).strip().lower() in id_index:
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
                if _values_differ(old_val, new_val):
                    label = db.friendly(col)
                    changes.append({
                        "kind": "update",
                        "reactor_name": label_name,
                        "match_by": match_by,
                        "col": col,
                        "new": new_val,
                        "desc": (
                            f"**Update vessel:** {label_name}\n\n"
                            f"**Field:** {label}\n\n"
                            f"**Current:** {_disp_value(old_val)}\n\n"
                            f"**New:** {_disp_value(new_val)}"
                        ),
                    })
        else:
            row = {c: new_row.get(c, "") for c in existing.columns}
            row["reactor_name"] = display_name
            summary_keys = ["owner", "scale", "impeller_type", "V_L_max"]
            summary = [
                f"**{db.friendly(k)}:** {str(row.get(k, '')).strip()}"
                for k in summary_keys if not _is_blank(row.get(k))
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


def _apply_import_change(df: pd.DataFrame, change: dict) -> pd.DataFrame:
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


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------
vessel_raw_df = db.load_csv(REACTOR_CSV, ["reactor_name"])  # source of truth (raw columns)
vessel_columns = list(vessel_raw_df.columns)
vessel_colmap = _reverse_map(vessel_columns)               # friendly -> raw
vessel_df = db.friendly_columns(vessel_raw_df)             # displayed / edited (friendly columns)
vessel_search = ""                                         # global search box
vessel_view_df = vessel_df                                 # what the table shows (full or filtered)
vessel_export = db.csv_bytes(vessel_raw_df)
vessel_msg = f"{len(vessel_raw_df)} vessels in database."

vessel_options = sorted(vessel_raw_df["reactor_name"].dropna().astype(str).unique().tolist())
selected_vessel = vessel_options[0] if vessel_options else ""

# Admin gate
admin_authenticated = False
admin_user = ""
admin_pw = ""
admin_status = "🔒 Editing is locked. Unlock with admin credentials to modify the database."

vessel_upload = ""

# Import review workflow. Only lightweight display state is bound to the GUI;
# the working frame and the pending-change queue live in a private ``state._``
# dict cache (following the _ms_cache/_vc_cache convention). A leading-underscore
# module global holding a plain dict is never serialized to the client, whereas
# binding a DataFrame / list there stalls update propagation from the
# file_selector action.
vessel_import_active = False
vessel_import_progress = ""
vessel_import_current = ""

_vessel_import_cache: dict = {}


def _reactor_id_for(df: pd.DataFrame, reactor_name: str) -> str:
    row = df[df["reactor_name"].astype(str) == str(reactor_name)]
    if row.empty or "reactor_id" not in df.columns:
        return ""
    return str(row.iloc[0].get("reactor_id", "") or "")


def _row_for(df: pd.DataFrame, reactor_name: str) -> pd.Series:
    row = df[df["reactor_name"].astype(str) == str(reactor_name)]
    return row.iloc[0] if not row.empty else pd.Series(dtype=object)


vessel_detail_df = db.detail_table(vessel_raw_df, "reactor_name", selected_vessel)
vessel_viewer_html = build_vessel_viewer_html(_reactor_id_for(vessel_raw_df, selected_vessel))
vessel_media_caption = media_caption(_reactor_id_for(vessel_raw_df, selected_vessel))

# 2D cross-section schematic + liquid fill level
_row0 = _row_for(vessel_raw_df, selected_vessel)
vessel_total_vol_L = brim_volume(_row0)
vessel_fill_L = round(vessel_total_vol_L * 0.7, 2)
_schem0 = build_vessel_schematic(_row0, vessel_fill_L, title=selected_vessel)
vessel_schematic_html = _schem0["html"]


def _fill_caption(res: dict) -> str:
    if res.get("level_mm") is None:
        base = f"Brim-full working volume ≈ {res.get('total_L', 0):,.1f} L."
    else:
        base = (f"Liquid surface at **{res['level_mm']:+.0f} mm** relative to the bottom "
                f"tangent line ({res['fill_pct']:.0f}% of the {res['total_L']:,.1f} L "
                f"brim-full volume).")
    warns = res.get("warnings") or []
    if warns:
        base += "\n\n⚠️ **Impeller–wall interference:** " + " ".join(warns)
    return base


vessel_fill_caption = _fill_caption(_schem0)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _refresh_display(state) -> None:
    state.vessel_columns = list(state.vessel_raw_df.columns)
    state.vessel_colmap = _reverse_map(state.vessel_columns)
    state.vessel_df = db.friendly_columns(state.vessel_raw_df)
    state.vessel_view_df = _apply_search(state)


def _apply_search(state) -> pd.DataFrame:
    """Return the full friendly frame, or a filtered (read-only) view when searching.

    Searches only the Reactor Name and Owner columns.
    """
    query = (state.vessel_search or "").strip()
    return (db.filter_rows(state.vessel_df, query, columns=["Reactor Name", "Owner"])
            if query else state.vessel_df)


def on_vessel_search(state):
    state.vessel_view_df = _apply_search(state)


def _searching(state) -> bool:
    if (state.vessel_search or "").strip():
        notify(state, "W", "Clear the search box to edit the database.")
        return True
    return False


def _persist(state) -> None:
    db.save_csv(state.vessel_raw_df, REACTOR_CSV)
    state.vessel_export = db.csv_bytes(state.vessel_raw_df)
    state.vessel_msg = f"{len(state.vessel_raw_df)} vessels in database."
    state.vessel_options = sorted(
        state.vessel_raw_df["reactor_name"].dropna().astype(str).unique().tolist())


def _require_admin(state) -> bool:
    if not state.admin_authenticated:
        notify(state, "W", "Editing is locked — unlock with admin credentials first.")
        return False
    return True


# ---------------------------------------------------------------------------
# Admin authentication
# ---------------------------------------------------------------------------
def on_admin_unlock(state):
    if (state.admin_user or "").strip() == ADMIN_USER and (state.admin_pw or "") == ADMIN_PW:
        state.admin_authenticated = True
        state.admin_status = "🔓 Editing unlocked. Changes save automatically to the CSV."
        state.admin_pw = ""
        notify(state, "S", "Admin editing unlocked.")
    else:
        state.admin_authenticated = False
        state.admin_status = "❌ Invalid credentials. Editing remains locked."
        notify(state, "E", "Invalid admin credentials.")


def on_admin_lock(state):
    state.admin_authenticated = False
    state.admin_user = ""
    state.admin_pw = ""
    state.admin_status = "🔒 Editing is locked. Unlock with admin credentials to modify the database."
    notify(state, "I", "Editing locked.")


# ---------------------------------------------------------------------------
# Table CRUD handlers (operate on the raw frame; display stays friendly)
# ---------------------------------------------------------------------------
def on_vessel_edit(state, var_name, payload):
    if _searching(state) or not _require_admin(state):
        return
    raw_payload = dict(payload)
    raw_payload["col"] = state.vessel_colmap.get(payload["col"], payload["col"])
    state.vessel_raw_df = db.apply_edit(state.vessel_raw_df.copy(), raw_payload)
    state.vessel_raw_df = _refresh_search_names(state.vessel_raw_df)
    _refresh_display(state)
    _persist(state)
    notify(state, "S", "Saved.")


def on_vessel_delete(state, var_name, payload):
    if _searching(state) or not _require_admin(state):
        return
    state.vessel_raw_df = db.delete_row(state.vessel_raw_df.copy(), payload)
    _refresh_display(state)
    _persist(state)
    notify(state, "I", "Row deleted.")


def on_vessel_add(state, var_name, payload):
    if _searching(state) or not _require_admin(state):
        return
    state.vessel_raw_df = db.add_blank(state.vessel_raw_df.copy(), state.vessel_columns)
    state.vessel_raw_df, _ = _assign_missing_reactor_ids(state.vessel_raw_df)
    state.vessel_raw_df = _refresh_search_names(state.vessel_raw_df)
    _refresh_display(state)
    _persist(state)


def _refresh_schematic(state):
    row = _row_for(state.vessel_raw_df, state.selected_vessel)
    res = build_vessel_schematic(row, state.vessel_fill_L, title=state.selected_vessel)
    state.vessel_total_vol_L = res["total_L"]
    state.vessel_schematic_html = res["html"]
    state.vessel_fill_caption = _fill_caption(res)


def on_vessel_select(state):
    name = state.selected_vessel
    state.vessel_detail_df = db.detail_table(state.vessel_raw_df, "reactor_name", name)
    rid = _reactor_id_for(state.vessel_raw_df, name)
    state.vessel_viewer_html = build_vessel_viewer_html(rid)
    state.vessel_media_caption = media_caption(rid)
    total = brim_volume(_row_for(state.vessel_raw_df, name))
    state.vessel_fill_L = round(total * 0.7, 2)
    _refresh_schematic(state)


def on_vessel_fill_change(state):
    total = state.vessel_total_vol_L
    raw = float(state.vessel_fill_L or 0.0)
    fill = min(max(0.0, raw), round(total, 2)) if total > 0 else max(0.0, raw)
    # Only write back when the value was actually clamped — re-assigning the
    # variable that triggered this on_change otherwise trips a Taipy warning.
    if fill != raw:
        state.vessel_fill_L = fill
    _refresh_schematic(state)


def on_vessel_import(state):
    if not _require_admin(state):
        return
    path = state.vessel_upload
    if not path:
        return
    try:
        new_df = pd.read_csv(path, encoding="utf-8-sig")
    except Exception as exc:  # noqa: BLE001 - surface parse errors to the user
        notify(state, "E", f"Import failed: {exc}")
        return
    new_df = _clean_uploaded_frame(new_df)
    changes = _build_import_changes(state.vessel_raw_df, new_df)
    if not changes:
        notify(state, "I", "No differences found — database is already up to date.")
        return
    state._vessel_import_cache = {
        "working": state.vessel_raw_df.copy(),
        "pending": changes,
        "index": 0,
        "applied": 0,
        "skipped": 0,
    }
    state.vessel_import_active = True
    _show_import_change(state)
    notify(state, "I", f"{len(changes)} change(s) to review.")


def _show_import_change(state):
    cache = state._vessel_import_cache
    changes = cache["pending"]
    index = cache["index"]
    state.vessel_import_progress = f"Change {index + 1} of {len(changes)}"
    state.vessel_import_current = changes[index]["desc"]


def _advance_import(state):
    cache = state._vessel_import_cache
    cache["index"] += 1
    if cache["index"] >= len(cache["pending"]):
        _finalize_import(state)
    else:
        _show_import_change(state)


def on_vessel_import_approve(state):
    cache = state._vessel_import_cache
    change = cache["pending"][cache["index"]]
    cache["working"] = _apply_import_change(cache["working"], change)
    cache["applied"] += 1
    _advance_import(state)


def on_vessel_import_reject(state):
    state._vessel_import_cache["skipped"] += 1
    _advance_import(state)


def on_vessel_import_accept_all(state):
    cache = state._vessel_import_cache
    pending = cache["pending"]
    while cache["index"] < len(pending):
        cache["working"] = _apply_import_change(cache["working"], pending[cache["index"]])
        cache["applied"] += 1
        cache["index"] += 1
    _finalize_import(state)


def on_vessel_import_cancel(state):
    state.vessel_import_active = False
    state._vessel_import_cache = {}
    state.vessel_upload = ""
    notify(state, "I", "Import cancelled — no changes applied.")


def _finalize_import(state):
    cache = state._vessel_import_cache
    df, assigned_count = _assign_missing_reactor_ids(cache["working"])
    df = _fill_missing_search_names(df)
    applied, skipped = cache["applied"], cache["skipped"]
    state.vessel_raw_df = db.reset(df)
    _refresh_display(state)
    _persist(state)
    state.vessel_import_active = False
    state._vessel_import_cache = {}
    state.vessel_upload = ""
    message = f"Import complete — {applied} change(s) applied, {skipped} skipped."
    if assigned_count:
        message += f" Assigned {assigned_count} new reactor ID(s)."
    notify(state, "S", message)


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------
page = Markdown(
    """
# ⚗️ Vessel Database

<|{vessel_msg}|text|>

<|part|class_name=va-card|
## Database
Editing is enabled only when unlocked in the **Admin** panel at the bottom of the
page. Reactor images are added separately.

<|Vessel database|expandable|expanded=False|
<|{vessel_search}|input|label=Search by name or owner|on_change=on_vessel_search|class_name=db-search|>

<|{vessel_view_df}|table|editable={admin_authenticated and vessel_search == ""}|filter|rebuild|on_edit=on_vessel_edit|on_delete=on_vessel_delete|on_add=on_vessel_add|width=100%|page_size=12|>
|>
|>

<|part|class_name=va-card|
## Explore Vessel
<|{selected_vessel}|selector|lov={vessel_options}|dropdown|label=Select vessel|on_change=on_vessel_select|>

<|layout|columns=1 1|
<|part|content={vessel_viewer_html}|height=380px|>

<|{vessel_detail_df}|table|width=100%|show_all|height=380px|>
|>

### 2D Schematic & Liquid Level
Enter a fill volume to draw the liquid surface on the vessel cross-section.

<|{vessel_fill_L}|number|label=Liquid fill volume (L)|on_change=on_vessel_fill_change|>

<|{vessel_fill_caption}|text|mode=markdown|>

<|part|content={vessel_schematic_html}|height=560px|>
|>

<|part|class_name=va-card|
## Import / Export
Importing **merges** an uploaded CSV into the current database: matching vessels
(by ID, then name) are updated and new vessels are added. Review each change
individually, or use **Accept all remaining** to apply everything at once.
Missing reactor IDs and search names are filled in automatically.

<|layout|columns=1 1|
<|Download CSV|file_download|content={vessel_export}|name=reactors_export.csv|label=Download vessel database|>

<|{vessel_upload}|file_selector|label=Import CSV (merge & review changes)|on_action=on_vessel_import|extensions=.csv|active={admin_authenticated}|>
|>

<|{vessel_import_active}|dialog|title=Review Import Changes|width=560px|on_action=on_vessel_import_cancel|
<|{vessel_import_progress}|text|>

<|{vessel_import_current}|text|mode=markdown|>

<|layout|columns=1 1 1 1|
<|✅ Approve|button|on_action=on_vessel_import_approve|class_name=compute-btn|>

<|⏭️ Skip|button|on_action=on_vessel_import_reject|>

<|⏩ Accept all remaining|button|on_action=on_vessel_import_accept_all|>

<|✖️ Cancel import|button|on_action=on_vessel_import_cancel|>
|>
|>
|>

<|part|class_name=va-card|
## Admin
<|{admin_status}|text|>

<|part|render={not admin_authenticated}|
<|layout|columns=230px 230px 150px|
<|{admin_user}|input|label=Admin username|>

<|{admin_pw}|input|password|label=Admin password|on_action=on_admin_unlock|>

<|Unlock editing|button|on_action=on_admin_unlock|>
|>
|>

<|part|render={admin_authenticated}|
<|Lock editing|button|on_action=on_admin_lock|>
|>
|>

<|part|class_name=va-card|
<|Updated: 2026.08.18|text|>
|>

"""
)
