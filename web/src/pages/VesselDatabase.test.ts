import { describe, expect, it } from "vitest";
import { defaultFill, fillStatus, splitLabel, type Fill } from "./VesselDatabase";

const OK: Fill = {
  total_L: 10,
  level_mm: 50,
  fill_pct: 40,
  contact_area_m2: 0.1,
  warnings: [],
  level_warning_kind: null,
  other_level_warning: "",
};

describe("vessel helpers (ports of pages/vessel_database.py)", () => {
  it("splitLabel", () => {
    expect(splitLabel("Max Volume [L]")).toEqual(["Max Volume", "L"]);
    expect(splitLabel("Owner")).toEqual(["Owner", ""]);
  });

  it("defaultFill: mid working volume, else 70 % of brim-full", () => {
    expect(defaultFill({ V_L_min: 0.03, V_L_max: 0.1 }, 0.18)).toBe(0.07);
    expect(defaultFill({ V_L_min: null, V_L_max: 0.1 }, 0.18677)).toBe(0.13);
  });

  it("fillStatus: volume band first, then level warnings", () => {
    const row = { V_L_min: 2, V_L_max: 8 };
    expect(fillStatus(row, 1, { ...OK, level_warning_kind: "red" })).toBe("🔴 Below Min Volume (2 L)");
    expect(fillStatus(row, 9.5, OK)).toBe("🔴 Above Max Volume (8 L)");
    expect(fillStatus(row, 5, { ...OK, level_warning_kind: "red" })).toBe(
      "🔴 Liquid level is below the lowest impeller",
    );
    expect(fillStatus(row, 5, { ...OK, level_warning_kind: "yellow" })).toBe(
      "🟡 Liquid level is at the lowest impeller",
    );
    expect(fillStatus(row, 5, { ...OK, other_level_warning: "Top impeller exposed" })).toBe(
      "🟡 Top impeller exposed",
    );
    expect(fillStatus({}, 5, OK)).toBe("");
  });
});
