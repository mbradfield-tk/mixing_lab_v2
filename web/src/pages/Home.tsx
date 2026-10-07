import { useQuery } from "@tanstack/react-query";
import { api, unwrap } from "../api/client";
import { Card, MenuIcon, PageLink } from "../components/ui";
import { logoUrl } from "../nav";

function Entry({ pageKey, children }: { pageKey: string; children: string }) {
  return (
    <li>
      <strong>
        <MenuIcon pageKey={pageKey} /> <PageLink pageKey={pageKey} />
      </strong>{" "}
      — {children}
    </li>
  );
}

export function Home() {
  const version = useQuery({
    queryKey: ["version"],
    queryFn: async () => unwrap(await api.GET("/api/v1/version")),
  });

  return (
    <>
      <div className="home-logo">
        <img src={logoUrl(360)} alt="Mixing Lab" />
      </div>
      <h1 className="centered">Welcome to Mixing Lab</h1>

      <Card title="About this app">
        <p>
          <strong>Mixing Lab</strong> is an engineering toolkit for characterising mixing
          sensitivity and comparing agitated vessels for experimental design or scale-up. It
          combines equipment, fluid, reaction and particle databases with hydrodynamic, mixing,
          and mass- and heat-transfer calculations so you can assess whether a vessel is fit for a
          given process, compare candidate vessels, determine scale-up suitability and document
          the results as PDF reports.
        </p>
        <p>
          Use the menu on the left to navigate between sections. Pages marked ↗ still open in the
          original app while they are being migrated.
        </p>
      </Card>

      <div className="grid-2">
        <Card title="Databases">
          <ul>
            <Entry pageKey="Vessel_Database">
              library of vessel geometries (tank, impeller, jacket, materials, operating ranges)
              used by all assessment tools.
            </Entry>
            <Entry pageKey="Fluid_Database">
              solvent physical properties with temperature correlations and a
              solvent-miscibility screening tool.
            </Entry>
            <Entry pageKey="Reaction_Database">
              reaction kinetics, schemes, heats of reaction and operating conditions.
            </Entry>
            <Entry pageKey="Particle_Database">
              particle size and density data for solid-suspension calculations.
            </Entry>
          </ul>
        </Card>
        <Card title="Assessment tools">
          <ul>
            <Entry pageKey="Vessel_Assessment">
              full single-vessel analysis: hydrodynamics, Damköhler numbers, mass-transfer capacity
              screen, solid suspension, heat balance, an operating-envelope chart and interactive
              3D response surfaces, with PDF export.
            </Entry>
            <Entry pageKey="Vessel_Comparison">
              side-by-side envelopes for several vessels plus scale-up matching between scales.
            </Entry>
            <Entry pageKey="Bourne_Protocol">
              experimental screen for mixing sensitivity (impeller speed, feed rate and feed
              location tests).
            </Entry>
            <Entry pageKey="Mixing_Sensitivity">
              step-by-step decision tree combining kinetics, phases and heat effects into a
              mixing-sensitivity verdict.
            </Entry>
            <Entry pageKey="Crystallization_Sensitivity">
              mixing-sensitivity workflow for crystallization process development (work in
              progress).
            </Entry>
          </ul>
        </Card>
      </div>

      <div className="grid-2">
        <Card title="Utilities">
          <ul>
            <Entry pageKey="Heat_Transfer">
              batch heating/cooling temperature and duty profiles, and heat-transfer-coefficient
              estimation.
            </Entry>
            <Entry pageKey="Recorded_Results">
              view, filter and bulk-export the case results saved from the analysis pages.
            </Entry>
            <Entry pageKey="Unit_Converter">
              engineering unit conversions (pressure, viscosity, energy, agitation, and more).
            </Entry>
            <Entry pageKey="Equations_Reference">
              every correlation used in the app, with symbols, units and literature references.
            </Entry>
          </ul>
        </Card>
        <Card title="Version">
          <ul>
            <li>
              <strong>Version:</strong> {version.data?.version ?? "…"}
            </li>
            <li>
              <strong>Released:</strong> {version.data?.release_date ?? "…"}
            </li>
            <li>
              <strong>Framework:</strong> React + FastAPI (Python 3.12)
            </li>
          </ul>
          <p>For questions, feedback or new-feature requests, contact Michael Bradfield.</p>
        </Card>
      </div>
    </>
  );
}
