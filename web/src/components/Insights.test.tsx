import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { LogScale, logPosition, statsFromRows, splitUnit, stripIcon, toneOf } from "./Insights";
import { ResultTable } from "./ResultTable";

describe("insight helpers", () => {
  it("reads severity from traffic-light icons", () => {
    expect(toneOf("🔴 Mixing-limited")).toBe("critical");
    expect(toneOf("🟡 Transitional")).toBe("warning");
    expect(toneOf("⚠️ Exceeds max volume")).toBe("warning");
    expect(toneOf("🟢 Mixing-insensitive")).toBe("ok");
    expect(toneOf("⚪ Unknown")).toBe("unknown");
    expect(toneOf("OK")).toBe("info");
    expect(stripIcon("🟢 Mixing-insensitive")).toBe("Mixing-insensitive");
  });

  it("builds tiles from Parameter/Value/Units and Metric (unit) rows", () => {
    expect(splitUnit("U (W/m2.K)")).toEqual(["U", "W/m2.K"]);
    expect(splitUnit("Re")).toEqual(["Re", ""]);
    expect(statsFromRows([{ Parameter: "Tip speed", Value: "0.63", Units: "m/s" }])).toEqual([
      { label: "Tip speed", value: "0.63", unit: "m/s" },
    ]);
    expect(statsFromRows([{ Metric: "Peak T (C)", Value: 30.4 }, { Metric: "Nu", Value: null }], "Metric")).toEqual([
      { label: "Peak T", value: "30.4", unit: "C" },
      { label: "Nu", value: "—", unit: "" },
    ]);
  });

  it("renders status cells as pills in result tables", () => {
    render(<ResultTable rows={[{ Regime: "🔴 Mixing-limited", Value: "22.7" }]} />);
    const pill = screen.getByText("Mixing-limited");
    expect(pill.className).toContain("tone-critical");
    expect(screen.getByText("22.7").className).not.toContain("pill");
  });

  it("places log-scale positions and zone widths on the Da axis", () => {
    expect(logPosition(0.1, 1e-3, 100)).toBeCloseTo(40);
    expect(logPosition(1, 1e-3, 100)).toBeCloseTo(60);
    expect(logPosition(1e-6, 1e-3, 100)).toBe(0);
    expect(logPosition(1e6, 1e-3, 100)).toBe(100);
    const { container } = render(
      <LogScale
        min={1e-3}
        max={100}
        zones={[
          { to: 0.1, label: "A", tone: "ok" },
          { to: 1, label: "B", tone: "warning" },
          { to: 100, label: "C", tone: "critical" },
        ]}
        markers={[{ label: "Da micro", value: 1.5 }]}
      />,
    );
    const widths = [...container.querySelectorAll<HTMLElement>(".log-zone")].map((z) => parseFloat(z.style.width));
    expect(widths.map((w) => Math.round(w))).toEqual([40, 20, 40]);
    expect(container.querySelector(".log-marker")?.textContent).toBe("Da micro 1.5");
  });
});
