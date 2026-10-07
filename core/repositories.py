"""Database repositories: validated CRUD over the CSV tables, with the write policy.

Each method takes the caller's working frame (a Taipy session's copy, or a fresh
:meth:`Repository.load` in an API handler), applies one change, persists it
atomically and returns the new frame. Writes call :func:`core.auth.authorize`
(``PermissionError``); invalid input raises ``ValueError`` with a readable message;
unknown names raise ``LookupError``. Swapping CSV for a database only touches
this module and :mod:`core.csv_store`.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
from pydantic import BaseModel, ValidationError

from core import tables
from core import vessel_import as vimport
from core.auth import Principal, authorize
from core.csv_store import append_csv, fresh_csv, save_csv
from core.records import DATA_DIR
from core.schemas import (
    RESULT_COLUMNS, FluidRecord, ParticleRecord, ReactionRecord, ReactorRecord, RecordedResult,
    validation_message,
)
from utils.solvent_properties import is_known_solvent


@dataclass
class Repository:
    table: str
    path: Path
    columns: list[str]
    name_col: str
    label: str
    record: type[BaseModel] | None = None
    normalize: Callable[[pd.DataFrame], pd.DataFrame] | None = None
    reserved: Callable[[str], str | None] | None = None

    # --- reads -----------------------------------------------------------
    def load(self) -> pd.DataFrame:
        df = tables.load_csv(self.path, self.columns)
        return self.normalize(df) if self.normalize else df

    def shared(self) -> pd.DataFrame:
        """mtime-cached frame shared across sessions — READ-ONLY."""
        return fresh_csv(self.path, [self.name_col])

    def names(self, df: pd.DataFrame | None = None) -> list[str]:
        df = self.load() if df is None else df
        if self.name_col not in df.columns:
            return []
        return df[self.name_col].dropna().astype(str).tolist()

    def index_of(self, df: pd.DataFrame, name: str) -> int:
        hits = df.index[df[self.name_col].astype(str) == str(name)]
        if len(hits) == 0:
            raise LookupError(f"Unknown {self.label} '{name}'.")
        return int(hits[0])

    def get(self, name: str, df: pd.DataFrame | None = None) -> dict:
        df = self.load() if df is None else df
        return df.loc[self.index_of(df, name)].to_dict()

    def search(self, df: pd.DataFrame, query: str, columns: list[str] | None = None,
               op: str = tables.SEARCH_CONTAINS) -> tuple[pd.DataFrame, str]:
        return tables.search(df, query, columns, op, noun=f"{self.label}s")

    # --- writes ----------------------------------------------------------
    def save(self, df: pd.DataFrame, principal: Principal) -> pd.DataFrame:
        authorize(principal, self.table)
        df = tables.reset(df)
        save_csv(df, self.path)
        return df

    def validate(self, data: dict) -> dict:
        """Record dict (CSV columns) for ``data``; ``ValueError`` when invalid."""
        if self.record is None:
            return dict(data)
        try:
            return self.record.model_validate(data).model_dump(by_alias=True)
        except ValidationError as exc:
            raise ValueError(validation_message(exc)) from None

    def create(self, df: pd.DataFrame, data: dict, principal: Principal) -> pd.DataFrame:
        authorize(principal, self.table)
        name = str(data.get(self.name_col) or "").strip()
        if not name:
            raise ValueError(f"Enter a {self.label} name.")
        if self.reserved and (msg := self.reserved(name)):
            raise ValueError(msg)
        if tables.name_taken(df, self.name_col, name):
            raise ValueError(f"A {self.label} named '{name}' already exists.")
        row = self.validate({**data, self.name_col: name})
        return self.save(pd.concat([df, pd.DataFrame([row])], ignore_index=True), principal)

    def edit(self, df: pd.DataFrame, payload: dict, principal: Principal) -> pd.DataFrame:
        """Inline cell edit ``{"index", "col", "value"}`` (index = row position)."""
        authorize(principal, self.table)
        return self.save(tables.apply_edit(df.copy(), payload), principal)

    def update(self, df: pd.DataFrame, name: str, changes: dict,
               principal: Principal) -> pd.DataFrame:
        """Set several columns of the row named ``name``."""
        authorize(principal, self.table)
        unknown = [c for c in changes if c not in df.columns]
        if unknown:
            raise ValueError(f"Unknown column(s): {', '.join(unknown)}")
        idx = self.index_of(df, name)
        out = df.copy()
        for col, value in changes.items():
            out = tables.apply_edit(out, {"index": idx, "col": col, "value": value})
        return self.save(out, principal)

    def delete(self, df: pd.DataFrame, payload: dict, principal: Principal) -> pd.DataFrame:
        authorize(principal, self.table)
        return self.save(tables.delete_row(df.copy(), payload), principal)

    def add_blank(self, df: pd.DataFrame, principal: Principal,
                  values: dict | None = None) -> pd.DataFrame:
        """Append a blank row (0.0 numeric / "" text), with ``values`` preset."""
        authorize(principal, self.table)
        out = tables.add_blank(df.copy(), list(df.columns) or self.columns)
        for col, value in (values or {}).items():
            out.loc[out.index[-1], col] = value
        return self.save(out, principal)

    def replace(self, new_df: pd.DataFrame, principal: Principal) -> pd.DataFrame:
        """Replace the whole table (CSV import)."""
        authorize(principal, self.table)
        df = tables.reset(new_df)
        return self.save(self.normalize(df) if self.normalize else df, principal)


def normalize_reactions(df: pd.DataFrame) -> pd.DataFrame:
    """Ensure imported/legacy reaction data has a normalized ``class`` flag (yes/no)."""
    result = df.copy()
    if "class" not in result.columns:
        insert_at = result.columns.get_loc("notes") if "notes" in result else len(result.columns)
        result.insert(insert_at, "class", "no")
    result["class"] = (result["class"].fillna("no").astype(str).str.strip().str.lower()
                       .replace({"": "no"}))
    return result


class ReactorRepository(Repository):
    """Vessels keep generated ``reactor_id`` / ``search_name`` columns in step."""

    def edit(self, df, payload, principal):
        authorize(principal, self.table)
        out = vimport.refresh_search_names(tables.apply_edit(df.copy(), payload))
        return self.save(out, principal)

    def update(self, df, name, changes, principal):
        out = super().update(df, name, changes, principal)
        return self.save(vimport.refresh_search_names(out), principal)

    def add_blank(self, df, principal, values=None):
        authorize(principal, self.table)
        out, _ = vimport.assign_missing_reactor_ids(
            tables.add_blank(df.copy(), list(df.columns) or self.columns))
        return self.save(vimport.refresh_search_names(out), principal)

    def import_changes(self, df: pd.DataFrame, new_df: pd.DataFrame) -> list[dict]:
        """Reviewable per-field changes of an uploaded vessel table (merge, not replace)."""
        return vimport.build_import_changes(df, new_df, label=tables.friendly)

    def apply_import(self, working: pd.DataFrame,
                     principal: Principal) -> tuple[pd.DataFrame, int]:
        """Persist an import's working frame; (frame, number of new reactor IDs)."""
        authorize(principal, self.table)
        out, assigned = vimport.assign_missing_reactor_ids(working)
        return self.save(vimport.fill_missing_search_names(out), principal), assigned


class ResultsRepository(Repository):
    """Append-only log of saved assessment results."""

    def load(self) -> pd.DataFrame:
        return fresh_csv(self.path).copy()

    def append(self, rows: list[dict], principal: Principal) -> int:
        """Validate and append saved results; returns the new record count."""
        authorize(principal, self.table)
        return append_csv(pd.DataFrame([self.validate(r) for r in rows],
                                       columns=self.columns), self.path)

    def clear(self, df: pd.DataFrame, principal: Principal) -> pd.DataFrame:
        """Remove every record, keeping the header."""
        return self.save(df.iloc[0:0], principal)


def filter_results(df: pd.DataFrame, reactors=None, reactions=None, fluids=None) -> pd.DataFrame:
    out = df
    for col, sel in (("reactor", reactors), ("reaction", reactions), ("fluid", fluids)):
        if sel and col in out.columns:
            out = out[out[col].astype(str).isin([str(s) for s in sel])]
    return out


def result_counts(df: pd.DataFrame) -> tuple[int, int, int]:
    """(reaction-limited, potentially sensitive, mixing-sensitive/limited) records."""
    if "Assessment" not in df.columns or df.empty:
        return 0, 0, 0
    a = df["Assessment"].astype(str)
    limited = a.str.contains("mixing-limited|Mixing-sensitive", case=False)
    potential = ~limited & a.str.contains("Potentially sensitive", case=False)
    n_limited, n_potential = int(limited.sum()), int(potential.sum())
    return len(a) - n_limited - n_potential, n_potential, n_limited


def _library_solvent(name: str) -> str | None:
    if is_known_solvent(name):
        return f"'{name}' is already in the solvent library — no need to add it."
    return None


PARTICLE_COLUMNS = ["particle_name", "rho_p_kg_m3", "d10_um", "d50_um", "d90_um",
                    "shape_description", "shape_factor", "notes"]
REACTION_COLUMNS = ["reaction_name", "type", "order", "k_value", "k_units", "C0_mol_L",
                    "t_rxn_s", "T_C", "solvent", "delta_H_kJ_mol", "class", "notes",
                    "reaction_scheme"]
FLUID_COLUMNS = ["fluid_name", "rho_kg_m3", "mu_Pa_s", "D_mol_m2_s", "surface_tension_N_m",
                 "notes", "Cp_J_per_kgK", "k_W_per_mK", "hsp_d", "hsp_p", "hsp_h"]

reactors = ReactorRepository("reactors", DATA_DIR / "reactors.csv", ["reactor_name"],
                             "reactor_name", "vessel", ReactorRecord)
reactions = Repository("reactions", DATA_DIR / "reactions.csv", REACTION_COLUMNS,
                       "reaction_name", "reaction", ReactionRecord,
                       normalize=normalize_reactions)
particles = Repository("particles", DATA_DIR / "particles.csv", PARTICLE_COLUMNS,
                       "particle_name", "particle", ParticleRecord)
fluids = Repository("fluids", DATA_DIR / "fluids.csv", FLUID_COLUMNS, "fluid_name",
                    "custom fluid", FluidRecord, reserved=_library_solvent)
results = ResultsRepository("recorded_results", DATA_DIR / "recorded_results.csv", RESULT_COLUMNS,
                            "reactor", "record", RecordedResult)

REPOSITORIES = {r.table: r for r in (reactors, reactions, particles, fluids, results)}
