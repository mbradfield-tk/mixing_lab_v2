"""Vessel Assessment result tables (shown on the page and embedded in the PDF)."""
from __future__ import annotations

import pandas as pd

from core import sensitivity_rules as rules
from utils.calculations import heat_balance_assessment, particle_suspension_criterion

TABLE_COLUMNS = ["Parameter", "Value", "Units"]
MT_COLUMNS = ["Transfer path", "kLa (1/s)", "Demand 1/t_rxn (1/s)", "Capacity / demand",
              "Screening"]

# (hydro-dict key, display name, unit)
HYDRO_ROWS = [
    ("Re", "Reynolds number", "–"),
    ("Power (W)", "Power", "W"),
    ("P/V (W/L)", "Power per volume", "W/L"),
    ("Tip speed (m/s)", "Tip speed", "m/s"),
    ("Blend time 95% (s)", "Blend time (95%)", "s"),
    ("Micromix time t_E (s)", "Micromixing time t_E", "s"),
    ("Kolmogorov η (µm)", "Kolmogorov length η", "µm"),
    ("Circulation time (s)", "Circulation time", "s"),
    ("Avg shear rate (1/s)", "Average shear rate", "1/s"),
    ("Max shear rate (1/s)", "Maximum shear rate", "1/s"),
    ("Torque (N·m)", "Torque", "N·m"),
    ("Froude number", "Froude number", "–"),
    ("kLa_surface (1/s)", "Surface kLa", "1/s"),
]


def assessment_tables(hydro: dict, n_rpm: float, t_rxn: float, *, solids_on: bool,
                      gas_on: bool, fed_on: bool) -> dict:
    """{hydro, damkohler, solids, heat, mass_transfer} DataFrames plus the
    Markdown ``assessment`` line, from an ``evaluate_point`` result."""
    kla_sl = hydro.get("kLa_SL (1/s)", 0.0)
    if solids_on:
        n_js_rpm = hydro.get("N_js (RPM)", 0.0)
        assess = particle_suspension_criterion(n_rpm / 60.0, n_js_rpm / 60.0)
        solids = pd.DataFrame([
            {"Parameter": "Just-suspended speed N_js", "Value": f"{n_js_rpm:.1f}", "Units": "RPM"},
            {"Parameter": "Operating speed N", "Value": f"{n_rpm:.1f}", "Units": "RPM"},
            {"Parameter": "N / N_js", "Value": f"{(n_rpm / n_js_rpm) if n_js_rpm > 0 else 0:.2f}", "Units": "–"},
            {"Parameter": "Suspension state", "Value": assess, "Units": "–"},
            {"Parameter": "Settling velocity v_t", "Value": f"{hydro.get('v_t (m/s)', 0.0):.3g}", "Units": "m/s"},
            {"Parameter": "Solid-liquid k_SL", "Value": f"{hydro.get('k_SL (m/s)', 0.0):.3g}", "Units": "m/s"},
            {"Parameter": "Solid-liquid kLa_SL", "Value": f"{kla_sl:.3g}", "Units": "1/s"},
        ])
    else:
        solids = pd.DataFrame(columns=TABLE_COLUMNS)

    reaction_on = "Da_macro" in hydro
    paths = []
    if gas_on and reaction_on:
        paths.append(("Gas-liquid", hydro["kLa (1/s)"]))
    if solids_on and reaction_on:
        paths.append(("Solid-liquid", kla_sl))
    mass_transfer = pd.DataFrame(rules.mass_transfer_screen(paths, t_rxn), columns=MT_COLUMNS)

    hydro_df = pd.DataFrame(
        [{"Parameter": name, "Value": f"{hydro[key]:,.4g}", "Units": unit}
         for key, name, unit in HYDRO_ROWS])

    regime = rules.regime_label
    da_meso = hydro.get("Da_meso", 0.0)
    gl_type = ("Gas–liquid mass transfer" if gas_on
               else "Gas–liquid mass transfer (surface aeration)")
    dam_rows = []
    if reaction_on:
        dam_rows.append({"Type": "Macromixing (bulk blending)", "Damköhler": "Da_macro", "Value": f"{hydro['Da_macro']:.3g}", "Regime": regime(hydro["Da_macro"])})
        if fed_on:
            dam_rows.append({"Type": "Mesomixing (feed dispersion)", "Damköhler": "Da_meso", "Value": f"{da_meso:.3g}", "Regime": regime(da_meso)})
        dam_rows.append({"Type": "Micromixing (engulfment)", "Damköhler": "Da_micro", "Value": f"{hydro['Da_micro']:.3g}", "Regime": regime(hydro["Da_micro"])})
        dam_rows.append({"Type": gl_type, "Damköhler": "Da_GL", "Value": f"{hydro['Da_GL']:.3g}", "Regime": regime(hydro["Da_GL"])})
        if solids_on:
            dam_rows.append({"Type": "Solid–liquid mass transfer", "Damköhler": "Da_SL", "Value": f"{hydro['Da_SL']:.3g}", "Regime": regime(hydro["Da_SL"])})

    if "Q_gen (W)" in hydro:
        q_gen, q_cool = hydro["Q_gen (W)"], hydro["Q_cool (W)"]
        rows = [{"Parameter": "Heat generation Q_gen", "Value": f"{q_gen:,.1f}", "Units": "W"}]
        q_load = q_gen
        if "Q_feed (W)" in hydro:
            q_load = hydro["Q_load (W)"]
            rows += [
                {"Parameter": "Feed sensible heat Q_feed", "Value": f"{hydro['Q_feed (W)']:,.1f}",
                 "Units": "W"},
                {"Parameter": "Net heat load Q_gen + Q_feed", "Value": f"{q_load:,.1f}", "Units": "W"},
            ]
        balance = (heat_balance_assessment(q_load, q_cool)
                   if q_load > 0 or "Q_feed (W)" not in hydro
                   else "Net cooling by the feed - no heat to remove")
        heat = pd.DataFrame(rows + [
            {"Parameter": "Overall U", "Value": f"{hydro['U (W/m²·K)']:,.1f}", "Units": "W/m²·K"},
            {"Parameter": "Jacket area A", "Value": f"{hydro['A_ht (m²)']:,.4g}", "Units": "m²"},
            {"Parameter": "Cooling capacity Q_cool", "Value": f"{q_cool:,.1f}", "Units": "W"},
            {"Parameter": "Balance", "Value": balance, "Units": "–"},
        ])
    else:
        heat = pd.DataFrame(columns=TABLE_COLUMNS)

    return {"hydro": hydro_df,
            "damkohler": pd.DataFrame(dam_rows, columns=["Type", "Damköhler", "Value", "Regime"]),
            "solids": solids, "heat": heat, "mass_transfer": mass_transfer,
            "assessment": (f"**Assessment:** {hydro['Assessment']}" if reaction_on else
                           "**Assessment:** No reaction selected - Damköhler screening does "
                           "not apply (hydrodynamic assessment).")}
