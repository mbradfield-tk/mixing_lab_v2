"""Particle Database page (Taipy) — browse, edit, add, import/export particles.

Ported from the Streamlit ``4_Particle_Database.py`` page. CRUD, validation and
persistence go through :data:`core.repositories.particles`.
"""
from __future__ import annotations

from taipy.gui import Markdown, notify

from core import repositories as repos
from utils.menu_icons import inject_icons
from pages import _db_common as db

REPO = repos.particles
PARTICLE_CSV = REPO.path
COLUMNS = REPO.columns

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------
particle_df = REPO.load()
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
def _persist(state, df) -> None:
    state.particle_df = df
    state.particle_export = db.csv_bytes(df)
    state.particle_msg = f"{len(df)} particles in database."
    state.particle_view_df = _apply_search(state)


def _apply_search(state):
    """Full frame, or a filtered (read-only) view while searching."""
    return REPO.search(state.particle_df, state.particle_search)[0]


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
    _persist(state, REPO.edit(state.particle_df, payload, db.ANONYMOUS))
    notify(state, "S", "Saved.")


def on_particle_delete(state, var_name, payload):
    if _searching(state):
        return
    _persist(state, REPO.delete(state.particle_df, payload, db.ANONYMOUS))
    notify(state, "I", "Row deleted.")


def on_particle_add(state, var_name, payload):
    if _searching(state):
        return
    _persist(state, REPO.add_blank(state.particle_df, db.ANONYMOUS))


def on_particle_add_row(state):
    data = {
        "particle_name": state.part_new_name, "rho_p_kg_m3": state.part_new_rho,
        "d10_um": state.part_new_d10, "d50_um": state.part_new_d50,
        "d90_um": state.part_new_d90, "shape_description": state.part_new_shape,
        "shape_factor": state.part_new_factor, "notes": state.part_new_notes,
    }
    try:
        df = REPO.create(state.particle_df, data, db.ANONYMOUS)
    except ValueError as exc:
        notify(state, "E", str(exc))
        return
    _persist(state, df)
    name = (state.part_new_name or "").strip()
    state.part_new_name = ""
    notify(state, "S", f"Added '{name}'.")


def on_particle_import(state):
    path = state.particle_upload
    if not path:
        return
    try:
        new_df = db.read_upload_csv(path)
    except Exception as exc:  # noqa: BLE001 - surface parse errors to the user
        notify(state, "E", f"Import failed: {exc}")
        return
    _persist(state, REPO.replace(new_df, db.ANONYMOUS))
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
