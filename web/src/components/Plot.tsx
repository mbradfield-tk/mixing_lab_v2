import Plotly from "plotly.js-dist-min";
import { useEffect, useRef } from "react";
import { darkLayout, useTheme } from "../theme";

export interface Figure {
  data?: unknown[];
  layout?: Record<string, unknown>;
}

/** Renders Plotly figure JSON from `POST /charts/{kind}` (built server-side by viz/). */
export default function Plot({ figure, height }: { figure: Figure; height?: number }) {
  const ref = useRef<HTMLDivElement>(null);
  const theme = useTheme();

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const layout = theme === "dark" ? darkLayout(figure.layout ?? {}) : figure.layout;
    void Plotly.react(
      el,
      (figure.data ?? []) as Plotly.Data[],
      { ...layout, autosize: true, ...(height ? { height } : {}) } as Partial<Plotly.Layout>,
      { responsive: true, displaylogo: false, modeBarButtonsToRemove: ["lasso2d", "select2d", "autoScale2d"],
        toImageButtonOptions: { format: "png", scale: 2 } },
    );
  }, [figure, height, theme]);

  useEffect(() => {
    const el = ref.current;
    return () => {
      if (el) Plotly.purge(el);
    };
  }, []);

  return <div ref={ref} className="plot" />;
}
