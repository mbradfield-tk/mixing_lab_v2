import { describe, expect, it } from "vitest";
import { defaultFill, defaultProps, fillStatus, splitLabel, vesselRatios, type Fill } from "./VesselDatabase";

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

describe("vesselRatios", () => {
  it("picks defaults by column so a relabelled column stays visible", () => {
    const labels = new Map([["D_imp_m", "Impeller Diameter [m]"], ["D_tank_m", "Tank Diameter [m]"]]);
    const props = defaultProps(labels);
    expect(props).toContain("Impeller Diameter");
    expect(props.slice(10, 13)).toEqual(["Impeller Diameter", "D/T", "H/T"]);
    expect(defaultProps(new Map([["D_imp_m", "Impeller 1 Diameter [m]"]]))).toContain("Impeller 1 Diameter");
  });

  it("derives D/T and H/T (dish + tan-tan height) from the tank diameter, skipping missing values", () => {
    expect(
      vesselRatios({ D_tank_m: 0.05, D_imp_m: 0.03, H_bot_dish_m: 0.01164, L_tan_tan_m: 0.088, H_m: 0.09384 }).map((r) => [
        r.prop,
        r.value,
      ]),
    ).toEqual([
      ["D/T", "0.6"],
      ["H/T", "1.99"],
    ]);
    // no measured dish height: falls back to H_max - L_tan_tan; full height is ignored
    expect(vesselRatios({ D_tank_m: 1, H_max_m: 1.5, L_tan_tan_m: 1.2, H_m: 9 }).map((r) => r.value)).toEqual(["1.5"]);
    expect(vesselRatios({ D_tank_m: 1.2, D_imp_m: "0.4", L_tan_tan_m: "" }).map((r) => r.prop)).toEqual(["D/T"]);
    expect(vesselRatios({ D_tank_m: 0, D_imp_m: 0.4, L_tan_tan_m: 1 })).toEqual([]);
  });
});
