"""Unit Converter page (Taipy).

Ported from the Streamlit ``9_Unit_Converter.py`` page. The conversion tables and
functions live in :mod:`core.units`; this module only formats and binds them.
"""
from __future__ import annotations

import pandas as pd
from taipy.gui import Markdown

from core import units
from pages._menu_icons import inject_icons

PROPERTIES = units.PROPERTIES
_units_for = units.units_for


def _fmt(converted: float) -> str:
    if converted == 0:
        return "0"
    if abs(converted) < 1e-4 or abs(converted) >= 1e8:
        return f"{converted:.6g}"
    return f"{converted:,.6g}"


def _compute(property_name: str, from_unit: str, value: float, gas_T_C: float, gas_P_atm: float) -> pd.DataFrame:
    results = units.convert(property_name, from_unit, value, gas_T_C, gas_P_atm)
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

GAS_REF_DF = pd.DataFrame(units.GAS_REFERENCE)


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
