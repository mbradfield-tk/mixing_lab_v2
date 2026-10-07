import { describe, expect, it } from "vitest";
import {
  INITIAL, blankKpi, buildPlan, completeKpis, dominantTone, kpiStatus, kpiWarning, mirrorKpis, nextVolume, seedKpi,
  testKey, testStages, type KpiRow,
} from "./model";

const COLS = ["Low speed", "Centre", "High speed"];
const row = (p: Partial<KpiRow>): KpiRow => ({ ...blankKpi(), ...p });
const inputs = { ...INITIAL, reactor: "R1", V_L: "0.05" };

describe("buildPlan", () => {
  it("builds the plan body and validates required inputs", () => {
    const b = buildPlan({ ...inputs, fedBatch: true, volumes: ["0.08", ""] });
    expect("body" in b && b.body).toMatchObject({ reactor: "R1", V_L: 0.05, centre_rpm: null, fed_batch_volumes_L: [0.08] });
    expect(buildPlan({ ...inputs, V_L: "" })).toEqual({ error: "Working volume must be greater than 0 L." });
    expect(buildPlan({ ...inputs, centreMode: "custom_rpm", rpmCentre: "0" })).toEqual({ error: "Centre RPM must be greater than 0." });
    const off = buildPlan({ ...inputs, fedBatch: false, volumes: ["0.08"] });
    expect("body" in off && off.body.fed_batch_volumes_L).toEqual([]);
  });

  it("scopes test validity like the Taipy invalidation rules", () => {
    const body = (i = inputs) => (buildPlan(i) as { body: Parameters<typeof testKey>[0] }).body;
    const kpis = { 1: [seedKpi()], 2: [seedKpi()], 3: [seedKpi()] };
    const changedFeed = body({ ...inputs, feedRate: "7" });
    expect(testKey(changedFeed, kpis, 1)).toBe(testKey(body(), kpis, 1));
    expect(testKey(changedFeed, kpis, 2)).not.toBe(testKey(body(), kpis, 2));
    const changedT3 = { ...kpis, 3: [seedKpi("Purity")] };
    expect(testKey(body(), changedT3, 2)).toBe(testKey(body(), kpis, 2));
    expect(testKey(body(), { ...kpis, 1: [seedKpi("Purity")] }, 3)).not.toBe(testKey(body(), kpis, 3));
  });
});

describe("KPI rows", () => {
  it("sends complete rows and words incomplete ones like the Taipy page", () => {
    const c = completeKpis(
      [row({ name: "Yield", unit: "%", low: "80", centre: "90", high: "95", stdDev: "0.5" }), row({ low: "1" }), row({})],
      COLS,
    );
    expect(c.kpis).toEqual([{ name: "Yield", unit: "%", low: 80, centre: 90, high: 95, std_dev: 0.5, replicates: null }]);
    expect(c.incomplete).toEqual(["KPI (missing Centre, High speed)"]);
    expect(kpiWarning(c)).toEqual({ block: false, text: "Skipped incomplete KPI row(s): KPI (missing Centre, High speed)." });
    expect(kpiWarning(completeKpis([row({ centre: "0" })], COLS))).toEqual({
      block: true,
      text: "Enter the low, centre and high responses for at least one KPI before assessing. Incomplete: KPI (missing Low speed, High speed).",
    });
    expect(kpiWarning(completeKpis([row({ low: "0", centre: "0", high: "0" })], COLS))).toBeNull();
  });

  it("mirrors names downstream but keeps matching tables", () => {
    const src = [row({ name: "Purity", unit: "area%", low: "1" }), row({ name: " " })];
    expect(mirrorKpis(src, [seedKpi()])).toEqual([seedKpi("Purity", "area%"), seedKpi("Yield", "")]);
    const typed = [row({ name: "Purity", low: "5" }), row({ name: "Yield", low: "6" })];
    expect(mirrorKpis(src, typed)).toBe(typed);
    expect(mirrorKpis([], [])).toEqual([seedKpi()]);
  });

  it("adds fed-batch milestones one working volume apart", () => {
    expect(nextVolume([], 0.05)).toBe("0.1");
    expect(nextVolume(["0.1", "0.08"], 0.05)).toBe("0.15");
  });
});

describe("outcome dashboard", () => {
  const test = (n: 1 | 2 | 3, status: "sensitive" | "not_sensitive" | "inconclusive") =>
    ({ test: n, status, verdict: "", run_next_test: true, kpis: [], kpi_details: [] });
  const out = {
    tests: [test(1, "sensitive")], dominant: "Incomplete", tentative: false, next_test: 2, summary: "",
    test_lines: ["**Test 1:** sensitive"], conclusion: "", pm_span: 100,
  };

  it("colours the dominant regime by risk", () => {
    expect(dominantTone("Mixing-insensitive", false)).toBe("ok");
    expect(dominantTone("Macromixing", false)).toBe("critical");
    expect(dominantTone("Macromixing", true)).toBe("warning");
    expect(dominantTone("Inconclusive", false)).toBe("unknown");
    expect(dominantTone("Incomplete", false)).toBe("info");
  });

  it("tracks assessed, next and pending tests", () => {
    expect(testStages(out).map((s) => [s.status, s.tone, s.detail])).toEqual([
      ["Sensitive", "critical", "sensitive"],
      ["Run next", "info", undefined],
      ["Pending", "unknown", undefined],
    ]);
    const done = { ...out, tests: [test(1, "not_sensitive")], next_test: 0, dominant: "Mixing-insensitive" };
    expect(testStages(done).map((s) => s.status)).toEqual(["Not sensitive", "Not needed", "Not needed"]);
  });

  it("separates noise-limited KPIs from insensitive ones", () => {
    const k = { name: "Yield", unit: "%", low: 1, centre: 1, high: 1, max_change_pct: 6, threshold_pct: 5, critical: false };
    expect(kpiStatus({ ...k, sensitive: true, noise_limited: false }).label).toBe("Sensitive");
    expect(kpiStatus({ ...k, sensitive: false, noise_limited: true }).tone).toBe("unknown");
    expect(kpiStatus({ ...k, sensitive: false, noise_limited: false }).tone).toBe("ok");
  });
});
