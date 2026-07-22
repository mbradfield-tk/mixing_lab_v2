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

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
REACTOR_CSV = DATA_DIR / "reactors.csv"

# Lightweight gate against accidental edits (not a real security boundary — the
# credentials live in source, matching the Streamlit app's admin pattern).
ADMIN_USER = "admin"
ADMIN_PW = "admin_tak_2026"


def _reverse_map(columns: list[str]) -> dict[str, str]:
    """Map friendly display labels back to their raw CSV column names."""
    return {db.friendly(c): c for c in columns}


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


def _reactor_id_for(df: pd.DataFrame, reactor_name: str) -> str:
    row = df[df["reactor_name"].astype(str) == str(reactor_name)]
    if row.empty or "reactor_id" not in df.columns:
        return ""
    return str(row.iloc[0].get("reactor_id", "") or "")


vessel_detail_df = db.detail_table(vessel_raw_df, "reactor_name", selected_vessel)
vessel_viewer_html = build_vessel_viewer_html(_reactor_id_for(vessel_raw_df, selected_vessel))
vessel_media_caption = media_caption(_reactor_id_for(vessel_raw_df, selected_vessel))


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
    _refresh_display(state)
    _persist(state)


def on_vessel_select(state):
    name = state.selected_vessel
    state.vessel_detail_df = db.detail_table(state.vessel_raw_df, "reactor_name", name)
    rid = _reactor_id_for(state.vessel_raw_df, name)
    state.vessel_viewer_html = build_vessel_viewer_html(rid)
    state.vessel_media_caption = media_caption(rid)


def on_vessel_import(state):
    if not _require_admin(state):
        return
    path = state.vessel_upload
    if not path:
        return
    try:
        new_df = pd.read_csv(path)
    except Exception as exc:  # noqa: BLE001 - surface parse errors to the user
        notify(state, "E", f"Import failed: {exc}")
        return
    state.vessel_raw_df = db.reset(new_df)
    _refresh_display(state)
    _persist(state)
    notify(state, "S", f"Imported {len(new_df)} vessels (replaced database).")


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

<|Vessel properties|expandable|expanded=False|
<|{vessel_detail_df}|table|width=100%|show_all|>
|>

<|{vessel_media_caption}|text|>

<|part|content={vessel_viewer_html}|height=380px|>
|>

<|part|class_name=va-card|
## Import / Export
<|layout|columns=1 1|
<|Download CSV|file_download|content={vessel_export}|name=reactors_export.csv|label=Download vessel database|>

<|{vessel_upload}|file_selector|label=Import CSV (replaces database)|on_action=on_vessel_import|extensions=.csv|active={admin_authenticated}|>
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
<|Updated: 2026.07.22|text|>
|>
|>

"""
)
