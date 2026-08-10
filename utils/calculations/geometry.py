"""Bottom-dish geometry helpers and liquid height estimation.

UNIT CONVENTION
---------------
D_tank, H, heights in m; dish volume in m^3; fill volume input in litres
(converted internally to m^3).

REFERENCES (per function)
-------------------------
    dish_geometry, estimate jacket dish factors
        Torispherical coefficients (h = 0.1935 D, V = 0.0847 D^3) and conical/
        hemispherical forms are standard dished-head geometry.
        Ref: DIN 28011 (torispherical) / DIN 28013 (semi-ellipsoidal) heads;
        ASME F&D head geometry.  [NOT in context/ - verify]
    liquid_height_from_volume
        Geometric volume-to-height inversion.  [definition]
    parse_cone_angle_deg, cone_depth
        Conical bottom depth from a cone angle (measured from the horizontal)
        parsed from the dish label, e.g. "Conical 60°".  Defaults to 45°
        (depth = D/2, the standard 90°-included cone).  [definition]
"""

import re

import numpy as np


def parse_cone_angle_deg(dish_type: str, default: float = 45.0) -> float:
    """Cone wall angle from the horizontal (deg), parsed from a dish label.

    A number in the label (``"Conical 60°"``, ``"Cone 30 deg"``) is taken as the
    angle the cone wall makes with the horizontal plane; steeper -> deeper cone.
    Falls back to ``default`` (45° -> depth = D/2) when no valid angle is given.
    """
    s = str(dish_type).lower()
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:°|deg)", s)
    if m is None:
        m = re.search(r"(\d+(?:\.\d+)?)", s)
    if m is not None:
        ang = float(m.group(1))
        if 5.0 <= ang <= 85.0:
            return ang
    return default


def cone_depth(D_tank: float, dish_type: str = "", default_angle_deg: float = 45.0) -> float:
    """Conical bottom depth (m) for a tank ID and its (parsed) cone angle."""
    if D_tank <= 0:
        return 0.0
    ang = parse_cone_angle_deg(dish_type, default_angle_deg)
    return (D_tank / 2.0) * np.tan(np.radians(ang))


def dish_geometry(D_tank: float, dish_type: str = "") -> tuple[float, float]:
    """Return (V_dish_m3, h_dish_m) for a vessel bottom dish."""
    if D_tank <= 0:
        return 0.0, 0.0

    dish = str(dish_type).lower().strip() if dish_type else ""

    if "conic" in dish:
        h_dish = cone_depth(D_tank, dish)
        V_dish = np.pi / 12 * D_tank**2 * h_dish
    elif "torisph" in dish or "din" in dish or "dished" in dish:
        h_dish = 0.1935 * D_tank
        V_dish = 0.0847 * D_tank**3
    else:
        h_dish = D_tank / 4
        V_dish = np.pi * D_tank**3 / 24

    return V_dish, h_dish


def liquid_height_from_volume(V_L_litres: float, D_tank: float,
                              H_max: float, dish_type: str = "") -> float:
    """Compute liquid height (m) from fill volume, accounting for bottom dish."""
    if D_tank <= 0 or V_L_litres <= 0:
        return 0.0

    V_L_m3 = V_L_litres / 1000.0
    V_dish, h_dish = dish_geometry(D_tank, dish_type)
    A_cs = np.pi / 4 * D_tank**2

    if V_L_m3 <= V_dish and V_dish > 0:
        frac = V_L_m3 / V_dish
        return frac * h_dish
    else:
        H_cyl = (V_L_m3 - V_dish) / A_cs if A_cs > 0 else 0.0
        H_total = h_dish + H_cyl
        return min(H_total, H_max) if H_max > 0 else H_total
