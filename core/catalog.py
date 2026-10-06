"""Option lists for the UI / API (``GET /options``): database names, the solvent
library and the correlation sources available per vessel. Read live from the
repositories, so lists reflect the current CSVs."""
from __future__ import annotations

from core import repositories as repos
from core import tables
from core.records import sf
from utils.rom_registry import available_modes, available_modes_multi
from utils.solvent_properties import is_known_solvent, list_solvents, resolve_solvent_name

__all__ = ["available_modes", "available_modes_multi", "is_known_solvent", "resolve_solvent_name",
           "solvent_names", "custom_fluid_names", "fluid_names", "fluid_names_grouped",
           "reactor_names", "reaction_names", "particle_names", "reactions_with_enthalpy"]

solvent_names = list_solvents


def custom_fluid_names() -> list[str]:
    return repos.fluids.names(repos.fluids.shared())


def fluid_names() -> list[str]:
    """Library solvents and custom fluids, alphabetical, without duplicates."""
    return sorted(set(solvent_names()) | set(custom_fluid_names()))


def fluid_names_grouped() -> list[str]:
    """Library solvents (alphabetical) followed by the custom fluids in table order."""
    return solvent_names() + custom_fluid_names()


def _unique_sorted(names: list[str]) -> list[str]:
    return sorted(set(names))


def reactor_names(sort: bool = True) -> list[str]:
    names = repos.reactors.names(repos.reactors.shared())
    return _unique_sorted(names) if sort else names


def particle_names(sort: bool = True) -> list[str]:
    names = repos.particles.names(repos.particles.shared())
    return _unique_sorted(names) if sort else names


def reaction_names(class_value: str | None = None) -> list[str]:
    """Reaction names; ``class_value`` "yes" = reaction classes, "no" = measured kinetics."""
    return tables.reaction_names(repos.reactions.shared(), class_value)


def reactions_with_enthalpy() -> list[str]:
    df = repos.reactions.shared()
    if "delta_H_kJ_mol" not in df.columns:
        return []
    hits = df[df["delta_H_kJ_mol"].apply(lambda v: sf(v) != 0.0)]
    return sorted(hits["reaction_name"].dropna().astype(str).tolist())
