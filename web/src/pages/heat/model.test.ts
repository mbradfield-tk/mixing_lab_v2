import { describe, expect, it } from "vitest";
import {
  INITIAL, adiabaticRise, adiabaticText, agitatorText, buildBody, colorLimits, heatStatus, kpiRows, reactionStatus,
  sweepRange,
} from "./model";

describe("heat-transfer text ports", () => {
  it("adiabatic rise and text (pages/heat_transfer._adiabatic_text)", () => {
    expect(adiabaticRise(1000, 4000, 1, -50)).toBeCloseTo(12.5);
    expect(adiabaticRise(0, 4000, 1, -50)).toBe(0);
    expect(adiabaticText(1000, 4000, 1, -50, 25)).toBe(
      "**Adiabatic (exothermic):** ΔT ≈ +12.5 °C → T_ad ≈ 37.5 °C (no cooling, from T_start = 25.0 °C).",
    );
    expect(adiabaticText(1000, 4000, 1, 20, 25)).toContain("(endothermic):** ΔT ≈ -5.0 °C");
  });

  it("agitator text", () => {
    expect(agitatorText(2.5, -100)).toBe(
      "**Agitator heat:** 2.50 W — about **2.5%** of the initial jacket duty (Q_max = 100.0 W).",
    );
    expect(agitatorText(2.5, 0)).toContain("about **∞**");
    expect(agitatorText(0, 100)).toBe("**Agitator heat:** not included (toggle *Include agitator heat* to add it).");
  });

  it("status lines", () => {
    expect(heatStatus(862.47, 1234.5, null)).toBe(
      "Computed successfully. U = 862.5 W/(m2.K), simulated time (const jacket) = 20.57 min, analytical = Infinity.",
    );
    expect(reactionStatus(-80, 40.04, 60.0, null)).toBe(
      "Reaction simulated (exothermic). Peak T = 40.0 C, adiabatic T = 60.0 C, time to 99% conversion = not reached.",
    );
  });

  it("kpiRows rounds like the Taipy table", () => {
    const rows = kpiRows({ Re: 8821.6, Pr: 6.123, Nu: 120.456, h_i_W_m2K: 1500.126, h_o_W_m2K: 2000, U_W_m2K: 862.474, A_ht_m2: 0.01, UA_W_K: 8.62474, agitator_power_W: 0 });
    expect(rows.map((r) => r.Value)).toEqual(["1500.13", "2000", "862.47", "8.62", "120.46", "8822", "6.12"]);
  });
});

describe("sweep defaults (core.heat_transfer.sweep_range_defaults)", () => {
  const ranges = { N_rpm_range: [50, 1000], V_L_range: null };
  it("uses vessel bounds for speed, ±50 % otherwise, and the zero-value table", () => {
    expect(sweepRange("n_rpm", 525, ranges, {})).toEqual([50, 1000]);
    expect(sweepRange("v_l", 0.06, ranges, {})).toEqual([0.03, 0.09]);
    expect(sweepRange("fouling", 0, ranges, { fouling: 0.002 })).toEqual([0, 0.002]);
  });

  it("colorLimits pads a flat surface", () => {
    expect(colorLimits([[1, 2], [3, null]])).toEqual([1, 3]);
    const [lo, hi] = colorLimits([[5, 5]]);
    expect(lo).toBeCloseTo(4.95);
    expect(hi).toBeCloseTo(5.05);
  });
});

describe("buildBody", () => {
  it("sends every editable value as an override", () => {
    const r = buildBody({ ...INITIAL, reactor: "R", htm: "Water", nusselt: "N" });
    if (!("body" in r)) throw new Error(r.error);
    expect(r.body.rho_kg_m3).toBe(997);
    expect(r.body.lining_thickness_mm).toBe(0);
    expect(r.body.project?.unit_operation).toBe("");
  });

  it("reports the first unusable number", () => {
    expect(buildBody({ ...INITIAL, reactor: "R", wall_k: "" })).toEqual({ error: "Enter a number for Wall k." });
    expect(buildBody(INITIAL)).toEqual({ error: "Select a reactor." });
  });
});
