import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { statsFromRows, splitUnit, stripIcon, toneOf } from "./Insights";
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
});
