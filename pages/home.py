"""Home / landing page.

Shown when the app first loads and when the Mixing Lab logo menu item is
selected. Gives a short summary of the app, each section, and version info.
"""
from __future__ import annotations

from taipy.gui import Markdown

from utils.menu_icons import inject_icons

APP_VERSION = "2.0.1"
RELEASE_DATE = "August 2026"

page = Markdown(
    inject_icons(
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

- **__ICON:Vessel_Database__[Vessels](/Vessel_Database)** — library of vessel geometries (tank, impeller, jacket,
  materials, operating ranges) used by all assessment tools.
- **__ICON:Fluid_Database__[Fluids](/Fluid_Database)** — solvent physical properties with temperature correlations and
  a solvent-miscibility screening tool.
- **__ICON:Reaction_Database__[Reactions](/Reaction_Database)** — reaction kinetics, schemes, heats of reaction and
  operating conditions.
- **__ICON:Particle_Database__[Particles](/Particle_Database)** — particle size and density data for solid-suspension
  calculations.
|>
<|part|class_name=va-card|
## Assessment tools

- **__ICON:Vessel_Assessment__[Vessel Assessment](/Vessel_Assessment)** — full single-vessel analysis: hydrodynamics,
  Damköhler numbers, solid suspension, heat balance and an operating-envelope
  chart, with PDF export.
- **__ICON:Vessel_Comparison__[Vessel Comparison](/Vessel_Comparison)** — side-by-side envelopes for several vessels plus
  scale-up matching between scales.
- **__ICON:Bourne_Protocol__[Bourne Protocol](/Bourne_Protocol)** — experimental screen for mixing sensitivity
  (impeller speed, feed rate and feed location tests).
- **__ICON:Mixing_Sensitivity__[Reaction Sensitivity Protocol](/Mixing_Sensitivity)** — step-by-step decision tree combining
  kinetics, phases and heat effects into a mixing-sensitivity verdict.
- **__ICON:Crystallization_Sensitivity__[Crystallization Sensitivity Protocol](/Crystallization_Sensitivity)** — mixing-sensitivity
  workflow for crystallization process development (work in progress).
|>
|>

<|layout|columns=1 1|
<|part|class_name=va-card|
## Utilities

- **__ICON:Heat_Transfer__[Heat Transfer Tool](/Heat_Transfer)** — batch heating/cooling temperature and duty
  profiles, and heat-transfer-coefficient estimation.
- **__ICON:Unit_Converter__[Unit Converter](/Unit_Converter)** — engineering unit conversions (pressure, viscosity,
  energy, agitation, and more).
- **__ICON:Equations_Reference__[Equations Reference](/Equations_Reference)** — every correlation used in the app, with symbols,
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
)
