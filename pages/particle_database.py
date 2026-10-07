"""Particle Database page (Taipy) — browse, edit, add, import/export particles.

Ported from the Streamlit ``4_Particle_Database.py`` page. CRUD, validation and
persistence go through :data:`core.repositories.particles`.
"""
from __future__ import annotations

from taipy.gui import Markdown, notify

from core import repositories as repos
from pages._menu_icons import inject_icons
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

# Admin gate
admin_authenticated = False
admin_user = ""
admin_pw = ""
admin_status = db.admin_status_initial()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _write(state, action, *args) -> bool:
    """Run a repository write; notify and return False when it is refused."""
    try:
        _persist(state, action(*args, principal=db.as_principal(state.admin_authenticated)))
    except (PermissionError, ValueError) as exc:
        notify(state, "E" if isinstance(exc, ValueError) else "W", str(exc))
        return False
    return True


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
    if _write(state, REPO.edit, state.particle_df, payload):
        notify(state, "S", "Saved.")


def on_particle_delete(state, var_name, payload):
    if _searching(state):
        return
    if _write(state, REPO.delete, state.particle_df, payload):
        notify(state, "I", "Row deleted.")


def on_particle_add(state, var_name, payload):
    if _searching(state):
        return
    _write(state, REPO.add_blank, state.particle_df)


def on_particle_add_row(state):
    data = {
        "particle_name": state.part_new_name, "rho_p_kg_m3": state.part_new_rho,
        "d10_um": state.part_new_d10, "d50_um": state.part_new_d50,
        "d90_um": state.part_new_d90, "shape_description": state.part_new_shape,
        "shape_factor": state.part_new_factor, "notes": state.part_new_notes,
    }
    if _write(state, REPO.create, state.particle_df, data):
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
    if _write(state, REPO.replace, new_df):
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
Edit particle properties inline after unlocking the **Admin** panel — **every change
is saved automatically**. Use the search box or column filters to narrow the table, or
the **Add Particle** form below for a validated entry.

<|Particle database|expandable|expanded=False|
<|{particle_search}|input|label=Search particles|on_change=on_particle_search|class_name=db-search|>

<|{particle_view_df}|table|editable={admin_authenticated and particle_search == ""}|filter|rebuild|on_edit=on_particle_edit|on_delete=on_particle_delete|on_add=on_particle_add|width=100%|page_size=12|>
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

<|Add particle|button|on_action=on_particle_add_row|active={admin_authenticated}|>
|>

<|part|class_name=va-card|
## Import / Export
<|layout|columns=1 1|
<|Download CSV|file_download|content={particle_export}|name=particles_export.csv|label=Download particle database|>

<|{particle_upload}|file_selector|label=Import CSV (replaces database)|on_action=on_particle_import|extensions=.csv|active={admin_authenticated}|>
|>
|>
""" + db.ADMIN_PANEL_MD)
)
