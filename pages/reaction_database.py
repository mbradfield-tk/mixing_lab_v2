"""Reaction Database page (Taipy) — browse, edit, add, import/export kinetics.

Ported from the Streamlit ``2_Reaction_Database.py`` page. CRUD, validation and the
admin write policy go through :data:`core.repositories.reactions`.
"""
from __future__ import annotations

import pandas as pd
from taipy.gui import Markdown, notify

from core import repositories as repos
from pages._menu_icons import inject_icons
from pages import _db_common as db

REPO = repos.reactions
REACTION_CSV = REPO.path
COLUMNS = REPO.columns
_normalize_reaction_df = repos.normalize_reactions

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------
reaction_df = REPO.load()
reaction_search = ""
reaction_class_search = ""
reaction_measured_search = ""
reaction_class_view_df = reaction_df[reaction_df["class"] == "yes"]
reaction_measured_view_df = reaction_df[reaction_df["class"] != "yes"]
reaction_export = db.csv_bytes(reaction_df)
reaction_msg = f"{len(reaction_df)} reactions in database."

# Scheme viewer
reaction_scheme_options = ["— none —"] + reaction_df["reaction_name"].dropna().astype(str).tolist()
reaction_scheme_selected = "— none —"
reaction_scheme_text = ""

# Add-form fields
rxn_new_name = ""
rxn_new_type = ""
rxn_new_class = "no"
rxn_new_order = "1"
rxn_new_k = 0.01
rxn_new_k_units = "1/s"
rxn_new_C0 = 0.1
rxn_new_trxn = 0.0
rxn_new_T = 25.0
rxn_new_solvent = "THF"
rxn_new_dH = 0.0
rxn_new_notes = ""
rxn_new_scheme = ""
rxn_order_options = ["1", "2", "pseudo-1", "pseudo-2", "n/a"]
rxn_class_options = ["yes", "no"]

reaction_upload = ""

# Admin gate
admin_authenticated = False
admin_user = ""
admin_pw = ""
admin_status = db.admin_status_initial()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _persist(state, df) -> None:
    state.reaction_df = df
    state.reaction_export = db.csv_bytes(df)
    state.reaction_msg = f"{len(df)} reactions in database."
    state.reaction_scheme_options = ["— none —"] + df["reaction_name"].dropna().astype(str).tolist()
    _refresh_views(state)


def _apply_search(df: pd.DataFrame, query: str) -> pd.DataFrame:
    """Return one reaction subset, optionally filtered by its search text."""
    return REPO.search(df, query)[0]


def _refresh_views(state) -> None:
    classes = state.reaction_df[state.reaction_df["class"].astype(str).str.lower() == "yes"]
    measured = state.reaction_df[state.reaction_df["class"].astype(str).str.lower() != "yes"]
    state.reaction_class_view_df = _apply_search(classes, state.reaction_class_search)
    state.reaction_measured_view_df = _apply_search(measured, state.reaction_measured_search)


def on_reaction_search(state):
    _refresh_views(state)


def on_reaction_class_search(state):
    _refresh_views(state)


def on_reaction_measured_search(state):
    _refresh_views(state)


def _searching(state) -> bool:
    if (state.reaction_search or "").strip():
        notify(state, "W", "Clear the search box to edit the database.")
        return True
    return False


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
# Handlers
# ---------------------------------------------------------------------------
def _write(state, action, *args) -> bool:
    """Run a repository write; notify and return False when it is refused."""
    try:
        _persist(state, action(*args, principal=db.as_principal(state.admin_authenticated)))
    except (PermissionError, ValueError) as exc:
        notify(state, "E" if isinstance(exc, ValueError) else "W", str(exc))
        return False
    return True


def on_reaction_edit(state, var_name, payload):
    if not _require_admin(state):
        return
    if (state.reaction_class_search or state.reaction_measured_search).strip():
        notify(state, "W", "Clear the search box to edit the database.")
        return
    if _write(state, REPO.edit, state.reaction_df, payload):
        notify(state, "S", "Saved.")


def on_reaction_delete(state, var_name, payload):
    if not _require_admin(state):
        return
    if (state.reaction_class_search or state.reaction_measured_search).strip():
        notify(state, "W", "Clear the search box to edit the database.")
        return
    if _write(state, REPO.delete, state.reaction_df, payload):
        notify(state, "I", "Row deleted.")


def on_reaction_add(state, var_name, payload):
    if not _require_admin(state):
        return
    if (state.reaction_class_search or state.reaction_measured_search).strip():
        notify(state, "W", "Clear the search box to add to the database.")
        return
    _write(state, REPO.add_blank, state.reaction_df,
           {"class": "yes" if "class" in str(var_name).lower() else "no"})


def on_reaction_scheme_select(state):
    name = state.reaction_scheme_selected
    if name == "— none —":
        state.reaction_scheme_text = ""
        return
    row = state.reaction_df[state.reaction_df["reaction_name"].astype(str) == name]
    scheme = ""
    if not row.empty:
        val = row.iloc[0].get("reaction_scheme", "")
        scheme = str(val) if pd.notna(val) else ""
    state.reaction_scheme_text = scheme or "No reaction scheme available for this reaction."


def on_reaction_add_row(state):
    data = {
        "reaction_name": state.rxn_new_name, "type": state.rxn_new_type,
        "order": state.rxn_new_order, "k_value": state.rxn_new_k,
        "k_units": state.rxn_new_k_units, "C0_mol_L": state.rxn_new_C0,
        "t_rxn_s": state.rxn_new_trxn, "T_C": state.rxn_new_T,
        "solvent": state.rxn_new_solvent, "delta_H_kJ_mol": state.rxn_new_dH,
        "class": state.rxn_new_class, "notes": state.rxn_new_notes,
        "reaction_scheme": state.rxn_new_scheme,
    }
    if _write(state, REPO.create, state.reaction_df, data):
        name = (state.rxn_new_name or "").strip()
        state.rxn_new_name = ""
        notify(state, "S", f"Added '{name}'.")


def on_reaction_import(state):
    if not _require_admin(state):
        return
    path = state.reaction_upload
    if not path:
        return
    try:
        new_df = db.read_upload_csv(path)
    except Exception as exc:  # noqa: BLE001 - surface parse errors to the user
        notify(state, "E", f"Import failed: {exc}")
        return
    if _write(state, REPO.replace, new_df):
        notify(state, "S", f"Imported {len(new_df)} reactions (replaced database).")


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------
page = Markdown(
    inject_icons("""
# __ICON:Reaction_Database__Reaction Database

<|{reaction_msg}|text|>

<|part|class_name=va-card|
## Databases
After unlocking the **Admin** panel, kinetic edits are saved automatically.
Search and browse remain available while the databases are locked.

<|part|height=18px|>

<|Reaction classes|expandable|expanded=False|
<|{reaction_class_search}|input|label=Search reaction classes|on_change=on_reaction_class_search|class_name=db-search|>

<|{reaction_class_view_df}|table|editable={admin_authenticated and reaction_class_search == "" and reaction_measured_search == ""}|filter|rebuild|on_edit=on_reaction_edit|on_delete=on_reaction_delete|on_add=on_reaction_add|width=100%|page_size=12|>
|>

<|Measured kinetics|expandable|expanded=False|
<|{reaction_measured_search}|input|label=Search measured kinetics|on_change=on_reaction_measured_search|class_name=db-search|>

<|{reaction_measured_view_df}|table|editable={admin_authenticated and reaction_class_search == "" and reaction_measured_search == ""}|filter|rebuild|on_edit=on_reaction_edit|on_delete=on_reaction_delete|on_add=on_reaction_add|width=100%|page_size=12|>
|>
|>

<|part|class_name=va-card|
## Reaction Scheme
<|{reaction_scheme_selected}|selector|lov={reaction_scheme_options}|dropdown|label=View scheme for reaction|on_change=on_reaction_scheme_select|>

<|{reaction_scheme_text}|text|class_name=scheme-box|>
|>

<|part|class_name=va-card|
## Add Reaction
<|layout|columns=1 1 1|class_name=form-grid|
<|{rxn_new_name}|input|label=Reaction name *|>

<|{rxn_new_type}|input|label=Type (e.g. Cross-coupling)|>

<|{rxn_new_class}|selector|lov={rxn_class_options}|dropdown|label=Reaction class? (yes/no)|>

<|{rxn_new_order}|selector|lov={rxn_order_options}|dropdown|label=Kinetic order|>
|>

<|layout|columns=1 1 1|class_name=form-grid|
<|{rxn_new_k}|number|label=Rate constant k|>

<|{rxn_new_k_units}|input|label=k units|>

<|{rxn_new_C0}|number|label=C0 (mol/L)|>
|>

<|layout|columns=1 1 1|class_name=form-grid|
<|{rxn_new_trxn}|number|label=Reaction time (s, 0 = auto)|>

<|{rxn_new_T}|number|label=Temperature (°C)|>

<|{rxn_new_solvent}|input|label=Solvent|>
|>

<|layout|columns=1 1 1|class_name=form-grid|
<|{rxn_new_dH}|number|label=ΔH_rxn (kJ/mol, negative = exothermic)|>

<|{rxn_new_notes}|input|label=Notes|>
|>

<|{rxn_new_scheme}|input|label=Reaction scheme (e.g. A + B → C + D)|class_name=form-grid|>

<|Add reaction|button|on_action=on_reaction_add_row|>
|>

<|part|class_name=va-card|
## Import / Export
<|layout|columns=1 3|
<|Download CSV|file_download|content={reaction_export}|name=reactions_export.csv|label=Download reaction database|>

<|{reaction_upload}|file_selector|label=Import CSV (replaces database)|on_action=on_reaction_import|extensions=.csv|active={admin_authenticated}|>
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
""")
)
