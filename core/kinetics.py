"""Reaction kinetics defaults and characteristic reaction times."""
from __future__ import annotations

import pandas as pd

from core.records import reaction_row, sf
from utils.calculations import characteristic_reaction_time

ORDER_OPTIONS = ["0", "1", "2", "pseudo-1", "pseudo-2"]


def kinetics_defaults(name: str) -> dict:
    """Database kinetics for a reaction: {order, k, C0, t_rxn, T, dH, solvent}.

    ``t_rxn`` is the *specified* time from the database (0 when it should be
    derived from k); unknown orders fall back to first order.
    """
    row = reaction_row(name) if name else pd.Series(dtype=object)
    order = str(row.get("order", "1") or "1")
    if order not in ORDER_OPTIONS:
        order = "1"
    return {"order": order, "k": sf(row.get("k_value")), "C0": sf(row.get("C0_mol_L")),
            "t_rxn": sf(row.get("t_rxn_s")), "T": sf(row.get("T_C"), 25.0),
            "dH": sf(row.get("delta_H_kJ_mol")),
            "solvent": str(row.get("solvent", "") or "")}


def timescale_profile(order: str, k: float, C0: float,
                      t_specified: float = 0.0) -> tuple[float, float, str]:
    """(characteristic t_rxn, 90 %-conversion time, basis) — see characteristic_reaction_time."""
    return characteristic_reaction_time(order, k, C0, t_specified)


def effective_t_rxn(order: str, k: float, C0: float, t_specified: float,
                    fallback: float = 0.0) -> float:
    """Characteristic reaction time, or ``fallback`` when the kinetics are incomplete."""
    return characteristic_reaction_time(order, k, C0, t_specified)[0] or fallback
