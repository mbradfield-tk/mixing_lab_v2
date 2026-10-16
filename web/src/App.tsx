import { lazy, Suspense, type ReactNode } from "react";
import { Route, Routes } from "react-router-dom";
import { Layout } from "./components/Layout";
import { CrystallizationSensitivity } from "./pages/CrystallizationSensitivity";
import { Home } from "./pages/Home";
import { NotFound } from "./pages/NotFound";
import { ParticleDatabase } from "./pages/ParticleDatabase";
import { ReactionDatabase } from "./pages/ReactionDatabase";
import { RecordedResults } from "./pages/RecordedResults";
import { UnitConverter } from "./pages/UnitConverter";
import { PersistentPage } from "./state/pageState";

// Loaded on demand: the Markdown/KaTeX renderer and the fluid tools are large.
const EquationsReference = lazy(() =>
  import("./pages/EquationsReference").then((m) => ({ default: m.EquationsReference })),
);
const FluidDatabase = lazy(() =>
  import("./pages/FluidDatabase").then((m) => ({ default: m.FluidDatabase })),
);
const VesselDatabase = lazy(() =>
  import("./pages/VesselDatabase").then((m) => ({ default: m.VesselDatabase })),
);
const VesselAssessment = lazy(() =>
  import("./pages/VesselAssessment").then((m) => ({ default: m.VesselAssessment })),
);
const VesselComparison = lazy(() =>
  import("./pages/VesselComparison").then((m) => ({ default: m.VesselComparison })),
);
const HeatTransfer = lazy(() => import("./pages/HeatTransfer").then((m) => ({ default: m.HeatTransfer })));
const BourneProtocol = lazy(() => import("./pages/BourneProtocol").then((m) => ({ default: m.BourneProtocol })));
const MixingSensitivity = lazy(() =>
  import("./pages/MixingSensitivity").then((m) => ({ default: m.MixingSensitivity })),
);

const deferred = (page: ReactNode) => <Suspense fallback={<p>Loading…</p>}>{page}</Suspense>;
const kept = (key: string, page: ReactNode) => <PersistentPage page={key}>{deferred(page)}</PersistentPage>;

export function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Home />} />
        <Route path="vessels" element={deferred(<VesselDatabase />)} />
        <Route path="fluids" element={deferred(<FluidDatabase />)} />
        <Route path="reactions" element={<ReactionDatabase />} />
        <Route path="particles" element={<ParticleDatabase />} />
        <Route path="recorded-results" element={<RecordedResults />} />
        <Route path="crystallization-sensitivity" element={<CrystallizationSensitivity />} />
        <Route path="vessel-assessment" element={kept("vessel-assessment", <VesselAssessment />)} />
        <Route path="vessel-comparison" element={kept("vessel-comparison", <VesselComparison />)} />
        <Route path="heat-transfer" element={kept("heat-transfer", <HeatTransfer />)} />
        <Route path="bourne-protocol" element={kept("bourne-protocol", <BourneProtocol />)} />
        <Route path="reaction-sensitivity" element={kept("reaction-sensitivity", <MixingSensitivity />)} />
        <Route path="unit-converter" element={<UnitConverter />} />
        <Route path="equations-reference" element={deferred(<EquationsReference />)} />
        <Route path="*" element={<NotFound />} />
      </Route>
    </Routes>
  );
}
