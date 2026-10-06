"""Coded option sets shared by core, the API contracts and the UIs.

The enum value is the stable *code* used by core and the API; ``label`` is the
default UI text. A UI may show its own wording by passing ``labels={member: text}``
to :meth:`Coded.labels` / :meth:`Coded.from_label`; codes never change.
"""
from __future__ import annotations

from enum import StrEnum


class Coded(StrEnum):
    label: str

    def __new__(cls, code: str, label: str):
        obj = str.__new__(cls, code)
        obj._value_ = code
        obj.label = label
        return obj

    @classmethod
    def labels(cls, labels: dict | None = None) -> list[str]:
        return [(labels or {}).get(m, m.label) for m in cls]

    @classmethod
    def from_label(cls, label, default=None, labels: dict | None = None):
        """Member whose (UI) label is ``label``; ``default`` for placeholders/unknowns."""
        return next((m for m in cls if (labels or {}).get(m, m.label) == label), default)


class Toggle(Coded):
    OFF = "off", "Off"
    ON = "on", "On"


def is_on(value) -> bool:
    """True for an On toggle label (or a legacy boolean True)."""
    return value is True or Toggle.from_label(value) is Toggle.ON


# --- Vessel / operating point ----------------------------------------------
class CorrSource(Coded):
    # Codes are the correlation-registry mode keys (utils.rom_registry).
    LITERATURE = "Literature", "Empirical (literature)"
    EXPERIMENTAL = "Experimental", "Experimental"
    ROM = "ROM", "Reduced-order (CFD)"


class FeedLocation(Coded):
    NEAR_IMPELLER = "near_impeller", "Near impeller"
    BULK = "bulk", "Bulk (mid-liquid)"
    SURFACE = "surface", "Surface"


class GasTransfer(Coded):
    HEADSPACE = "headspace", "Headspace"
    SPARGING = "sparging", "Sparging"


class Coalescence(Coded):
    COALESCING = "coalescing", "Coalescing"
    NON_COALESCING = "non_coalescing", "Non-coalescing"


# --- Bourne Protocol ---------------------------------------------------------
class CenterMode(Coded):
    DEFAULT = "default", "Default (0.2 W/kg)"
    CUSTOM_PM = "custom_pm", "Custom P/m"
    CUSTOM_RPM = "custom_rpm", "Custom RPM"


class FeedBasis(Coded):
    RATE = "rate", "Feed rate"
    TIME = "time", "Feed time"


class Mechanism(Coded):
    # Codes match the Bourne results CSV and report wording, so they stay capitalised.
    MICROMIXING = "Micromixing", "Micromixing"
    MESOMIXING = "Mesomixing", "Mesomixing"
    MACROMIXING = "Macromixing", "Macromixing"


BOURNE_TESTS = {1: "Test 1", 2: "Test 2", 3: "Test 3"}


def bourne_test_number(label: str) -> int:
    return next(n for n, lbl in BOURNE_TESTS.items() if lbl == label)


# --- Reaction Sensitivity Protocol -----------------------------------------
class BourneStatus(Coded):
    SKIP = "skip", "Not run - skip pre-screen"
    CONFIRMED = "confirmed", "Ran - sensitivity confirmed"
    INSENSITIVE = "insensitive", "Ran - no sensitivity at lab scale"
    INCONCLUSIVE = "inconclusive", "Ran - inconclusive (Test 1 not completed)"


class Kinetics(Coded):
    AVAILABLE = "available", "Yes - kinetics available in the database"
    APPROXIMATE = "approximate", "Approximate - use a similar reaction as a proxy"
    DECLINED = "declined", "No - kinetics not yet available"


class Phase(Coded):
    LIQUID = "liquid", "Liquid"
    SOLID = "solid", "Solid"
    GAS = "gas", "Gas"


class Competing(Coded):
    YES = "yes", "Yes"
    NO = "no", "No"
    NOT_SURE = "not_sure", "Not sure"


class DhAction(Coded):
    CALORIMETRY = "calorimetry", "Perform calorimetry - measure ΔH experimentally"
    ESTIMATE = "estimate", "Estimate ΔH from a similar reaction"


class DhBasis(Coded):
    MEASURED = "measured", "Yes - measured"
    ESTIMATED = "estimated", "No - estimated"
