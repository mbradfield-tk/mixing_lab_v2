"""Regression tests for the solvent miscibility / reactivity screening.

These guard the hand-maintained lookup tables in ``utils.solvent_properties``.
The tables are keyed by ``frozenset`` of canonical solvent names, so a typo in a
name does not raise -- it silently never matches, and the pair then falls
through to the "Miscible (known pair)" default.  For a reactive pair that turns
a safety warning into a clean bill of health, so the name check below matters
more than it looks.

Run with:  pytest tests/test_miscibility.py
"""

import os
import re
import sys
from itertools import combinations

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.solvent_properties import (  # noqa: E402
    SOLVENT_DB,
    _IMMISCIBLE,
    _PARTIALLY_MISCIBLE,
    _REACTIVE,
    miscibility_assessment,
    resolve_solvent_name,
    solvent_miscibility,
)

ALL_NAMES = sorted(SOLVENT_DB)
ALL_PAIRS = list(combinations(ALL_NAMES, 2))
TABLES = {
    "_IMMISCIBLE": _IMMISCIBLE,
    "_PARTIALLY_MISCIBLE": _PARTIALLY_MISCIBLE,
    "_REACTIVE": _REACTIVE,
}


# --------------------------------------------------------------------------
# Table integrity
# --------------------------------------------------------------------------

@pytest.mark.parametrize("table_name", sorted(TABLES))
def test_lookup_names_are_canonical(table_name):
    """Every name must be a canonical SOLVENT_DB key, or it never matches."""
    bad = sorted({
        n for pair in TABLES[table_name] for n in pair if n not in SOLVENT_DB
    })
    assert not bad, f"{table_name} references non-canonical names: {bad}"


@pytest.mark.parametrize("table_name", sorted(TABLES))
def test_lookup_pairs_are_two_distinct_solvents(table_name):
    """A frozenset of a self-pair collapses to one element and never matches."""
    bad = [sorted(p) for p in TABLES[table_name] if len(p) != 2]
    assert not bad, f"{table_name} has non-pair entries: {bad}"


def test_tables_are_mutually_exclusive():
    """A pair in two tables would resolve by branch order, hiding one verdict."""
    overlaps = []
    for a, b in combinations(sorted(TABLES), 2):
        # set(dict) yields its keys, so this works for both table shapes.
        for pair in set(TABLES[a]) & set(TABLES[b]):
            overlaps.append((a, b, sorted(pair)))
    assert not overlaps, f"pairs listed in multiple tables: {overlaps}"


def test_every_reactive_pair_has_a_reason():
    missing = [sorted(p) for p, reason in _REACTIVE.items() if not reason.strip()]
    assert not missing, f"reactive pairs with empty reason: {missing}"


# --------------------------------------------------------------------------
# solvent_miscibility contract
# --------------------------------------------------------------------------

REQUIRED_KEYS = {"miscible", "assessment", "source", "Ra", "hsp_1", "hsp_2"}


@pytest.mark.parametrize("a,b", ALL_PAIRS, ids=lambda v: v)
def test_result_shape_and_symmetry(a, b):
    """Order of arguments must not change the verdict."""
    fwd, rev = solvent_miscibility(a, b), solvent_miscibility(b, a)
    assert REQUIRED_KEYS <= fwd.keys(), f"missing keys: {REQUIRED_KEYS - fwd.keys()}"
    assert fwd["miscible"] == rev["miscible"]
    assert fwd["assessment"] == rev["assessment"]
    assert fwd.get("reactive") == rev.get("reactive")


@pytest.mark.parametrize("name", ALL_NAMES)
def test_identity_is_miscible(name):
    m = solvent_miscibility(name, name)
    assert m["miscible"] is True
    assert m["Ra"] == 0.0
    assert not m.get("reactive")


# --------------------------------------------------------------------------
# Reactive pairs
# --------------------------------------------------------------------------

@pytest.mark.parametrize("pair", sorted(_REACTIVE, key=sorted), ids=lambda p: " + ".join(sorted(p)))
def test_reactive_pairs_flagged(pair):
    a, b = sorted(pair)
    m = solvent_miscibility(a, b)
    assert m.get("reactive") is True
    # Reactive pairs must also read as non-miscible so callers that only check
    # `miscible` still refuse to average properties across them.
    assert m["miscible"] is False
    assert m["assessment"].startswith("⚠️ Reactive —")
    assert m["source"] == "lookup"


def test_reactive_assessments_are_specific():
    """Each reactive pair should explain what happens, not repeat one blurb."""
    texts = [solvent_miscibility(*sorted(p))["assessment"] for p in _REACTIVE]
    assert len(set(texts)) > 1, "all reactive pairs share one generic message"
    for t in texts:
        reason = t.split("—", 1)[1].strip()
        assert len(reason) > 10, f"reason too terse: {t!r}"


@pytest.mark.parametrize("a,b", [
    ("Trifluoroacetic Anhydride", "Water"),
    ("Trifluoroacetic Anhydride", "Methanol"),
    ("Trifluoroacetic Anhydride", "DMSO"),
    ("Trifluoroacetic Anhydride", "DMF"),
    ("Trifluoroacetic Anhydride", "NMP"),
    ("Trifluoroacetic Anhydride", "Acetic Acid"),
    ("36% HCl (aq)", "6 M NaOH (aq)"),
    ("36% HCl (aq)", "47% K2CO3 (aq)"),
    ("Acetic Acid", "6 M NaOH (aq)"),
    ("6 M NaOH (aq)", "DMSO"),
    ("6 M NaOH (aq)", "DMF"),
    ("6 M NaOH (aq)", "NMP"),
    ("6 M NaOH (aq)", "Chloroform"),
])
def test_known_incompatibilities_are_not_reported_miscible(a, b):
    """These must never regress to the 'Miscible (known pair)' default."""
    m = solvent_miscibility(a, b)
    assert m.get("reactive") is True, f"{a} + {b} reported as {m['assessment']!r}"


def test_stable_coexisting_pair_is_not_reactive():
    """TFA/TFAA mixtures are a standard reagent system -- guard over-flagging."""
    m = solvent_miscibility("Trifluoroacetic Acid", "Trifluoroacetic Anhydride")
    assert not m.get("reactive")


# --------------------------------------------------------------------------
# Phase behaviour
# --------------------------------------------------------------------------

@pytest.mark.parametrize("pair", sorted(_PARTIALLY_MISCIBLE, key=sorted),
                         ids=lambda p: " + ".join(sorted(p)))
def test_partially_miscible_reports_not_miscible(pair):
    """Partial miscibility must trip the same phase-split warning as immiscible."""
    m = solvent_miscibility(*sorted(pair))
    assert m["miscible"] is False
    assert "artial" in m["assessment"]


@pytest.mark.parametrize("pair", sorted(_IMMISCIBLE, key=sorted),
                         ids=lambda p: " + ".join(sorted(p)))
def test_immiscible_reports_not_miscible(pair):
    m = solvent_miscibility(*sorted(pair))
    assert m["miscible"] is False
    assert not m.get("reactive")


@pytest.mark.parametrize("organic", [
    "Toluene", "Hexane", "Heptane", "DCM", "Chloroform", "Diethyl Ether",
    "MTBE", "Ethyl Acetate", "2-MeTHF", "MEK",
])
@pytest.mark.parametrize("aqueous", [
    "Water", "36% HCl (aq)", "6 M NaOH (aq)", "47% K2CO3 (aq)",
])
def test_aqueous_organic_pairs_split(aqueous, organic):
    """Aqueous phases must not be reported as fully miscible with these."""
    m = solvent_miscibility(aqueous, organic)
    assert m["miscible"] is not True, \
        f"{aqueous} + {organic} reported {m['assessment']!r}"


@pytest.mark.parametrize("alkane", ["Hexane", "Heptane"])
def test_acetic_acid_alkane_is_not_fully_miscible(alkane):
    """AcOH/alkane sits near its UCST at RT; must not read as a clean blend."""
    m = solvent_miscibility("Acetic Acid", alkane)
    assert m["miscible"] is False
    assert not m.get("reactive")


@pytest.mark.parametrize("ether", ["Diethyl Ether", "MTBE"])
def test_dmso_ether_is_immiscible(ether):
    """Standard miscibility charts mark DMSO immiscible with ethers."""
    m = solvent_miscibility("DMSO", ether)
    assert m["miscible"] is False
    assert not m.get("reactive")


@pytest.mark.parametrize("amide", ["DMF", "NMP"])
def test_k2co3_salts_out_amides(amide):
    m = solvent_miscibility("47% K2CO3 (aq)", amide)
    assert m["miscible"] is False
    assert not m.get("reactive")


def test_borderline_hansen_band_is_not_miscible():
    """The 15-25 MPa^0.5 band is a phase-split risk, not a clean blend."""
    assert miscibility_assessment(20.0)["miscible"] is False
    assert miscibility_assessment(5.0)["miscible"] is True
    assert miscibility_assessment(40.0)["miscible"] is False


def test_alias_resolves_into_reactive_lookup():
    """Aliases must reach the same verdict as canonical names."""
    canonical = "Isopropanol (IPA)"
    alias = next(
        (a for a in ("IPA", "isopropanol", "2-propanol", "iso-propanol")
         if resolve_solvent_name(a) == canonical),
        None,
    )
    if alias is None:
        pytest.skip("no alias registered for Isopropanol (IPA)")
    direct = solvent_miscibility(canonical, "Trifluoroacetic Anhydride")
    via_alias = solvent_miscibility(alias, "Trifluoroacetic Anhydride")
    assert via_alias["assessment"] == direct["assessment"]
    assert via_alias.get("reactive") == direct.get("reactive")


def test_unknown_fluid_reports_unknown_not_miscible():
    m = solvent_miscibility("Water", "Totally Made Up Fluid XYZ")
    assert m["miscible"] is None
    assert m["source"] == "none"


def test_custom_fluid_hsp_lookup_tolerates_whitespace():
    """A stray space in a CSV-edited name must not silently drop HSP data."""
    pd = pytest.importorskip("pandas")
    custom = pd.DataFrame([{
        "fluid_name": "  My Brine ", "hsp_d": 16.0, "hsp_p": 14.0, "hsp_h": 30.0,
    }])
    m = solvent_miscibility("Water", "My Brine", custom_fluids=custom)
    assert m["source"] == "Hansen estimate"
    assert m["Ra"] is not None


# --------------------------------------------------------------------------
# Status-line helper in the blend page
# --------------------------------------------------------------------------

def _load_join_pairs():
    """Import _join_pairs without importing taipy (which the page pulls in)."""
    path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "pages", "fluid_database.py",
    )
    with open(path, encoding="utf-8") as fh:
        src = fh.read()
    match = re.search(r"^def _join_pairs.*?(?=^def |\Z)", src, re.S | re.M)
    assert match, "_join_pairs not found in pages/fluid_database.py"
    ns = {}
    exec(match.group(0), ns)
    return ns["_join_pairs"]


def test_join_pairs_truncates_long_lists():
    join = _load_join_pairs()
    assert join(["a/b"]) == "a/b"
    assert join(["a/b", "c/d"]) == "a/b; c/d"
    assert join(["a/b", "c/d", "e/f"]) == "a/b; c/d; e/f"
    assert join(["a/b", "c/d", "e/f", "g/h"]) == "a/b; c/d; e/f; +1 more"
    assert join([f"p{i}" for i in range(10)]).endswith("+7 more")
