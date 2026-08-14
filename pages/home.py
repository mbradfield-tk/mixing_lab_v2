"""Home / landing page.

Shown when the app first loads and when the Mixing Lab logo menu item is
selected. Gives a short summary of the app, each section, and version info.
"""
from __future__ import annotations

from taipy.gui import Markdown

APP_VERSION = "2.0.1"
RELEASE_DATE = "August 2026"

page = Markdown(
    """
# Welcome to Mixing Lab

<|part|class_name=va-card|
## About this app

**Mixing Lab** is an engineering toolkit for characterising mixing sensitivity and comparing
agitated vessels for experimental design or scale-up. It combines equipment, fluid, reaction and particle databases
with hydrodynamic, mixing, and mass- and heat-transfer calculations so you can
assess whether a vessel is fit for a given process, compare candidate vessels, determine sale-up suitability
and document the results as PDF reports.

Use the menu on the left to navigate between sections.
|>

<|layout|columns=1 1|
<|part|class_name=va-card|
## Databases

- **⚗️ Vessels** — library of vessel geometries (tank, impeller, jacket,
  materials, operating ranges) used by all assessment tools.
- **💧 Fluids** — solvent physical properties with temperature correlations and
  a solvent-miscibility screening tool.
- **🧪 Reactions** — reaction kinetics, schemes, heats of reaction and
  operating conditions.
- **🟤 Particles** — particle size and density data for solid-suspension
  calculations.
|>
<|part|class_name=va-card|
## Assessment tools

- **🌀 Vessel Assessment** — full single-vessel analysis: hydrodynamics,
  Damköhler numbers, solid suspension, heat balance and an operating-envelope
  chart, with PDF export.
- **⚖️ Vessel Comparison** — side-by-side envelopes for several vessels plus
  scale-up matching between scales.
- **🅱️ Bourne Protocol** — experimental screen for mixing sensitivity
  (impeller speed, feed rate and feed location tests).
- **🧭 Reaction Sensitivity Protocol** — step-by-step decision tree combining
  kinetics, phases and heat effects into a mixing-sensitivity verdict.
|>
|>

<|layout|columns=1 1|
<|part|class_name=va-card|
## Utilities

- **🔥 Heat Transfer Tool** — batch heating/cooling temperature and duty
  profiles, and heat-transfer-coefficient estimation.
- **🔄 Unit Converter** — engineering unit conversions (pressure, viscosity,
  energy, agitation, and more).
- **📐 Equations Reference** — every correlation used in the app, with symbols,
  units and literature references.
|>
<|part|class_name=va-card|
## Version

- **Version:** """ + APP_VERSION + """
- **Released:** """ + RELEASE_DATE + """
- **Framework:** Taipy GUI (Python 3.12)

For questions, feedback or new-feature requests, contact Michael Bradfield.
|>
|>
"""
)
