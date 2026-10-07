import { lazy, Suspense } from "react";
import type { Figure } from "./Plot";

const Plot = lazy(() => import("./Plot"));

/** Plotly chart that downloads the (large) Plotly bundle only when first shown. */
export function Chart({ figure, height }: { figure: Figure | undefined; height?: number }) {
  if (!figure) return null;
  return (
    <Suspense fallback={<p className="muted">Loading chart…</p>}>
      <Plot figure={figure} height={height} />
    </Suspense>
  );
}
