"""Tests for the shared database helpers in pages/_db_common.py."""

import os
import sys

import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pages import _db_common as db


@pytest.fixture
def frame() -> pd.DataFrame:
    return pd.DataFrame({
        "name": ["Alpha", "Beta", "Gamma"],
        "rho": [1000.0, 800.0, 1200.0],
        "notes": ["water-like", "light solvent", "dense brine"],
    })


# --- CRUD -------------------------------------------------------------------
def test_apply_edit_coerces_numeric_columns(frame):
    out = db.apply_edit(frame, {"index": 1, "col": "rho", "value": "850"})
    assert out.at[1, "rho"] == 850.0
    assert isinstance(out.at[1, "rho"], float)


def test_apply_edit_leaves_text_columns_alone(frame):
    out = db.apply_edit(frame, {"index": 0, "col": "notes", "value": "123"})
    assert out.at[0, "notes"] == "123"


def test_delete_row_reindexes(frame):
    out = db.delete_row(frame, {"index": 1})
    assert list(out["name"]) == ["Alpha", "Gamma"]
    assert list(out.index) == [0, 1]


def test_delete_missing_index_is_noop(frame):
    out = db.delete_row(frame, {"index": 99})
    assert len(out) == 3


def test_add_blank_uses_zero_for_numeric_and_empty_for_text(frame):
    out = db.add_blank(frame, ["name", "rho", "notes"])
    assert len(out) == 4
    assert out.at[3, "rho"] == 0.0
    assert out.at[3, "name"] == ""


def test_name_taken_is_case_insensitive(frame):
    assert db.name_taken(frame, "name", "  beta ")
    assert not db.name_taken(frame, "name", "Delta")
    assert not db.name_taken(pd.DataFrame(), "name", "Alpha")


def test_filter_rows_scopes_to_columns(frame):
    assert list(db.filter_rows(frame, "brine")["name"]) == ["Gamma"]
    # "brine" only appears in notes, so a name-only search finds nothing.
    assert db.filter_rows(frame, "brine", columns=["name"]).empty
    assert len(db.filter_rows(frame, "")) == 3


# --- CSV I/O ----------------------------------------------------------------
def test_save_append_and_fresh_csv_roundtrip(tmp_path, frame):
    path = tmp_path / "db.csv"
    db.save_csv(frame, path)
    assert db.append_csv(pd.DataFrame([{"name": "Delta", "rho": 900.0, "notes": ""}]), path) == 4
    fresh = db.fresh_csv(path, ["name", "missing_col"])
    assert len(fresh) == 4
    assert "missing_col" in fresh.columns
    assert not list(tmp_path.glob(".db_*.tmp")), "temp file must be cleaned up"


def test_fresh_csv_missing_file_returns_empty_with_columns(tmp_path):
    out = db.fresh_csv(tmp_path / "nope.csv", ["a", "b"])
    assert out.empty and list(out.columns) == ["a", "b"]


def test_read_upload_csv_handles_encodings_and_mojibake(tmp_path):
    utf8 = tmp_path / "u.csv"
    utf8.write_text("name,T\nAcetone,35°\n", encoding="utf-8-sig")
    assert db.read_upload_csv(str(utf8)).at[0, "T"] == "35°"

    mac = tmp_path / "m.csv"
    mac.write_bytes("name,T\nAcetone,35°\n".encode("mac_roman"))
    assert db.read_upload_csv(str(mac)).at[0, "T"] == "35°"

    moji = tmp_path / "x.csv"
    moji.write_text("name,T\nAcetone,35Â°\n", encoding="utf-8")
    assert db.read_upload_csv(str(moji)).at[0, "T"] == "35°"


def test_csv_bytes_is_utf8_without_index(frame):
    raw = db.csv_bytes(frame)
    assert raw.startswith(b"name,rho,notes\n")


# --- Admin gate -------------------------------------------------------------
def test_admin_credentials_ok(monkeypatch):
    monkeypatch.setenv("MIXING_LAB_ADMIN_USER", "ops")
    monkeypatch.setenv("MIXING_LAB_ADMIN_PW", "s3cret")
    assert db.admin_credentials_ok(" ops ", "s3cret")
    assert not db.admin_credentials_ok("ops", "S3CRET")
    assert not db.admin_credentials_ok("", "")
    assert not db.admin_credentials_ok(None, None)


def test_admin_login_fails_closed_without_env(monkeypatch):
    monkeypatch.delenv("MIXING_LAB_ADMIN_USER", raising=False)
    monkeypatch.delenv("MIXING_LAB_ADMIN_PW", raising=False)
    assert not db.admin_configured()
    assert not db.admin_credentials_ok("admin", "admin_tak_2026")
    assert not db.admin_credentials_ok("", "")


# --- Reactor geometry accessors --------------------------------------------
def test_bottom_dish_height_prefers_csv_column():
    row = pd.Series({"H_bot_dish_m": 0.05, "H_max_m": 1.0, "L_tan_tan_m": 0.8})
    assert db.bottom_dish_height(row) == 0.05


def test_bottom_dish_height_derived_fallback_requires_consistent_heights():
    assert db.bottom_dish_height(pd.Series({"H_max_m": 0.8, "L_tan_tan_m": 1.0})) == 0.0
    assert db.bottom_dish_height(pd.Series({})) == 0.0
