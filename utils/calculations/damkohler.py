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
"""

import numpy as np


def characteristic_reaction_time(order: str, k: float, C0: float = 0.0,
                                 t_specified: float = 0.0) -> tuple[float, float, str]:
    """Return (t_rxn, t_90, basis) for a reaction of the given order.

    ``t_rxn`` is the characteristic (initial-rate) time used in every Damköhler
    number: 1/k (1st / pseudo-1st order), 1/(k·C0) (2nd / pseudo-2nd order,
    equimolar) or C0/k (zero order). ``t_90`` is the time to 90 % conversion, a
    process-window figure that is 2.3–9x LONGER and therefore NOT conservative for
    mixing sensitivity (Da = t_mix / t_rxn is largest for the shortest t_rxn).
    A directly specified time is returned unchanged for both (its conversion
    basis is unknown). All times in seconds; 0.0 when undeterminable.
    """
    if t_specified and t_specified > 0:
        return float(t_specified), float(t_specified), "specified directly"
    if not k or k <= 0:
        return 0.0, 0.0, ""
    o = str(order).strip()
    if o in ("1", "pseudo-1"):
        return 1.0 / k, np.log(10.0) / k, "1/k; 90% conversion = 2.303/k"
    if o in ("2", "pseudo-2") and C0 > 0:
        return 1.0 / (k * C0), 9.0 / (k * C0), "1/(k·C₀); 90% conversion = 9/(k·C₀)"
    if o == "0" and C0 > 0:
        return C0 / k, 0.9 * C0 / k, "C₀/k; 90% conversion = 0.9·C₀/k"
    return 0.0, 0.0, "fallback (order/C₀ incomplete)"

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
