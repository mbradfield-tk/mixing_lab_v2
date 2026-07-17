"""
Shared input-validation constants and helpers for the Mixing Lab app.

Centralises the bounds applied to user-facing ``st.number_input`` widgets so
the same limits are enforced consistently on every page, plus small helpers
for cross-field consistency checks (ascending order, duplicate names).
"""

# ── Temperature bounds (°C) ────────────────────────────────────────────
# Applied to every user-facing temperature input across the app.
TEMP_MIN_C = -100.0
TEMP_MAX_C = 300.0

# ── Pressure bounds (atm) — process inputs ─────────────────────────────
PRESSURE_MIN_ATM = 0.001
PRESSURE_MAX_ATM = 200.0

# ── Physical-property upper caps ───────────────────────────────────────
# Generous caps that only catch gross unit-entry mistakes (e.g. entering
# g/cm³ instead of kg/m³) without blocking exotic-but-real fluids.
RHO_MAX = 25000.0        # kg/m³   (denser than mercury ≈ 13 600)
MU_MAX = 1.0e5           # Pa·s    (extremely viscous melts/polymers)
CP_MAX = 1.0e5           # J/(kg·K)
K_THERMAL_MAX = 1000.0   # W/(m·K) (higher than any liquid)
SIGMA_MAX = 2.0          # N/m     (well above molten metals)
D_MOL_MAX = 1.0e-6       # m²/s

# ── Rotational speed ───────────────────────────────────────────────────
RPM_MAX = 100000.0


def check_ordered(items):
    """Validate that a sequence of labelled numbers is non-decreasing.

    Parameters
    ----------
    items : list[tuple[str, float | None]]
        Ordered ``(label, value)`` pairs that should satisfy
        ``v0 <= v1 <= ...``.  Entries whose value is ``None`` or ``<= 0``
        are skipped (treated as "not specified"), so partially-filled
        forms don't trip the check.

    Returns
    -------
    str | None
        An error message if the order is violated, else ``None``.
    """
    filtered = [(lbl, v) for lbl, v in items if v is not None and v > 0]
    for (l1, v1), (l2, v2) in zip(filtered, filtered[1:]):
        if v1 > v2:
            return f"{l1} ({v1:g}) must be ≤ {l2} ({v2:g})."
    return None


def name_exists(existing_names, name):
    """Return True if ``name`` (case-insensitive, trimmed) already exists.

    Parameters
    ----------
    existing_names : Iterable[str]
        Names already present in the target database.
    name : str
        Candidate name to check.
    """
    if not name:
        return False
    target = name.strip().lower()
    return any(str(n).strip().lower() == target for n in existing_names)
