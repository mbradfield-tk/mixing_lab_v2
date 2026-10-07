import { describe, expect, it } from "vitest";
import { INITIAL, buildRequests, comparisonTrxn, kineticsCaption } from "./model";

describe("comparison kinetics", () => {
  it("falls back to 1 s when the kinetics are incomplete", () => {
    expect(comparisonTrxn("1", 0, 0, 0)).toBe(1);
    expect(comparisonTrxn("2", 0.5, 1, 0)).toBe(2);
  });

  it("kineticsCaption matches pages/vessel_comparison._kin_caption", () => {
    expect(kineticsCaption("2", 0.5, 1, 0, -80)).toBe(
      "Effective reaction time **t_rxn = 2 s** (derived from k)  •  ΔH = -80.0 kJ/mol",
    );
    expect(kineticsCaption("1", 0, 0, 0, 0)).toBe(
      "Effective reaction time **t_rxn = 1 s** (fallback)  •  ΔH = 0.0 kJ/mol (heat balance disabled)",
    );
    expect(kineticsCaption("1", 0.01, 0, 69, 0)).toContain("t_rxn = 69 s** (specified)");
  });
});

describe("buildRequests", () => {
  const base = { ...INITIAL, reactors: ["A", "B"], basis: "A", feedBasis: "A" };

  it("needs vessels and numeric conditions", () => {
    expect(buildRequests(INITIAL)).toEqual({ error: "Select at least one vessel to compare." });
    expect(buildRequests({ ...base, T: "" })).toEqual({ error: "Enter a number for Temperature." });
  });

  it("includes options only when switched on", () => {
    const r = buildRequests(base);
    if (!("page" in r)) throw new Error(r.error);
    expect(r.comparison.solids).toBeNull();
    expect(r.comparison.feed).toBeNull();
    expect(r.page.scale_up).toBeNull();
    expect(r.page.feed_schedule).toBeNull();
    expect(r.comparison.gas).toEqual({ present: false, v_s_m_s: 0, coalescing: true });
  });

  it("solids need d50 > 0; feed and scale-up carry their per-vessel tables", () => {
    const r = buildRequests({
      ...base,
      solids: true,
      d50: "0",
      fed: true,
      feedPipe: { A: "3", B: "" },
      scaling: true,
      targets: { B: "2.5" },
      gas: true,
      gasTransfer: "headspace",
    });
    if (!("page" in r)) throw new Error(r.error);
    expect(r.comparison.solids).toBeNull();
    expect(r.comparison.feed).toEqual({ location: "bulk", pipe_id_mm: { A: 3, B: 0 } });
    expect(r.page.feed_schedule).toEqual({ basis_reactor: "A", volume_mL: 100, time_h: 1 });
    expect(r.page.scale_up?.fixed).toEqual({ B: 2.5 });
    expect(r.comparison.gas?.v_s_m_s).toBe(0);
  });

  it("scale-up needs at least two vessels", () => {
    const r = buildRequests({ ...base, reactors: ["A"], scaling: true });
    if (!("page" in r)) throw new Error(r.error);
    expect(r.page.scale_up).toBeNull();
  });
});
