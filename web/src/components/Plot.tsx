import Plotly from "plotly.js-dist-min";
import { useEffect, useRef } from "react";

export interface Figure {
  data?: unknown[];
  layout?: Record<string, unknown>;
}

/** Renders Plotly figure JSON from `POST /charts/{kind}` (built server-side by viz/). */
export default function Plot({ figure, height }: { figure: Figure; height?: number }) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    void Plotly.react(
      el,
      (figure.data ?? []) as Plotly.Data[],
      { ...figure.layout, autosize: true, ...(height ? { height } : {}) } as Partial<Plotly.Layout>,
      { responsive: true, displaylogo: false },
    );
  }, [figure, height]);

  useEffect(() => {
    const el = ref.current;
    return () => {
      if (el) Plotly.purge(el);
    };
  }, []);

  return <div ref={ref} className="plot" />;
}
