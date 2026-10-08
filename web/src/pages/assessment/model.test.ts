import { describe, expect, it } from "vitest";
import {
  INITIAL, autoTrxn, buildFilling, buildRequest, buildTemperature, defaultDose, feedRateMlMin, fillingRows, fillingTiles,
  heatBalanceTone, kineticModel, sliderStep, solveMessage, solveTiles, suspensionTone, temperatureTiles, toCsv,
  transferTone, type FillingResult, type PointRequest, type SolveResult, type TemperatureResult,
} from "./model";

describe("fed-batch dosing and filling", () => {
  it("derives the feed rate and slider increments", () => {
    expect(feedRateMlMin("0.04", "2")).toBeCloseTo(40 / 120);
    expect(feedRateMlMin("1000", "10")).toBeCloseTo(1666.67, 1);
    expect(feedRateMlMin("", "1")).toBeNaN();
    expect(feedRateMlMin("1", "0")).toBeNaN();
    // 100 mL span -> 5 mL; 1000 L span -> 10 L; 50-1000 RPM -> 10 RPM
    expect(sliderStep(0.1)).toBe(0.005);
    expect(sliderStep(1000)).toBe(10);
    expect(sliderStep(950)).toBe(10);
    expect(sliderStep(0.09)).toBe(0.005);
    expect(sliderStep(13674)).toBe(100);
    expect(sliderStep(0)).toBe(1);
    expect(defaultDose(0.055, 0.1)).toBe(0.023);
    expect(defaultDose(1, 1)).toBe(0.2);
  });

  it("builds the filling request only when simulating, and validates the dosing inputs", () => {
    const point = { reactor: "R" } as PointRequest;
    const fed = { ...INITIAL, fed: true, simulateFilling: true, dosingTime: "2", dosingAmount: "0.04", feedFluid: "Toluene" };
    expect(buildFilling({ ...fed, simulateFilling: false }, point)).toEqual({ filling: null });
    expect(buildFilling({ ...fed, fed: false }, point)).toEqual({ filling: null });
    expect(buildFilling(fed, point)).toEqual({
      filling: { point, dosing_time_h: 2, dosing_amount_L: 0.04, feed_fluid: "Toluene", n_steps: 50 },
    });
    expect(buildFilling({ ...fed, dosingTime: "0" }, point)).toEqual({ error: "Enter a dosing time above 0 h." });
    expect(buildFilling({ ...fed, dosingAmount: "" }, point)).toEqual({ error: "Enter a dosing amount above 0 L." });
  });

  it("sends the dosing rate, temperature and fluid with the feed", () => {
    const fed = { ...INITIAL, reactor: "TMA EasyMax-102", fed: true, dosingTime: "2", dosingAmount: "0.04", feedFluid: "Toluene", feedT: "5" };
    const r = buildRequest(fed);
    if ("error" in r) throw new Error(r.error);
    expect(r.request.feed).toMatchObject({ T_C: 5, fluid: "Toluene", d_pipe_mm: 3 });
    expect(r.request.feed?.rate_mL_min).toBeCloseTo(40 / 120);
    const noRate = buildRequest({ ...fed, dosingAmount: "" });
    if ("error" in noRate) throw new Error(noRate.error);
    expect(noRate.request.feed?.rate_mL_min).toBeNull();
    expect(buildRequest({ ...fed, feedT: "" })).toEqual({ error: expect.stringContaining("Dosing temperature") });
  });

  it("sends no reaction and skips the kinetics checks when 'No reaction' is selected", () => {
    const r = buildRequest({ ...INITIAL, reactor: "R", reactionSource: "none", k: "" });
    if ("error" in r) throw new Error(r.error);
    expect(r.request.reaction).toBeNull();
    expect(buildRequest({ ...INITIAL, reactor: "R", k: "" })).toEqual({ error: "Enter a number for k." });
  });

  it("simulates the dosed scenario when dosing is defined, else the batch with reaction heat", () => {
    const point = { reactor: "R", reaction: { dH_kJ_mol: -80 } } as PointRequest;
    const fed = { ...INITIAL, fed: true, dosingTime: "2", dosingAmount: "0.04" };
    expect(buildTemperature(fed, point)).toEqual({ point, dosing_time_h: 2, dosing_amount_L: 0.04 });
    expect(buildTemperature({ ...fed, fed: false }, point)).toEqual({ point });
    expect(buildTemperature(INITIAL, { ...point, reaction: { dH_kJ_mol: 0 } } as PointRequest)).toBeNull();
    expect(buildTemperature(INITIAL, { ...point, reaction: null })).toBeNull();
    expect(buildTemperature(fed, { ...point, reaction: null })).toMatchObject({ dosing_time_h: 2 });
  });

  it("summarises a temperature profile", () => {
    const r = {
      scenario: "batch", T_start_C: 25, T_max_C: 30.76, t_T_max_min: 0.3, T_min_C: 15, t_T_min_min: 33,
      T_end_C: 15.01, T_ad_C: 48.98, dT_ad_K: 23.98, final_conversion: 0.99, t_99_min: 33, Q_rxn_total_kJ: 5,
    } as TemperatureResult;
    const tiles = temperatureTiles(r);
    expect(tiles.map((t) => t.label)).toEqual([
      "Start temperature", "Peak temperature (at 0.3 min)", "Lowest temperature (at 33 min)", "End (99 % conversion)",
      "No-cooling end temperature", "Reaction heat (total)", "Final conversion", "Time to 99 % conversion",
    ]);
    expect(tiles[4].value).toBe("48.98 (+24 K)");
    const dosed = temperatureTiles({ ...r, scenario: "dosed", Q_rxn_total_kJ: 0, t_99_min: null });
    expect(dosed.map((t) => t.label)).toContain("End of dosing");
    expect(dosed.map((t) => t.label)).not.toContain("Reaction heat (total)");
  });

  it("summarises the filling profile as start-to-end tiles and table rows", () => {
    const res: FillingResult = {
      time_min: [0, 60, 120],
      V_L: [0.05, 0.07, 0.09],
      V_end_L: 0.09,
      feed_rate_mL_min: 0.333,
      warnings: [],
      series: [
        { field: "V_L", label: "Fill volume (L)", group: "fluid", values: [0.05, 0.07, 0.09] },
        { field: "rho_kg_m3", label: "Density ρ (kg/m³)", group: "fluid", values: [997, 965, 937] },
        { field: "Re", label: "Re", group: "hydrodynamics", values: [6721.3, 7200, 7667.9] },
      ],
    };
    expect(fillingTiles(res)).toEqual([
      { label: "Fill volume", value: "0.05 → 0.09", unit: "L" },
      { label: "Density ρ", value: "997 → 937", unit: "kg/m³" },
      { label: "Re", value: "6.72e+03 → 7.67e+03", unit: undefined },
    ]);
    expect(fillingRows(res)[2]).toEqual({ "Time (min)": "120", "Fill volume (L)": "0.09", "Density ρ (kg/m³)": "937", Re: "7.67e+03" });
  });
});

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
    expect(r.request.heat).toEqual({ T_process_C: 25, T_coolant_C: 15, htm: null, v_jacket_m_s: 1, d_hyd_jacket_m: 0.05 });
    const withHtf = buildRequest({ ...base, htm: "Water-Glycol (50/50)" });
    if (!("request" in withHtf)) throw new Error(withHtf.error);
    expect(withHtf.request.heat?.htm).toBe("Water-Glycol (50/50)");
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
    expect(heatBalanceTone("Net cooling by the feed - no heat to remove")).toBe("ok");
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
      ["Held: fill volume V", "0.055", "L", undefined],
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
