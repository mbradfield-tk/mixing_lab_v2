import { describe, expect, it } from "vitest";
import {
  INITIAL, autoTrxn, buildRequest, heatBalanceTone, kineticModel, solveMessage, solveTiles, suspensionTone, toCsv,
  transferTone, type SolveResult,
} from "./model";

describe("autoTrxn (damkohler.characteristic_reaction_time)", () => {
  it("uses the specified time, else the order-based initial-rate time", () => {
    expect(autoTrxn("2", 0.5, 1, 7)).toBe(7);
    expect(autoTrxn("1", 0.01, 0, 0)).toBeCloseTo(100);
    expect(autoTrxn("pseudo-1", 0.005, 0.1, 0)).toBeCloseTo(200);
    expect(autoTrxn("2", 0.5, 1, 0)).toBe(2);
    expect(autoTrxn("pseudo-2", 0.02, 0.2, 0)).toBe(250);
    expect(autoTrxn("0", 0.5, 1, 0)).toBe(2);
    expect(autoTrxn("2", 0.5, 0, 0)).toBe(0);
    expect(autoTrxn("1", 0, 1, 0)).toBe(0);
  });
});

describe("buildRequest", () => {
  const base = { ...INITIAL, reactor: "TMA EasyMax-102" };

  it("maps the form to a PointRequest; optional phases only when switched on", () => {
    const r = buildRequest(base);
    if (!("request" in r)) throw new Error(r.error);
    expect(r.request.solids).toBeNull();
    expect(r.request.feed).toBeNull();
    expect(r.request.gas).toEqual({ present: false, v_s_m_s: 0, coalescing: true });
    expect(r.request.heat).toEqual({ T_process_C: 25, T_coolant_C: 15 });
    expect(r.request.fluid?.rho_kg_m3).toBe(997);
  });

  it("sends v_s and coalescence only when sparging", () => {
    const head = buildRequest({ ...base, gas: true, gasTransfer: "headspace", coalescing: "non_coalescing" });
    const sparge = buildRequest({ ...base, gas: true, gasTransfer: "sparging", coalescing: "non_coalescing" });
    if (!("request" in head) || !("request" in sparge)) throw new Error("unexpected error");
    expect(head.request.gas).toEqual({ present: true, v_s_m_s: 0, coalescing: true });
    expect(sparge.request.gas).toEqual({ present: true, v_s_m_s: 0.005, coalescing: false });
  });

  it("reports the first unusable number", () => {
    expect(buildRequest({ ...base, N: "" })).toEqual({ error: "Enter a number for Agitation speed." });
    expect(buildRequest({ ...base, solids: true, d50: "x" })).toEqual({ error: "Enter a number for d50." });
    expect(buildRequest({ ...INITIAL })).toEqual({ error: "Select a vessel." });
  });
});

describe("text ports", () => {
  it("kineticModel", () => {
    expect(kineticModel("2", 0.5, "L/(mol·s)", -80)).toBe("Order 2 · k = 0.5 L/(mol·s) · exothermic (ΔH = -80 kJ/mol)");
    expect(kineticModel("1", 0.01, "1/s", 0)).toBe("Order 1 · k = 0.01 1/s · athermal");
  });

  const res = (patch: Partial<SolveResult>): SolveResult => ({
    parameter: "P_V_W_L",
    target: 0.5,
    solve_for: "N_rpm",
    status: "solved",
    best: 412.345,
    solutions: [{ value: 412.345, achieved: 0.5, in_vessel_range: true }],
    search_range: [12.5, 2000],
    vessel_range: [50, 1000],
    achievable_span: [0.0001, 30],
    ...patch,
  });
  const ctx = { N_rpm: 525, V_L: 0.055, corrLabel: "Empirical (literature)" };

  it("solveMessage covers the three outcomes", () => {
    expect(solveMessage(res({}), "P/V (W/L)", ctx).text).toBe(
      "Solution: N = 412.3 RPM gives P/V (W/L) = 0.5 at V = 0.055 L (Empirical (literature)).",
    );
    expect(solveMessage(res({ status: "outside_vessel_range", best: null }), "P/V (W/L)", ctx).text).toBe(
      "Solution outside vessel range: P/V (W/L) = 0.5 needs N = 412.3 RPM at V = 0.055 L; vessel window is N = 50–1000 RPM.",
    );
    expect(
      solveMessage(res({ status: "unreachable", best: null, solutions: [], solve_for: "V_L" }), "P/V (W/L)", ctx).text,
    ).toBe("No solution: P/V (W/L) = 0.5 is not reachable for V = 12.5–2000 L at N = 525 RPM (achievable range 0.0001–30).");
  });

  it("toCsv quotes like pandas", () => {
    expect(toCsv([{ Parameter: "Power", Value: "1,234", Units: "W" }])).toBe('Parameter,Value,Units\nPower,"1,234",W\n');
  });
});

describe("result status tones", () => {
  it("classifies the suspension, heat-balance and mass-transfer labels", () => {
    expect(suspensionTone("Poorly suspended (N/Njs=0.45)")).toBe("critical");
    expect(suspensionTone("Just suspended (N/Njs=1.02)")).toBe("warning");
    expect(suspensionTone("Fully suspended (N/Njs=1.60)")).toBe("ok");
    expect(heatBalanceTone("🔴 Insufficient cooling (Q_gen/Q_cool = 1.20)")).toBe("critical");
    expect(heatBalanceTone("Moderate – monitor closely (Q_gen/Q_cool = 0.60)")).toBe("warning");
    expect(heatBalanceTone("Comfortable margin (Q_gen/Q_cool = 0.30)")).toBe("ok");
    expect(transferTone("Potentially transfer-limited")).toBe("critical");
    expect(transferTone("Capacity comparable to demand")).toBe("warning");
    expect(transferTone("Capacity exceeds kinetic demand")).toBe("ok");
    expect(transferTone("Unknown — kLa unavailable")).toBe("unknown");
  });

  it("summarises a Solve-for outcome as tiles", () => {
    const base: SolveResult = {
      parameter: "P_V_W_L", target: 1, solve_for: "N_rpm", status: "solved", best: 760.42,
      solutions: [{ value: 760.42, achieved: 1.0, in_vessel_range: true }],
      search_range: [12.5, 2000], vessel_range: [50, 1000], achievable_span: null,
    };
    const tiles = solveTiles(base, "P/V (W/L)", { N_rpm: 400, V_L: 0.055 });
    expect(tiles.map((t) => [t.label, t.value, t.unit, t.tone])).toEqual([
      ["Agitation speed N", "760.4", "RPM", "ok"],
      ["Target P/V (W/L)", "1", undefined, undefined],
      ["Held: working volume V", "0.055", "L", undefined],
      ["Vessel window", "50–1000", "RPM", undefined],
    ]);
    expect(tiles[0].hint).toBe("Solution found · gives 1");
    const out = solveTiles({ ...base, status: "outside_vessel_range", best: null }, "P/V (W/L)", { N_rpm: 400, V_L: 0.055 });
    expect([out[0].tone, out[0].hint]).toEqual(["warning", "Outside the vessel window · gives 1"]);
    const none = solveTiles(
      { ...base, solve_for: "V_L", status: "unreachable", best: null, solutions: [], achievable_span: [0.1, 0.4] },
      "P/V (W/L)",
      { N_rpm: 400, V_L: 0.055 },
    );
    expect(none.map((t) => t.value)).toEqual(["No solution", "1", "400", "50–1000"]);
    expect([none[0].tone, none[0].hint, none[2].label]).toEqual(["critical", "Achievable P/V (W/L): 0.1–0.4", "Held: agitation speed N"]);
  });
});
