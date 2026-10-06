"""Taipy glue for the database pages: re-exports the framework-free table helpers
(:mod:`core.tables`), CSV store and auth, plus the shared admin-gate handlers.

Taipy table CRUD payloads: ``on_edit`` -> ``{"index", "col", "value"}``,
``on_delete`` / ``on_add`` -> ``{"index"}``. Pages keep a contiguous ``RangeIndex``
so the index label equals the row position.
"""
from __future__ import annotations

from core.auth import (
    ANONYMOUS, NOT_CONFIGURED_MSG, Principal, admin_configured, admin_credentials_ok,
)
from core.csv_store import append_csv, fresh_csv, save_csv
from core.records import bottom_dish_height
from core.tables import (
    COLUMN_LABELS, add_blank, apply_edit, clean_uploaded_frame, csv_bytes, delete_row,
    detail_table, filter_rows, fix_mojibake, friendly, friendly_columns, load_csv, name_taken,
    reaction_names, read_upload_csv, reset, split_label,
)

__all__ = [
    "ANONYMOUS", "Principal", "admin_configured", "admin_credentials_ok", "append_csv",
    "fresh_csv", "save_csv", "bottom_dish_height", "COLUMN_LABELS", "add_blank", "apply_edit",
    "clean_uploaded_frame", "csv_bytes", "delete_row", "detail_table", "filter_rows",
    "fix_mojibake", "friendly", "friendly_columns", "load_csv", "name_taken", "reaction_names",
    "read_upload_csv", "reset", "split_label", "as_principal", "admin_status_initial",
    "unlock_attempt", "ADMIN_LOCKED", "ADMIN_UNLOCKED",
]

ADMIN_LOCKED = "🔒 Editing is locked. Unlock with admin credentials to modify the database."
ADMIN_UNLOCKED = "🔓 Editing unlocked. Changes save automatically to the CSV."

# Taipy resolves ``state.<var>`` from the *calling* module, so these helpers never
# touch ``state``; the page handlers read and assign the values themselves.


def as_principal(admin_authenticated: bool) -> Principal:
    return Principal(is_admin=True) if admin_authenticated else ANONYMOUS


def admin_status_initial() -> str:
    return ADMIN_LOCKED if admin_configured() else "🔒 " + NOT_CONFIGURED_MSG


def unlock_attempt(user: str | None, password: str | None) -> tuple[bool, str, str, str]:
    """(unlocked?, status text, notify kind, notify message) for an unlock attempt."""
    if admin_credentials_ok(user, password):
        return True, ADMIN_UNLOCKED, "S", "Admin editing unlocked."
    if not admin_configured():
        return False, "🔒 " + NOT_CONFIGURED_MSG, "E", NOT_CONFIGURED_MSG
    return False, "❌ Invalid credentials. Editing remains locked.", "E", "Invalid admin credentials."

