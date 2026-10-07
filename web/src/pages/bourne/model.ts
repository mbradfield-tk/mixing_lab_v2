import type { Schemas } from "../../api/client";

export type TestNo = 1 | 2 | 3;
export type CentreMode = Schemas["CenterMode"];
export type FeedBasis = Schemas["FeedBasis"];
export type PlanBody = Schemas["BournePlanRequest"];
export type KpiResponse = Schemas["KpiResponse"];

/** One editable KPI row; numbers are kept as typed text. */
export interface KpiRow {
  name: string;
  unit: string;
  low: string;
  centre: string;
  high: string;
  stdDev: string;
  replicates: string;
}

export interface Inputs {
  reactor: string;
  fluid: string;
  T: string;
  P: string;
  V_L: string;
  centreMode: CentreMode;
  pmCentre: string;
  rpmCentre: string;
  fedBatch: boolean;
  volumes: string[];
  feedVolume: string;
  feedBasis: FeedBasis;
  feedRate: string;
  feedTime: string;
  surface: string;
  mid: string;
  impeller: string;
}

export const INITIAL: Inputs = {
  reactor: "",
  fluid: "Water",
  T: "25",
  P: "1",
  V_L: "",
  centreMode: "default",
  pmCentre: "0.2",
  rpmCentre: "300",
  fedBatch: false,
  volumes: [],
  feedVolume: "100",
  feedBasis: "rate",
  feedRate: "5",
  feedTime: "20",
  surface: "0.1",
  mid: "1",
  impeller: "3",
};

export const CENTRE_MODES: { code: CentreMode; label: string }[] = [
  { code: "default", label: "Default (0.2 W/kg)" },
  { code: "custom_pm", label: "Custom P/m" },
  { code: "custom_rpm", label: "Custom RPM" },
];

export const FEED_BASES: { code: FeedBasis; label: string }[] = [
  { code: "rate", label: "Feed rate" },
  { code: "time", label: "Feed time" },
];

/** Blank / non-numeric text -> NaN (never 0), as in ``utils.bourne_kpi._num``. */
export const parse = (v: string): number => (v.trim() === "" ? Number.NaN : Number(v));
const positive = (v: string, fallback: number) => {
  const x = parse(v);
  return Number.isFinite(x) && x > 0 ? x : fallback;
};

export const round3 = (x: number) => Math.round(x * 1000) / 1000;

/** Request body for the plan / assess endpoints, or the first input problem. */
export function buildPlan(i: Inputs): { body: PlanBody } | { error: string } {
  if (!i.reactor) return { error: "Choose a vessel." };
  const vL = parse(i.V_L);
  if (!(vL > 0)) return { error: "Working volume must be greater than 0 L." };
  const P = parse(i.P);
  if (!(P > 0)) return { error: "Pressure must be greater than 0 atm." };
  const T = parse(i.T);
  if (!Number.isFinite(T)) return { error: "Enter a temperature." };
  if (i.centreMode === "custom_pm" && !(parse(i.pmCentre) > 0))
    return { error: "Centre P/m must be greater than 0 W/kg." };
  if (i.centreMode === "custom_rpm" && !(parse(i.rpmCentre) > 0))
    return { error: "Centre RPM must be greater than 0." };
  return {
    body: {
      reactor: i.reactor,
      fluid: i.fluid,
      T_C: T,
      P_atm: P,
      V_L: vL,
      centre: i.centreMode,
      centre_pm_W_kg: positive(i.pmCentre, 0.2),
      centre_rpm: i.centreMode === "custom_rpm" ? parse(i.rpmCentre) : null,
      fed_batch_volumes_L: i.fedBatch ? i.volumes.map(parse).filter((v) => Number.isFinite(v)) : [],
      feed_volume_mL: positive(i.feedVolume, 100),
      feed_basis: i.feedBasis,
      feed_rate_mL_min: positive(i.feedRate, 5),
      feed_time_min: positive(i.feedTime, 20),
      surface_ratio: positive(i.surface, 0.1),
      mid_ratio: positive(i.mid, 1),
      impeller_ratio: positive(i.impeller, 3),
    },
  };
}

/** Inputs each test's verdict depends on (Taipy invalidation scopes). */
export function testScope(body: PlanBody, n: TestNo): Partial<PlanBody> {
  const { reactor, fluid, T_C, P_atm, V_L, centre, centre_pm_W_kg, centre_rpm } = body;
  const scope: Partial<PlanBody> = { reactor, fluid, T_C, P_atm, V_L, centre, centre_pm_W_kg, centre_rpm };
  if (n >= 2) Object.assign(scope, { feed_volume_mL: body.feed_volume_mL, feed_basis: body.feed_basis, feed_rate_mL_min: body.feed_rate_mL_min, feed_time_min: body.feed_time_min });
  if (n >= 3) Object.assign(scope, { surface_ratio: body.surface_ratio, mid_ratio: body.mid_ratio, impeller_ratio: body.impeller_ratio });
  return scope;
}

/** Validity key of Test ``n``: its input scope plus the KPI tables of Tests 1..n. */
export const testKey = (body: PlanBody, kpis: Record<TestNo, KpiRow[]>, n: TestNo) =>
  JSON.stringify([testScope(body, n), ([1, 2, 3] as TestNo[]).filter((t) => t <= n).map((t) => kpis[t])]);

export const blankKpi = (): KpiRow => ({ name: "", unit: "", low: "", centre: "", high: "", stdDev: "", replicates: "" });
export const seedKpi = (name = "Yield", unit = "%"): KpiRow => ({ ...blankKpi(), name, unit });

const rowName = (r: KpiRow) => r.name.trim() || "KPI";

/** Complete rows as API responses, plus the incomplete-row descriptions (Taipy wording). */
export function completeKpis(rows: KpiRow[], columns: string[]): { kpis: KpiResponse[]; incomplete: string[] } {
  const kpis: KpiResponse[] = [];
  const incomplete: string[] = [];
  for (const r of rows) {
    const vals = [parse(r.low), parse(r.centre), parse(r.high)];
    const missing = columns.filter((_, k) => Number.isNaN(vals[k]));
    if (missing.length === 0) {
      const sd = parse(r.stdDev);
      const reps = parse(r.replicates);
      kpis.push({
        name: rowName(r),
        unit: r.unit.trim(),
        low: vals[0],
        centre: vals[1],
        high: vals[2],
        std_dev: Number.isFinite(sd) ? sd : null,
        replicates: Number.isFinite(reps) ? reps : null,
      });
    } else if (missing.length < 3) {
      incomplete.push(`${rowName(r)} (missing ${missing.join(", ")})`);
    }
  }
  return { kpis, incomplete };
}

/** Warning for an assess click: blocks when nothing is complete. */
export function kpiWarning(c: { kpis: KpiResponse[]; incomplete: string[] }): { block: boolean; text: string } | null {
  if (!c.kpis.length) {
    let text = "Enter the low, centre and high responses for at least one KPI before assessing.";
    if (c.incomplete.length) text += ` Incomplete: ${c.incomplete.join("; ")}.`;
    return { block: true, text };
  }
  if (c.incomplete.length) return { block: false, text: `Skipped incomplete KPI row(s): ${c.incomplete.join("; ")}.` };
  return null;
}

/** Carry KPI names / units downstream; keep ``existing`` when its names already match. */
export function mirrorKpis(src: KpiRow[], existing: KpiRow[]): KpiRow[] {
  let names = src.map((r) => [r.name.trim() ? rowName(r) : "Yield", r.unit.trim()] as const);
  if (!names.length) names = [["Yield", "%"]];
  if (existing.length && existing.map((r) => r.name.trim()).join("\u0000") === names.map(([n]) => n).join("\u0000"))
    return existing;
  return names.map(([n, u]) => seedKpi(n, u));
}

/** Next fed-batch milestone: the largest volume (or V) plus V. */
export function nextVolume(volumes: string[], vL: number): string {
  const vols = volumes.map(parse).filter((v) => v > 0);
  const base = vols.length ? Math.max(...vols) : vL;
  return String(round3(base + vL));
}

type Tone = "critical" | "warning" | "ok" | "unknown" | "info";
type Status = Schemas["BourneTestOut"]["status"];

export const STATUS_LABEL: Record<Status, string> = {
  sensitive: "Sensitive",
  not_sensitive: "Not sensitive",
  inconclusive: "Inconclusive",
};
export const STATUS_TONE: Record<Status, Tone> = { sensitive: "critical", not_sensitive: "ok", inconclusive: "warning" };

export const TEST_TITLES: Record<TestNo, string> = { 1: "Impeller speed", 2: "Feed rate", 3: "Feed location" };

/** Banner tone of the decision-tree outcome: a confirmed mixing regime is the headline risk. */
export function dominantTone(dominant: string, tentative: boolean): Tone {
  if (dominant === "Mixing-insensitive") return "ok";
  if (["Micromixing", "Mesomixing", "Macromixing"].includes(dominant)) return tentative ? "warning" : "critical";
  if (dominant === "Inconclusive") return "unknown";
  return "info";
}

/** Stage tracker items for Tests 1-3 from an assessment. */
export function testStages(out: Schemas["BourneAssessResult"]): { label: string; status: string; tone: Tone; detail?: string }[] {
  return ([1, 2, 3] as TestNo[]).map((n) => {
    const label = `Test ${n} · ${TEST_TITLES[n]}`;
    const k = out.tests.findIndex((t) => t.test === n);
    if (k >= 0) {
      const t = out.tests[k];
      return {
        label,
        status: STATUS_LABEL[t.status],
        tone: STATUS_TONE[t.status],
        detail: out.test_lines[k]?.replace(/^\*\*Test \d:\*\*\s*/, ""),
      };
    }
    if (out.next_test === n) return { label, status: "Run next", tone: "info" };
    return { label, status: out.next_test && n > out.next_test ? "Pending" : "Not needed", tone: "unknown" };
  });
}

/** KPI card status: noise-limited changes are reported separately from "not sensitive". */
export function kpiStatus(k: Schemas["BourneKpiDetail"]): { label: string; tone: Tone } {
  if (k.sensitive) return { label: "Sensitive", tone: "critical" };
  if (k.noise_limited) return { label: "Within noise", tone: "unknown" };
  return { label: "Not sensitive", tone: "ok" };
}
