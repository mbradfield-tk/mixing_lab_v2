"""Liquid-phase stratification of a solvent blend from pairwise miscibility."""
from __future__ import annotations


def settled_phases(comp_props: list[dict], pair_misc: dict) -> tuple[list[dict], bool]:
    """Partition blend components into the fewest mutually-miscible liquid phases.

    ``comp_props`` items carry ``name``, ``vol_frac``, ``mass_frac`` and ``rho_kg_m3``;
    ``pair_misc`` maps ``(name_a, name_b)`` to ``{"miscible": True | False | None}``.
    Exhaustive search with pruning — order-independent, unlike a greedy pass where a
    bridging solvent picked early can block the correct grouping.

    Returns (phases sorted densest first as ``{label, vol, rho}``, whether any
    cross-phase pair is only *unknown* rather than immiscible).
    """
    def _misc(a: str, b: str):
        m = pair_misc.get((a, b)) or pair_misc.get((b, a))
        return m["miscible"] if m else None

    best: list[list[dict]] = [[cp] for cp in comp_props]

    def _assign(i: int, groups: list[list[dict]]) -> None:
        nonlocal best
        if len(groups) >= len(best):
            return  # cannot beat the best partition found so far
        if i == len(comp_props):
            best = [g[:] for g in groups]
            return
        cp = comp_props[i]
        for g in groups:
            if all(_misc(cp["name"], other["name"]) is True for other in g):
                g.append(cp)
                _assign(i + 1, groups)
                g.pop()
        groups.append([cp])
        _assign(i + 1, groups)
        groups.pop()

    _assign(0, [])

    phase_of = {cp["name"]: i for i, g in enumerate(best) for cp in g}
    phases = []
    for members in best:
        vol = sum(cp["vol_frac"] for cp in members)
        mass = sum(cp["mass_frac"] for cp in members)
        rho = mass / sum(cp["mass_frac"] / cp["rho_kg_m3"] for cp in members)
        phases.append({"label": " + ".join(cp["name"] for cp in members),
                       "vol": vol, "rho": rho})
    phases.sort(key=lambda p: p["rho"], reverse=True)

    unknown_split = any(
        m["miscible"] is None and phase_of[n1] != phase_of[n2]
        for (n1, n2), m in pair_misc.items())
    return phases, unknown_split
