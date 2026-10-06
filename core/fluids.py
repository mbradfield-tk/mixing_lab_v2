"""Fluid Database calculations: solvent properties at T/P, custom-fluid lookups and
liquid blends (mixing rules, pairwise miscibility, settled phases, dispersion screen)."""
from __future__ import annotations

from itertools import combinations

import numpy as np
import pandas as pd

from core.miscibility import settled_phases
from utils.calculations.liquid_liquid import minimum_dispersion_speed, phase_separation_check
from utils.solvent_properties import (
    SOLVENT_DB, boiling_point_at_pressure, get_properties, is_known_solvent, solvent_info_table,
    solvent_miscibility,
)

PROP_KEYS = ("rho_kg_m3", "mu_Pa_s", "D_mol_m2_s", "surface_tension_N_m",
             "Cp_J_per_kgK", "k_W_per_mK")


def library_table() -> list[dict]:
    """Built-in solvent library at 25 °C / 1 atm (one row per solvent)."""
    return solvent_info_table()


def component_props(name: str, custom: pd.DataFrame, T_C: float = 25.0) -> dict | None:
    """Mixing-rule properties of a library solvent (at ``T_C``) or a custom fluid (fixed)."""
    if is_known_solvent(name):
        p = get_properties(name, T_C)
        return {k: p[k] for k in PROP_KEYS}
    if not custom.empty and name in custom["fluid_name"].astype(str).values:
        row = custom[custom["fluid_name"].astype(str) == name].iloc[0]
        try:
            return {
                "rho_kg_m3": float(row["rho_kg_m3"]),
                "mu_Pa_s": float(row["mu_Pa_s"]),
                "D_mol_m2_s": float(row["D_mol_m2_s"]),
                "surface_tension_N_m": float(row["surface_tension_N_m"]),
                "Cp_J_per_kgK": float(row.get("Cp_J_per_kgK", 4182.0) or 4182.0),
                "k_W_per_mK": float(row.get("k_W_per_mK", 0.607) or 0.607),
            }
        except (TypeError, ValueError):  # non-numeric cell -> treat as missing
            return None
    return None


def solvent_state(name: str, P_atm: float, T_C: float) -> dict:
    """Library solvent properties at (T, P) plus boiling/melting points and the liquid range."""
    if name not in SOLVENT_DB:
        raise LookupError(f"Unknown solvent '{name}'.")
    sd = SOLVENT_DB[name]
    props = get_properties(name, T_C, P_atm)
    bp_at_p = boiling_point_at_pressure(P_atm, sd)
    return {**props, "bp_at_P_C": bp_at_p, "bp_C": sd.bp_C, "liquid_range_C": (sd.mp_C, bp_at_p)}


def _fractions(comp_props: list[dict], volume_basis: bool) -> None:
    if volume_basis:
        for cp in comp_props:
            cp["vol_frac"] = cp["input"]
        masses = [cp["vol_frac"] * cp["rho_kg_m3"] for cp in comp_props]
        tm = sum(masses)
        for cp, m in zip(comp_props, masses):
            cp["mass_frac"] = m / tm
    else:
        for cp in comp_props:
            cp["mass_frac"] = cp["input"]
        vols = [cp["mass_frac"] / cp["rho_kg_m3"] for cp in comp_props]
        tv = sum(vols)
        for cp, v in zip(comp_props, vols):
            cp["vol_frac"] = v / tv


def mixing_rules(comp_props: list[dict]) -> dict:
    """Blend properties from mass/volume fractions (literature mixing rules)."""
    return {
        "rho_kg_m3": 1.0 / sum(cp["mass_frac"] / cp["rho_kg_m3"] for cp in comp_props),
        "mu_Pa_s": float(np.exp(sum(cp["mass_frac"] * np.log(cp["mu_Pa_s"]) for cp in comp_props))),
        "D_mol_m2_s": float(np.exp(sum(cp["mass_frac"] * np.log(cp["D_mol_m2_s"])
                                       for cp in comp_props))),
        "surface_tension_N_m": sum(cp["vol_frac"] * cp["surface_tension_N_m"] for cp in comp_props),
        "Cp_J_per_kgK": sum(cp["mass_frac"] * cp["Cp_J_per_kgK"] for cp in comp_props),
        "k_W_per_mK": sum(cp["vol_frac"] * cp["k_W_per_mK"] for cp in comp_props),
    }


def _dispersion(comp_props: list[dict], pairs: list[dict], speed: float, d_imp: float,
                h_liquid: float, sigma_ll: float) -> list[dict]:
    """Preliminary dispersion screen for each immiscible pair (continuous = larger volume)."""
    by_name = {cp["name"]: cp for cp in comp_props}
    rows = []
    for pair in pairs:
        if pair["class"] != "immiscible":
            continue
        first, second = by_name[pair["a"]], by_name[pair["b"]]
        continuous, dispersed = ((first, second) if first["vol_frac"] >= second["vol_frac"]
                                 else (second, first))
        pair_fraction = first["vol_frac"] + second["vol_frac"]
        phi_d = dispersed["vol_frac"] / pair_fraction if pair_fraction > 0 else 0.0
        sep = phase_separation_check(
            max(speed, 0.0), max(d_imp, 0.0), max(h_liquid, 0.0),
            continuous["rho_kg_m3"], dispersed["rho_kg_m3"], continuous["mu_Pa_s"],
            max(sigma_ll, 0.0), phi_d)
        n_min = minimum_dispersion_speed(max(d_imp, 0.0), max(sigma_ll, 0.0),
                                         continuous["rho_kg_m3"], phi_d)
        rows.append({"pair": pair["label"], "We": sep["We"], "d32_um": sep["d32 (µm)"],
                     "N_min_1_s": n_min, "N_over_N_min": speed / n_min if n_min > 0 else 0.0,
                     "assessment": sep["Assessment"]})
    return rows


def blend(amounts: dict[str, float], volume_basis: bool, T_C: float, custom: pd.DataFrame,
          speed_1_s: float = 5.0, d_imp_m: float = 0.05, h_liquid_m: float = 1.0,
          sigma_ll_N_m: float = 0.01) -> dict:
    """Blend of ``amounts`` {component: amount} on a volume or mass basis.

    Returns {components (props + vol_frac/mass_frac), blend (mixed props), pairs
    [{label, a, b, class, misc}], phases (settled_phases result or None when a pair
    reacts), dispersion (immiscible pairs), status: reactive|immiscible|unknown|single_phase}.
    Raises ``ValueError`` for unusable input.
    """
    total = sum(amounts.values())
    if total <= 0:
        raise ValueError("Total amount must be > 0.")
    comp_props, missing = [], []
    for comp, amount in amounts.items():
        p = component_props(comp, custom, T_C)
        if p is None:
            missing.append(comp)
        else:
            comp_props.append({"name": comp, "input": amount / total, **p})
    if missing:
        raise ValueError(f"No properties for: {', '.join(missing)}")
    bad = [cp["name"] for cp in comp_props
           if not (cp["rho_kg_m3"] > 0 and cp["mu_Pa_s"] > 0 and cp["D_mol_m2_s"] > 0)]
    if bad:
        raise ValueError(f"Invalid properties (ρ, μ and D must be > 0) for: {', '.join(bad)}")
    _fractions(comp_props, volume_basis)

    pairs, pair_misc = [], {}
    for n1, n2 in combinations(list(amounts), 2):
        m = solvent_miscibility(n1, n2, custom_fluids=custom)
        pair_misc[(n1, n2)] = m
        cls = ("reactive" if m.get("reactive") else "immiscible" if m["miscible"] is False
               else "unknown" if m["miscible"] is None else "miscible")
        pairs.append({"label": f"{n1} / {n2}", "a": n1, "b": n2, "class": cls, "misc": m})

    classes = {p["class"] for p in pairs}
    status = next((c for c in ("reactive", "immiscible", "unknown") if c in classes),
                  "single_phase")
    return {
        "components": comp_props, "blend": mixing_rules(comp_props), "pairs": pairs,
        "phases": None if status == "reactive" else settled_phases(comp_props, pair_misc),
        "dispersion": (_dispersion(comp_props, pairs, speed_1_s, d_imp_m, h_liquid_m,
                                   sigma_ll_N_m) if "immiscible" in classes else []),
        "status": status,
    }
