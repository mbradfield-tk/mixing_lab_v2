"""Unit Converter page (Taipy).

Ported from the Streamlit ``9_Unit_Converter.py`` page. The conversion tables are
pure data; only the UI layer is rewritten for Taipy. Each page module owns its
state variables and handlers, and exposes ``page`` (a Taipy ``Markdown``) which
``app.py`` mounts into the navigation.
"""
from __future__ import annotations

import pandas as pd
from taipy.gui import Markdown

from utils.menu_icons import inject_icons
from utils.validation import TEMP_MIN_C, TEMP_MAX_C, PRESSURE_MAX_ATM

# ---------------------------------------------------------------------------
# Conversion tables — factor converts 1 <unit> -> the SI base unit (first key).
# ---------------------------------------------------------------------------
_TEMP_UNITS = ["°C", "°F", "K", "°R"]

_PRESSURE = {
    "Pa": 1.0, "kPa": 1.0e3, "MPa": 1.0e6, "bar": 1.0e5, "mbar": 1.0e2,
    "atm": 101325.0, "psi (lbf/in²)": 6894.757293168, "mmHg (torr)": 133.3223684,
    "inHg": 3386.389, "cmH₂O": 98.0665, "inH₂O": 249.08891,
}
_VOLUME = {
    "m³": 1.0, "L": 1.0e-3, "mL": 1.0e-6, "µL": 1.0e-9, "cm³": 1.0e-6,
    "US gal": 3.785411784e-3, "UK gal (imp)": 4.54609e-3, "US qt": 9.46352946e-4,
    "US fl oz": 2.95735296e-5, "UK fl oz": 2.84130625e-5,
    "US bbl (petroleum)": 0.158987295, "ft³": 0.028316846592, "in³": 1.6387064e-5,
}
_DYNAMIC_VISCOSITY = {
    "Pa·s": 1.0, "mPa·s (cP)": 1.0e-3, "µPa·s": 1.0e-6, "P (poise)": 0.1,
    "cP (centipoise)": 1.0e-3, "lbf·s/ft²": 47.88025898, "lb/(ft·s)": 1.488163944,
    "lb/(ft·h)": 4.133789e-4,
}
_KINEMATIC_VISCOSITY = {
    "m²/s": 1.0, "mm²/s (cSt)": 1.0e-6, "cm²/s (St)": 1.0e-4, "ft²/s": 9.290304e-2,
    "ft²/h": 2.58064e-5, "in²/s": 6.4516e-4,
}
_DENSITY = {
    "kg/m³": 1.0, "g/cm³": 1000.0, "g/mL": 1000.0, "g/L": 1.0, "kg/L": 1000.0,
    "lb/ft³": 16.01846337, "lb/gal (US)": 119.8264273, "lb/gal (UK)": 99.77637266,
    "lb/in³": 27679.90471, "slug/ft³": 515.3788184,
}
_POWER = {
    "W": 1.0, "kW": 1.0e3, "MW": 1.0e6, "mW": 1.0e-3, "hp (mechanical)": 745.69987158,
    "hp (metric)": 735.49875, "hp (boiler)": 9809.5, "BTU/h": 0.29307107,
    "BTU/s": 1055.05585, "ft·lbf/s": 1.3558179483, "kcal/h": 1.163, "cal/s": 4.184,
}
_ENERGY = {
    "J": 1.0, "kJ": 1.0e3, "MJ": 1.0e6, "cal": 4.184, "kcal": 4184.0,
    "BTU": 1055.05585, "kWh": 3.6e6, "Wh": 3600.0, "eV": 1.602176634e-19,
    "ft·lbf": 1.3558179483, "therm (US)": 1.054804e8, "erg": 1.0e-7,
}
_MASS = {
    "kg": 1.0, "g": 1.0e-3, "mg": 1.0e-6, "µg": 1.0e-9, "tonne (metric)": 1000.0,
    "lb": 0.45359237, "oz": 0.028349523125, "stone": 6.35029318, "slug": 14.593903,
    "US ton (short)": 907.18474, "UK ton (long)": 1016.0469088, "grain": 6.479891e-5,
}
_LENGTH = {
    "m": 1.0, "km": 1000.0, "cm": 0.01, "mm": 1.0e-3, "µm": 1.0e-6, "nm": 1.0e-9,
    "in": 0.0254, "ft": 0.3048, "yd": 0.9144, "mi (statute)": 1609.344,
    "nmi (nautical mile)": 1852.0, "mil (thou)": 2.54e-5, "Å (angström)": 1.0e-10,
}
_SURFACE_TENSION = {
    "N/m": 1.0, "mN/m": 1.0e-3, "dyn/cm": 1.0e-3, "lbf/ft": 14.5939029,
    "lbf/in": 175.1268349, "µN/m": 1.0e-6,
}
_DIFFUSIVITY = {
    "m²/s": 1.0, "cm²/s": 1.0e-4, "mm²/s": 1.0e-6, "ft²/s": 9.290304e-2, "ft²/h": 2.58064e-5,
}
_FLOW_RATE = {
    "m³/s": 1.0, "m³/h": 1.0 / 3600.0, "L/min": 1.0e-3 / 60.0, "L/h": 1.0e-3 / 3600.0,
    "mL/min": 1.0e-6 / 60.0, "US gal/min (GPM)": 6.30902e-5, "US gal/h": 1.05150e-5,
    "UK gal/min": 7.57682e-5, "ft³/min (CFM)": 4.71947e-4, "ft³/h": 7.86578e-6,
    "bbl/day": 1.84013e-6,
}
_SPEED = {
    "m/s": 1.0, "km/h": 1.0 / 3.6, "cm/s": 0.01, "mm/s": 1.0e-3, "ft/s": 0.3048,
    "ft/min": 0.00508, "in/s": 0.0254, "mph": 0.44704, "knot": 0.514444,
}
_TORQUE = {
    "N·m": 1.0, "kN·m": 1000.0, "mN·m": 1.0e-3, "lbf·ft": 1.3558179483,
    "lbf·in": 0.1129848290, "ozf·in": 7.06155e-3, "kgf·m": 9.80665,
    "kgf·cm": 0.0980665, "dyn·cm": 1.0e-7,
}
_CONCENTRATION = {
    "mol/L (M)": 1.0, "mmol/L (mM)": 1.0e-3, "µmol/L (µM)": 1.0e-6,
    "mol/m³": 1.0e-3, "kmol/m³": 1.0,
}

# --- Gas flow rate (special: requires T and P) ----------------------------
_T_NORMAL_K = 273.15
_T_STANDARD_K = 288.7056
_P_REF_PA = 101_325.0

# Each entry: (vol_factor_m3, time_factor_s, T_ref_K or None, P_ref_Pa or None)
_GAS_FLOW_SPECS: dict[str, tuple[float, float, float | None, float | None]] = {
    "Nm³/h": (1.0, 3600.0, _T_NORMAL_K, _P_REF_PA),
    "Nm³/min": (1.0, 60.0, _T_NORMAL_K, _P_REF_PA),
    "Nm³/s": (1.0, 1.0, _T_NORMAL_K, _P_REF_PA),
    "NL/min": (1.0e-3, 60.0, _T_NORMAL_K, _P_REF_PA),
    "NL/h": (1.0e-3, 3600.0, _T_NORMAL_K, _P_REF_PA),
    "SCFM": (0.028316846592, 60.0, _T_STANDARD_K, _P_REF_PA),
    "SCFH": (0.028316846592, 3600.0, _T_STANDARD_K, _P_REF_PA),
    "SCFS": (0.028316846592, 1.0, _T_STANDARD_K, _P_REF_PA),
    "Am³/h": (1.0, 3600.0, None, None),
    "Am³/min": (1.0, 60.0, None, None),
    "Am³/s": (1.0, 1.0, None, None),
    "AL/min": (1.0e-3, 60.0, None, None),
    "AL/h": (1.0e-3, 3600.0, None, None),
    "ACFM": (0.028316846592, 60.0, None, None),
    "ACFH": (0.028316846592, 3600.0, None, None),
}
_GAS_FLOW_UNIT_LIST = list(_GAS_FLOW_SPECS.keys())

PROPERTIES: dict[str, dict[str, float] | str] = {
    "Temperature": "temperature",
    "Pressure": _PRESSURE,
    "Volume": _VOLUME,
    "Dynamic viscosity": _DYNAMIC_VISCOSITY,
    "Kinematic viscosity": _KINEMATIC_VISCOSITY,
    "Density": _DENSITY,
    "Power": _POWER,
    "Energy": _ENERGY,
    "Mass": _MASS,
    "Length": _LENGTH,
    "Surface tension": _SURFACE_TENSION,
    "Diffusivity": _DIFFUSIVITY,
    "Flow rate (liquid)": _FLOW_RATE,
    "Gas flow rate": "gas_flow",
    "Speed / velocity": _SPEED,
    "Torque": _TORQUE,
    "Concentration": _CONCENTRATION,
}


# ---------------------------------------------------------------------------
# Pure conversion helpers
# ---------------------------------------------------------------------------
def _convert_temperature(value: float, from_unit: str) -> dict[str, float]:
    if from_unit == "°C":
        K = value + 273.15
    elif from_unit == "°F":
        K = (value - 32) * 5 / 9 + 273.15
    elif from_unit == "K":
        K = value
    elif from_unit == "°R":
        K = value * 5 / 9
    else:
        K = value
    return {"°C": K - 273.15, "°F": (K - 273.15) * 9 / 5 + 32, "K": K, "°R": K * 9 / 5}


def _convert_multiplicative(value: float, from_unit: str, table: dict[str, float]) -> dict[str, float]:
    base_value = value * table[from_unit]
    return {unit: base_value / factor for unit, factor in table.items()}


def _convert_gas_flow(value: float, from_unit: str, T_actual_K: float, P_actual_Pa: float) -> dict[str, float]:
    vol, time_s, T_ref, P_ref = _GAS_FLOW_SPECS[from_unit]
    if T_ref is not None:
        actual_m3_s = value * (vol / time_s) * (T_actual_K / T_ref) * (P_ref / P_actual_Pa)
    else:
        actual_m3_s = value * (vol / time_s)
    results: dict[str, float] = {}
    for unit, (v, t, Tr, Pr) in _GAS_FLOW_SPECS.items():
        if Tr is not None:
            results[unit] = actual_m3_s / (v / t) * (Tr / T_actual_K) * (P_actual_Pa / Pr)
        else:
            results[unit] = actual_m3_s / (v / t)
    return results


def _units_for(property_name: str) -> list[str]:
    entry = PROPERTIES[property_name]
    if entry == "temperature":
        return _TEMP_UNITS
    if entry == "gas_flow":
        return _GAS_FLOW_UNIT_LIST
    return list(entry.keys())  # type: ignore[union-attr]


def _fmt(converted: float) -> str:
    if converted == 0:
        return "0"
    if abs(converted) < 1e-4 or abs(converted) >= 1e8:
        return f"{converted:.6g}"
    return f"{converted:,.6g}"


def _compute(property_name: str, from_unit: str, value: float, gas_T_C: float, gas_P_atm: float) -> pd.DataFrame:
    entry = PROPERTIES[property_name]
    if entry == "temperature":
        results = _convert_temperature(value, from_unit)
    elif entry == "gas_flow":
        results = _convert_gas_flow(value, from_unit, gas_T_C + 273.15, gas_P_atm * 101325.0)
    else:
        results = _convert_multiplicative(value, from_unit, entry)  # type: ignore[arg-type]
    rows = [{"Unit": unit, "Value": _fmt(conv)} for unit, conv in results.items() if unit != from_unit]
    return pd.DataFrame(rows, columns=["Unit", "Value"])


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------
uc_property = "Pressure"
uc_property_options = list(PROPERTIES.keys())
uc_from_options = _units_for(uc_property)
uc_from_unit = uc_from_options[0]
uc_value = 1.0
uc_gas_T = 25.0
uc_gas_P = 1.0
uc_show_gas = False
uc_header = f"{uc_value:g} {uc_from_unit}"
uc_result_df = _compute(uc_property, uc_from_unit, uc_value, uc_gas_T, uc_gas_P)

GAS_REF_DF = pd.DataFrame(
    [
        {"Basis": "Normal (N)", "T_ref": "0 °C (273.15 K)", "P_ref": "1 atm (101 325 Pa)", "Standard": "DIN 1343 / ISO 2533"},
        {"Basis": "Standard (S)", "T_ref": "60 °F (288.71 K)", "P_ref": "1 atm (101 325 Pa)", "Standard": "US / SCFM"},
        {"Basis": "Actual (A)", "T_ref": "user T", "P_ref": "user P", "Standard": "User-specified"},
    ]
)


def _refresh(state):
    state.uc_header = f"{state.uc_value:g} {state.uc_from_unit}"
    state.uc_result_df = _compute(
        state.uc_property, state.uc_from_unit, state.uc_value, state.uc_gas_T, state.uc_gas_P
    )


def on_property_change(state):
    opts = _units_for(state.uc_property)
    state.uc_from_options = opts
    state.uc_from_unit = opts[0]
    state.uc_show_gas = PROPERTIES[state.uc_property] == "gas_flow"
    _refresh(state)


def on_input_change(state):
    _refresh(state)


page = Markdown(
    inject_icons("""
# __ICON:Unit_Converter__Unit Converter

General unit conversions for physical properties relevant to mixing and reactor engineering.

<|part|class_name=va-card|
## Convert
<|layout|columns=1 1 1|
<|{uc_property}|selector|lov={uc_property_options}|dropdown|label=Physical property|on_change=on_property_change|>

<|{uc_from_unit}|selector|lov={uc_from_options}|dropdown|label=From unit|on_change=on_input_change|>

<|{uc_value}|number|label=Value|on_change=on_input_change|>
|>

<|part|render={uc_show_gas}|
Gas flow conversions use the ideal-gas law. Specify the **actual** gas temperature and pressure.

<|layout|columns=1 1|
<|{uc_gas_T}|number|label=Gas temperature (°C)|on_change=on_input_change|>

<|{uc_gas_P}|number|label=Gas pressure (atm)|on_change=on_input_change|>
|>

<|Reference conditions|expandable|expanded=False|
<|{GAS_REF_DF}|table|width=100%|show_all|>
|>
|>
|>

<|part|class_name=va-card|
## Results
### <|{uc_header}|text|raw|>

<|{uc_result_df}|table|width=100%|page_size=20|>
|>
""")
)
