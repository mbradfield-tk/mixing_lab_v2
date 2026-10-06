"""Vessel (Reactor) Database page (Taipy) — browse, edit, add, import/export.

Ported from the Streamlit ``1_Reactor_Database.py`` page (reactor images
deferred). The table displays friendly column labels while persisting the raw
CSV schema to ``data/reactors.csv``. Editing is locked by default and unlocked
with admin credentials to guard against accidental changes.
"""
from __future__ import annotations

import pandas as pd
from taipy.gui import Markdown, notify

from pages import _db_common as db
from core import repositories as repos
from core import tables
from core import vessel_import as vimport
from utils.menu_icons import inject_icons
from pages._vessel_media import build_vessel_viewer_html, media_caption
from viz.vessel_schematic import brim_volume, build_vessel_schematic

REPO = repos.reactors
REACTOR_CSV = REPO.path


def _reverse_map(columns: list[str]) -> dict[str, str]:
    """Map friendly display labels back to their raw CSV column names."""
    return {db.friendly(c): c for c in columns}


_assign_missing_reactor_ids = vimport.assign_missing_reactor_ids
_search_name_for = vimport.search_name_for
_refresh_search_names = vimport.refresh_search_names
_fill_missing_search_names = vimport.fill_missing_search_names
_apply_import_change = vimport.apply_import_change
_build_import_changes = REPO.import_changes


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------
vessel_raw_df = REPO.load()                                # source of truth (raw columns)
vessel_columns = list(vessel_raw_df.columns)
vessel_colmap = _reverse_map(vessel_columns)               # friendly -> raw
vessel_df = db.friendly_columns(vessel_raw_df)             # displayed / edited (friendly columns)
vessel_search = ""                                         # global search box

# Scope of the search box: the two headline fields, every field, or one column.
VESSEL_SEARCH_NAME_OWNER = "Name & Owner"
VESSEL_SEARCH_ALL = "All fields"

# Text match by default; the comparison operators filter a single numeric column.
VESSEL_SEARCH_CONTAINS = tables.SEARCH_CONTAINS
vessel_search_op_options = tables.SEARCH_OPS


def _search_field_options(columns: list[str]) -> list[str]:
    return [VESSEL_SEARCH_NAME_OWNER, VESSEL_SEARCH_ALL] + columns


vessel_search_field_options = _search_field_options(list(vessel_df.columns))
vessel_search_field = VESSEL_SEARCH_NAME_OWNER
vessel_search_op = VESSEL_SEARCH_CONTAINS
vessel_search_status = ""
vessel_view_df = vessel_df                                 # what the table shows (full or filtered)

# Click-to-highlight row: `selected` drives Taipy's own highlight, the index list
# is also read back by vessel_row_class for the stronger custom styling.
vessel_selected_rows: list[int] = []
vessel_selected_caption = ""

vessel_export = db.csv_bytes(vessel_raw_df)
vessel_msg = f"{len(vessel_raw_df)} vessels in database."

vessel_options = sorted(vessel_raw_df["reactor_name"].dropna().astype(str).unique().tolist())
selected_vessel = ("TMA EasyMax-102" if "TMA EasyMax-102" in vessel_options
                   else (vessel_options[0] if vessel_options else ""))

# Admin gate
admin_authenticated = False
admin_user = ""
admin_pw = ""
admin_status = db.admin_status_initial()

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


# Property filter for the "Explore Vessel" detail table.
_DEFAULT_PROPS = [
    "Reactor ID", "Reactor Name", "Owner", "Scale", "Tank Diameter",
    "Min Volume", "Max Volume", "Impeller Count", "Min Speed", "Max Speed",
    "Shell Material",
]


def _all_property_names(columns: list[str]) -> list[str]:
    """Friendly property names (unit stripped) for every column, in order."""
    names: list[str] = []
    for col in columns:
        prop = db.split_label(db.friendly(col))[0]
        if prop and prop not in names:
            names.append(prop)
    return names


def _detail_view(raw_df: pd.DataFrame, name: str, selected: list) -> pd.DataFrame:
    """Property/Value/Units table for ``name`` limited to the selected properties."""
    full = db.detail_table(raw_df, "reactor_name", name)
    if selected:
        full = db.reset(full[full["Property"].isin(selected)])
    return full


vessel_prop_options = _all_property_names(vessel_columns)
vessel_prop_selected = [p for p in _DEFAULT_PROPS if p in vessel_prop_options]

vessel_detail_df = _detail_view(vessel_raw_df, selected_vessel, vessel_prop_selected)
vessel_viewer_html = build_vessel_viewer_html(_reactor_id_for(vessel_raw_df, selected_vessel))
vessel_media_caption = media_caption(_reactor_id_for(vessel_raw_df, selected_vessel))

def _default_fill_L(row: pd.Series, total_L: float) -> float:
    """Midpoint of the vessel's working-volume range, else 70% of brim-full."""
    try:
        lo, hi = float(row.get("V_L_min")), float(row.get("V_L_max"))
        if lo > 0 and hi > 0:  # NaN comparisons are False, so NaNs fall through
            return round((lo + hi) / 2.0, 2)
    except (TypeError, ValueError):
        pass
    return round(total_L * 0.7, 2)


# 2D cross-section schematic + liquid fill level
_row0 = _row_for(vessel_raw_df, selected_vessel)
vessel_total_vol_L = brim_volume(_row0)
vessel_fill_L = _default_fill_L(_row0, vessel_total_vol_L)
_schem0 = build_vessel_schematic(_row0, vessel_fill_L, title=selected_vessel)
vessel_schematic_html = _schem0["html"]


def _fill_caption(res: dict) -> str:
    if res.get("level_mm") is None:
        base = f"Brim-full working volume ≈ {res.get('total_L', 0):,.1f} L."
    else:
        base = (f"Liquid surface at **{res['level_mm']:+.0f} mm** relative to the bottom "
                f"tangent line ({res['fill_pct']:.0f}% of the {res['total_L']:,.1f} L "
                f"brim-full volume).")
        area = res.get("contact_area_m2")
        if area is not None:
            base += f" Wetted contact area ≈ **{area:,.3f} m²**."
    warns = res.get("warnings") or []
    if warns:
        base += "\n\n⚠️ **Impeller–wall interference:** " + " ".join(warns)
    return base


def _fill_status_warning(row: pd.Series, fill_L: float, schem: dict) -> str:
    """Single fill warning: volume band takes priority, else the schematic's
    liquid-level/impeller warning. Red for every case except a liquid level
    that intersects an impeller (partially submerged), which is yellow."""
    try:
        lo = float(row.get("V_L_min"))
    except (TypeError, ValueError):
        lo = float("nan")
    if lo > 0 and fill_L < lo:
        return "🔴 Below Min Volume ({:g} L)".format(lo)
    try:
        hi = float(row.get("V_L_max"))
    except (TypeError, ValueError):
        hi = float("nan")
    if hi > 0 and fill_L > hi:
        return "🔴 Above Max Volume ({:g} L)".format(hi)
    if schem.get("level_warning_kind") == "red":
        return "🔴 Liquid level is below the lowest impeller"
    if schem.get("level_warning_kind") == "yellow":
        return "🟡 Liquid level is at the lowest impeller"
    other = schem.get("other_level_warning")
    return f"🟡 {other}" if other else ""


vessel_fill_caption = _fill_caption(_schem0)
vessel_fill_min_warning = _fill_status_warning(_row0, vessel_fill_L, _schem0)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _refresh_display(state) -> None:
    state.vessel_columns = list(state.vessel_raw_df.columns)
    state.vessel_colmap = _reverse_map(state.vessel_columns)
    state.vessel_df = db.friendly_columns(state.vessel_raw_df)
    state.vessel_search_field_options = _search_field_options(list(state.vessel_df.columns))
    if state.vessel_search_field not in state.vessel_search_field_options:
        state.vessel_search_field = VESSEL_SEARCH_NAME_OWNER
    state.vessel_view_df = _apply_search(state)


def _search_columns(field: str) -> list[str] | None:
    """Columns to search; None means every column."""
    if field == VESSEL_SEARCH_ALL:
        return None
    if field == VESSEL_SEARCH_NAME_OWNER:
        return ["Reactor Name", "Owner"]
    return [field]


def _apply_search(state) -> pd.DataFrame:
    """Return the full friendly frame, or a filtered (read-only) view when searching."""
    view, state.vessel_search_status = tables.search(
        state.vessel_df, state.vessel_search, _search_columns(state.vessel_search_field),
        state.vessel_search_op, noun="vessels")
    return view


def _clear_row_selection(state) -> None:
    state.vessel_selected_rows = []
    state.vessel_selected_caption = ""


_numeric_series = tables.numeric_series


def on_vessel_row_select(state, var_name, payload):
    index = payload.get("index")
    if index is None:
        return
    if index in state.vessel_selected_rows:
        _clear_row_selection(state)
        return
    state.vessel_selected_rows = [index]
    view = state.vessel_view_df
    name = ""
    if 0 <= index < len(view) and "Reactor Name" in view.columns:
        name = str(view.iloc[index].get("Reactor Name", "") or "")
    state.vessel_selected_caption = (
        f"**Highlighted row {index + 1}:** {name}" if name
        else f"**Highlighted row {index + 1}**")


def on_vessel_search(state):
    state.vessel_view_df = _apply_search(state)
    _clear_row_selection(state)


def on_vessel_search_field_change(state):
    state.vessel_view_df = _apply_search(state)
    _clear_row_selection(state)


def on_vessel_search_op_change(state):
    state.vessel_view_df = _apply_search(state)
    _clear_row_selection(state)


def _searching(state) -> bool:
    if (state.vessel_search or "").strip():
        notify(state, "W", "Clear the search box to edit the database.")
        return True
    return False


def _persist(state) -> None:
    state.vessel_export = db.csv_bytes(state.vessel_raw_df)
    state.vessel_msg = f"{len(state.vessel_raw_df)} vessels in database."
    state.vessel_options = sorted(
        state.vessel_raw_df["reactor_name"].dropna().astype(str).unique().tolist())


def _write(state, action, *args) -> bool:
    """Run a repository write into ``vessel_raw_df``; notify and return False if refused."""
    try:
        state.vessel_raw_df = action(*args, principal=db.as_principal(state.admin_authenticated))
    except PermissionError as exc:
        notify(state, "W", str(exc))
        return False
    _refresh_display(state)
    _persist(state)
    return True


def _require_admin(state) -> bool:
    if not state.admin_authenticated:
        notify(state, "W", "Editing is locked — unlock with admin credentials first.")
        return False
    return True


# ---------------------------------------------------------------------------
# Admin authentication
# ---------------------------------------------------------------------------
def on_admin_unlock(state):
    ok, state.admin_status, kind, msg = db.unlock_attempt(state.admin_user, state.admin_pw)
    state.admin_authenticated = ok
    if ok:
        state.admin_pw = ""
    notify(state, kind, msg)


def on_admin_lock(state):
    state.admin_authenticated = False
    state.admin_user = ""
    state.admin_pw = ""
    state.admin_status = db.admin_status_initial()
    notify(state, "I", "Editing locked.")


# ---------------------------------------------------------------------------
# Table CRUD handlers (operate on the raw frame; display stays friendly)
# ---------------------------------------------------------------------------
def on_vessel_edit(state, var_name, payload):
    if _searching(state) or not _require_admin(state):
        return
    raw_payload = dict(payload)
    raw_payload["col"] = state.vessel_colmap.get(payload["col"], payload["col"])
    if _write(state, REPO.edit, state.vessel_raw_df, raw_payload):
        notify(state, "S", "Saved.")


def on_vessel_delete(state, var_name, payload):
    if _searching(state) or not _require_admin(state):
        return
    if _write(state, REPO.delete, state.vessel_raw_df, payload):
        _clear_row_selection(state)
        notify(state, "I", "Row deleted.")


def on_vessel_add(state, var_name, payload):
    if _searching(state) or not _require_admin(state):
        return
    if _write(state, REPO.add_blank, state.vessel_raw_df):
        _clear_row_selection(state)


def _refresh_schematic(state):
    row = _row_for(state.vessel_raw_df, state.selected_vessel)
    res = build_vessel_schematic(row, state.vessel_fill_L, title=state.selected_vessel)
    state.vessel_total_vol_L = res["total_L"]
    state.vessel_schematic_html = res["html"]
    state.vessel_fill_caption = _fill_caption(res)
    state.vessel_fill_min_warning = _fill_status_warning(row, state.vessel_fill_L, res)


def on_vessel_select(state):
    name = state.selected_vessel
    state.vessel_detail_df = _detail_view(state.vessel_raw_df, name, state.vessel_prop_selected)
    rid = _reactor_id_for(state.vessel_raw_df, name)
    state.vessel_viewer_html = build_vessel_viewer_html(rid)
    state.vessel_media_caption = media_caption(rid)
    row = _row_for(state.vessel_raw_df, name)
    state.vessel_fill_L = _default_fill_L(row, brim_volume(row))
    _refresh_schematic(state)


def on_vessel_props_change(state):
    state.vessel_detail_df = _detail_view(
        state.vessel_raw_df, state.selected_vessel, state.vessel_prop_selected)


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
        new_df = db.read_upload_csv(path)
    except Exception as exc:  # noqa: BLE001 - surface parse errors to the user
        notify(state, "E", f"Import failed: {exc}")
        return
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
    applied, skipped = cache["applied"], cache["skipped"]
    try:
        df, assigned_count = REPO.apply_import(cache["working"],
                                               db.as_principal(state.admin_authenticated))
    except PermissionError as exc:
        notify(state, "W", str(exc))
        return
    state.vessel_raw_df = df
    _refresh_display(state)
    _clear_row_selection(state)
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
    inject_icons("""
# __ICON:Vessel_Database__Vessel Database

<|{vessel_msg}|text|>

<|part|class_name=va-card|
## Database
Editing is enabled only when unlocked in the **Admin** panel at the bottom of the
page. Reactor images are added separately.

<|part|height=18px|>

<|layout|columns=260px 150px 320px|
<|{vessel_search_field}|selector|lov={vessel_search_field_options}|dropdown|label=Search in|on_change=on_vessel_search_field_change|>

<|{vessel_search_op}|selector|lov={vessel_search_op_options}|dropdown|label=Compare|on_change=on_vessel_search_op_change|>

<|{vessel_search}|input|label=Search|on_change=on_vessel_search|class_name=db-search|>
|>

<|{vessel_search_status}|text|>

Click any row to highlight it, making it easier to follow while editing. Choose a
single field and a comparison operator to filter numerically — for example, set
**Search in** to Max Volume, **Compare** to greater-than and search for 100.

<|{vessel_selected_caption}|text|mode=markdown|>

<|Vessel database|expandable|expanded=False|
<|part|class_name=vessel-db-table|
<|{vessel_view_df}|table|editable={admin_authenticated and vessel_search == ""}|filter|rebuild|on_edit=on_vessel_edit|on_delete=on_vessel_delete|on_add=on_vessel_add|on_action=on_vessel_row_select|selected={vessel_selected_rows}|width=100%|page_size=12|>
|>
|>
|>

<|part|class_name=va-card|
## Explore Vessel
<|{selected_vessel}|selector|lov={vessel_options}|dropdown|label=Select vessel|on_change=on_vessel_select|>

<|layout|columns=1 1|
<|part|content={vessel_viewer_html}|height=380px|>

<|part|class_name=vessel-props|
<|{vessel_prop_selected}|selector|lov={vessel_prop_options}|multiple|dropdown|label=Properties to show|on_change=on_vessel_props_change|>

<|{vessel_detail_df}|table|width=100%|show_all|class_name=vp-table|>
|>
|>

### 2D Schematic & Liquid Level
<|layout|columns=1 1|
<|part|content={vessel_schematic_html}|height=380px|class_name=vessel-schem|>

<|part|
Enter a fill volume to draw the liquid surface on the vessel cross-section.

<|layout|columns=1 1|
<|{vessel_fill_L}|number|label=Liquid fill volume (L)|on_change=on_vessel_fill_change|>

<|{vessel_fill_min_warning}|text|mode=markdown|>
|>

<|{vessel_fill_caption}|text|mode=markdown|>
|>
|>
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

""")
)
