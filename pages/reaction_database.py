"""Reaction Database page (Taipy) — browse, edit, add, import/export kinetics.

Ported from the Streamlit ``2_Reaction_Database.py`` page. The editable table
persists every change straight to ``data/reactions.csv`` (single-user, in-place,
as in the Streamlit app).
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
from taipy.gui import Markdown, notify

from utils.menu_icons import inject_icons
from pages import _db_common as db

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
REACTION_CSV = DATA_DIR / "reactions.csv"

COLUMNS = [
    "reaction_name", "type", "order", "k_value", "k_units", "C0_mol_L",
    "t_rxn_s", "T_C", "solvent", "delta_H_kJ_mol", "notes", "reaction_scheme",
]

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------
reaction_df = db.load_csv(REACTION_CSV, COLUMNS)
reaction_search = ""
reaction_view_df = reaction_df
reaction_export = db.csv_bytes(reaction_df)
reaction_msg = f"{len(reaction_df)} reactions in database."

# Scheme viewer
reaction_scheme_options = ["— none —"] + reaction_df["reaction_name"].dropna().astype(str).tolist()
reaction_scheme_selected = "— none —"
reaction_scheme_text = ""

# Add-form fields
rxn_new_name = ""
rxn_new_type = ""
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

reaction_upload = ""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _persist(state) -> None:
    db.save_csv(state.reaction_df, REACTION_CSV)
    state.reaction_export = db.csv_bytes(state.reaction_df)
    state.reaction_msg = f"{len(state.reaction_df)} reactions in database."
    state.reaction_scheme_options = ["— none —"] + state.reaction_df["reaction_name"].dropna().astype(str).tolist()
    state.reaction_view_df = _apply_search(state)


def _apply_search(state) -> pd.DataFrame:
    """Full frame, or a filtered (read-only) view while searching."""
    query = (state.reaction_search or "").strip()
    return db.filter_rows(state.reaction_df, query) if query else state.reaction_df


def on_reaction_search(state):
    state.reaction_view_df = _apply_search(state)


def _searching(state) -> bool:
    if (state.reaction_search or "").strip():
        notify(state, "W", "Clear the search box to edit the database.")
        return True
    return False


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------
def on_reaction_edit(state, var_name, payload):
    if _searching(state):
        return
    state.reaction_df = db.apply_edit(state.reaction_df.copy(), payload)
    _persist(state)
    notify(state, "S", "Saved.")


def on_reaction_delete(state, var_name, payload):
    if _searching(state):
        return
    state.reaction_df = db.delete_row(state.reaction_df.copy(), payload)
    _persist(state)
    notify(state, "I", "Row deleted.")


def on_reaction_add(state, var_name, payload):
    if _searching(state):
        return
    state.reaction_df = db.add_blank(state.reaction_df.copy(), COLUMNS)
    _persist(state)


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
    name = (state.rxn_new_name or "").strip()
    if not name:
        notify(state, "W", "Enter a reaction name.")
        return
    if db.name_taken(state.reaction_df, "reaction_name", name):
        notify(state, "E", f"A reaction named '{name}' already exists.")
        return
    try:
        t_rxn = float(state.rxn_new_trxn)
        k_val = float(state.rxn_new_k)
        c0_val = float(state.rxn_new_C0)
        dh_val = float(state.rxn_new_dH)
    except (TypeError, ValueError):
        notify(state, "E", "k, C0, t_rxn and ΔH must be numeric.")
        return
    order = state.rxn_new_order
    if t_rxn == 0 and k_val > 0:
        if order in ("1", "pseudo-1"):
            t_rxn = 1.0 / k_val
        elif order in ("2", "pseudo-2") and c0_val > 0:
            t_rxn = 1.0 / (k_val * c0_val)
    if k_val <= 0 and t_rxn <= 0:
        notify(state, "E", "Enter a rate constant k (> 0) or a reaction time (> 0).")
        return
    new = pd.DataFrame([{
        "reaction_name": name, "type": state.rxn_new_type, "order": order,
        "k_value": k_val, "k_units": state.rxn_new_k_units, "C0_mol_L": c0_val,
        "t_rxn_s": t_rxn, "T_C": state.rxn_new_T, "solvent": state.rxn_new_solvent,
        "delta_H_kJ_mol": dh_val, "notes": state.rxn_new_notes,
        "reaction_scheme": state.rxn_new_scheme,
    }])
    state.reaction_df = db.reset(pd.concat([state.reaction_df, new], ignore_index=True))
    _persist(state)
    state.rxn_new_name = ""
    notify(state, "S", f"Added '{name}'.")


def on_reaction_import(state):
    path = state.reaction_upload
    if not path:
        return
    try:
        new_df = pd.read_csv(path)
    except Exception as exc:  # noqa: BLE001 - surface parse errors to the user
        notify(state, "E", f"Import failed: {exc}")
        return
    state.reaction_df = db.reset(new_df)
    _persist(state)
    notify(state, "S", f"Imported {len(new_df)} reactions (replaced database).")


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------
page = Markdown(
    inject_icons("""
# __ICON:Reaction_Database__Reaction Database

<|{reaction_msg}|text|>

<|part|class_name=va-card|
## Database
Edit kinetic data inline — **every change is saved automatically**. Use the
search box or column filters to narrow the table, the row actions to add or
delete rows, or the **Add Reaction** form below for a validated entry.

<|part|height=18px|>

<|Reaction database|expandable|expanded=False|
<|{reaction_search}|input|label=Search reactions|on_change=on_reaction_search|class_name=db-search|>

<|{reaction_view_df}|table|editable={reaction_search == ""}|filter|rebuild|on_edit=on_reaction_edit|on_delete=on_reaction_delete|on_add=on_reaction_add|width=100%|page_size=12|>
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

<|{reaction_upload}|file_selector|label=Import CSV (replaces database)|on_action=on_reaction_import|extensions=.csv|>
|>
|>
""")
)
