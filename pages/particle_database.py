"""Particle Database page (Taipy) — browse, edit, add, import/export particles.

Ported from the Streamlit ``4_Particle_Database.py`` page. The editable table
persists every change straight to ``data/particles.csv``.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
from taipy.gui import Markdown, notify

from utils.menu_icons import inject_icons
from pages import _db_common as db

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
PARTICLE_CSV = DATA_DIR / "particles.csv"

COLUMNS = [
    "particle_name", "rho_p_kg_m3", "d10_um", "d50_um", "d90_um",
    "shape_description", "shape_factor", "notes",
]

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------
particle_df = db.load_csv(PARTICLE_CSV, COLUMNS)
particle_search = ""
particle_view_df = particle_df
particle_export = db.csv_bytes(particle_df)
particle_msg = f"{len(particle_df)} particles in database."

# Add-form fields
part_new_name = ""
part_new_rho = 1500.0
part_new_d10 = 10.0
part_new_d50 = 50.0
part_new_d90 = 150.0
part_new_shape = ""
part_new_factor = 1.0
part_new_notes = ""

particle_upload = ""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _persist(state) -> None:
    db.save_csv(state.particle_df, PARTICLE_CSV)
    state.particle_export = db.csv_bytes(state.particle_df)
    state.particle_msg = f"{len(state.particle_df)} particles in database."
    state.particle_view_df = _apply_search(state)


def _apply_search(state) -> pd.DataFrame:
    """Full frame, or a filtered (read-only) view while searching."""
    query = (state.particle_search or "").strip()
    return db.filter_rows(state.particle_df, query) if query else state.particle_df


def on_particle_search(state):
    state.particle_view_df = _apply_search(state)


def _searching(state) -> bool:
    if (state.particle_search or "").strip():
        notify(state, "W", "Clear the search box to edit the database.")
        return True
    return False


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------
def on_particle_edit(state, var_name, payload):
    if _searching(state):
        return
    state.particle_df = db.apply_edit(state.particle_df.copy(), payload)
    _persist(state)
    notify(state, "S", "Saved.")


def on_particle_delete(state, var_name, payload):
    if _searching(state):
        return
    state.particle_df = db.delete_row(state.particle_df.copy(), payload)
    _persist(state)
    notify(state, "I", "Row deleted.")


def on_particle_add(state, var_name, payload):
    if _searching(state):
        return
    state.particle_df = db.add_blank(state.particle_df.copy(), COLUMNS)
    _persist(state)


def on_particle_add_row(state):
    name = (state.part_new_name or "").strip()
    if not name:
        notify(state, "W", "Enter a particle name.")
        return
    if db.name_taken(state.particle_df, "particle_name", name):
        notify(state, "E", f"A particle named '{name}' already exists.")
        return
    d10, d50, d90 = float(state.part_new_d10), float(state.part_new_d50), float(state.part_new_d90)
    if not (d10 <= d50 <= d90):
        notify(state, "E", "Particle sizes must satisfy d10 ≤ d50 ≤ d90.")
        return
    new = pd.DataFrame([{
        "particle_name": name, "rho_p_kg_m3": float(state.part_new_rho),
        "d10_um": d10, "d50_um": d50, "d90_um": d90,
        "shape_description": state.part_new_shape,
        "shape_factor": float(state.part_new_factor), "notes": state.part_new_notes,
    }])
    state.particle_df = db.reset(pd.concat([state.particle_df, new], ignore_index=True))
    _persist(state)
    state.part_new_name = ""
    notify(state, "S", f"Added '{name}'.")


def on_particle_import(state):
    path = state.particle_upload
    if not path:
        return
    try:
        new_df = pd.read_csv(path)
    except Exception as exc:  # noqa: BLE001 - surface parse errors to the user
        notify(state, "E", f"Import failed: {exc}")
        return
    state.particle_df = db.reset(new_df)
    _persist(state)
    notify(state, "S", f"Imported {len(new_df)} particles (replaced database).")


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------
page = Markdown(
    inject_icons("""
# __ICON:Particle_Database__Particle Database

<|{particle_msg}|text|>

<|part|class_name=va-card|
## Database
Edit particle properties inline — **every change is saved automatically**. Use
the search box or column filters to narrow the table, or the **Add Particle**
form below for a validated entry.

<|Particle database|expandable|expanded=False|
<|{particle_search}|input|label=Search particles|on_change=on_particle_search|class_name=db-search|>

<|{particle_view_df}|table|editable={particle_search == ""}|filter|rebuild|on_edit=on_particle_edit|on_delete=on_particle_delete|on_add=on_particle_add|width=100%|page_size=12|>
|>
|>

<|part|class_name=va-card|
## Add Particle
<|layout|columns=1 1 1|class_name=form-grid|
<|{part_new_name}|input|label=Particle name *|>

<|{part_new_rho}|number|label=Density ρ_p (kg/m³)|>

<|{part_new_factor}|number|label=Shape factor|>
|>

<|layout|columns=1 1 1|class_name=form-grid|
<|{part_new_d10}|number|label=D10 (µm)|>

<|{part_new_d50}|number|label=D50 (µm)|>

<|{part_new_d90}|number|label=D90 (µm)|>
|>

<|layout|columns=1 1 1|class_name=form-grid|
<|{part_new_shape}|input|label=Shape description|>

<|{part_new_notes}|input|label=Notes|>
|>

<|Add particle|button|on_action=on_particle_add_row|>
|>

<|part|class_name=va-card|
## Import / Export
<|layout|columns=1 1|
<|Download CSV|file_download|content={particle_export}|name=particles_export.csv|label=Download particle database|>

<|{particle_upload}|file_selector|label=Import CSV (replaces database)|on_action=on_particle_import|extensions=.csv|>
|>
|>
""")
)
