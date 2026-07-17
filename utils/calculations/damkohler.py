"""Damkohler numbers and reaction time helpers.

UNIT CONVENTION
---------------
All characteristic times (t_blend, t_micro, t_rxn) in seconds; mass-transfer
coefficients kLa in 1/s.  All Damkohler numbers are dimensionless.

REFERENCES (per function)
-------------------------
    damkohler_macro (Da = theta_blend / t_rxn),
    damkohler_micro (Da = t_E / t_rxn)
        Ref: Baldyga & Bourne, *Turbulent Mixing and Chemical Reactions*
        (1999); Myerson (2019) Ch. 8 (Baldyga).  [in context/]
    damkohler_gl, damkohler_sl (Da = 1/(kLa t_rxn))
        Two-film mass-transfer vs reaction timescale ratio.
        Ref: standard two-film theory (e.g. Levenspiel, *Chemical Reaction
        Engineering*, 1999).  [NOT in context/ - verify]
    mixing_sensitivity_assessment
        Qualitative Da thresholds (0.01/0.1/1/10) are heuristic interpretation
        bands, not a published classification.  [SOURCE MISSING - heuristic]
    half_life_first_order, reaction_time_second_order
        Standard chemical-kinetics definitions.  [textbook]
"""

import numpy as np


def damkohler_macro(t_blend: float, t_rxn: float) -> float:
    """Da_macro = θ_blend / t_rxn"""
    if t_rxn == 0:
        return np.inf
    return t_blend / t_rxn


def damkohler_micro(t_micro: float, t_rxn: float) -> float:
    """Da_micro = t_E / t_rxn"""
    if t_rxn == 0:
        return np.inf
    return t_micro / t_rxn


def damkohler_gl(kLa: float, t_rxn: float) -> float:
    """Gas-liquid Damköhler number  Da_GL = 1 / (kLa · t_rxn)."""
    if kLa <= 0:
        return 0.0
    if t_rxn <= 0:
        return np.inf
    return 1.0 / (kLa * t_rxn)


def damkohler_sl(kLa_SL: float, t_rxn: float) -> float:
    """Solid-liquid Damköhler number  Da_SL = 1 / (kLa_SL · t_rxn)."""
    if kLa_SL <= 0:
        return 0.0
    if t_rxn <= 0:
        return np.inf
    return 1.0 / (kLa_SL * t_rxn)


def mixing_sensitivity_assessment(Da_macro: float, Da_micro: float,
                                   Da_GL: float = 0.0,
                                   Da_SL: float = 0.0) -> str:
    """Qualitative assessment based on Damköhler numbers."""
    labels = []
    for name, Da in [("Macro", Da_macro), ("Micro", Da_micro)]:
        if Da < 0.01:
            labels.append(f"{name}: Reaction-limited (Da={Da:.3g})")
        elif Da < 0.1:
            labels.append(f"{name}: Likely insensitive (Da={Da:.3g})")
        elif Da < 1:
            labels.append(f"{name}: Potentially sensitive (Da={Da:.3g})")
        elif Da < 10:
            labels.append(f"{name}: Mixing-sensitive (Da={Da:.3g})")
        else:
            labels.append(f"{name}: Strongly mixing-limited (Da={Da:.3g})")
    if Da_GL > 0:
        if Da_GL < 0.01:
            labels.append(f"G-L: Transfer-fast (Da_GL={Da_GL:.3g})")
        elif Da_GL < 0.1:
            labels.append(f"G-L: Likely insensitive (Da_GL={Da_GL:.3g})")
        elif Da_GL < 1:
            labels.append(f"G-L: Potentially transfer-limited (Da_GL={Da_GL:.3g})")
        elif Da_GL < 10:
            labels.append(f"G-L: Transfer-limited (Da_GL={Da_GL:.3g})")
        else:
            labels.append(f"G-L: Strongly transfer-limited (Da_GL={Da_GL:.3g})")
    if Da_SL > 0:
        if Da_SL < 0.01:
            labels.append(f"S-L: Transfer-fast (Da_SL={Da_SL:.3g})")
        elif Da_SL < 0.1:
            labels.append(f"S-L: Likely insensitive (Da_SL={Da_SL:.3g})")
        elif Da_SL < 1:
            labels.append(f"S-L: Potentially transfer-limited (Da_SL={Da_SL:.3g})")
        elif Da_SL < 10:
            labels.append(f"S-L: Transfer-limited (Da_SL={Da_SL:.3g})")
        else:
            labels.append(f"S-L: Strongly transfer-limited (Da_SL={Da_SL:.3g})")
    return " | ".join(labels)


def half_life_first_order(k: float) -> float:
    """t_1/2 = ln2 / k"""
    if k <= 0:
        return np.inf
    return np.log(2) / k


def reaction_time_second_order(k: float, C0: float) -> float:
    """Characteristic time = 1 / (k C0)"""
    if k * C0 <= 0:
        return np.inf
    return 1.0 / (k * C0)
