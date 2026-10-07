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

const deferred = (page: ReactNode) => <Suspense fallback={<p>Loading…</p>}>{page}</Suspense>;

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
        <Route path="vessel-assessment" element={deferred(<VesselAssessment />)} />
        <Route path="vessel-comparison" element={deferred(<VesselComparison />)} />
        <Route path="unit-converter" element={<UnitConverter />} />
        <Route path="equations-reference" element={deferred(<EquationsReference />)} />
        <Route path="*" element={<NotFound />} />
      </Route>
    </Routes>
  );
}
