import type { Schemas } from "../../api/client";
import { formatG } from "../../format";

export type PointRequest = Schemas["PointRequest"];
export type ReactionOrder = NonNullable<NonNullable<PointRequest["reaction"]>["order"]>;
export const ORDERS: ReactionOrder[] = ["1", "2", "pseudo-1", "pseudo-2", "0"];

/** Form state; numbers are kept as typed text and parsed when a request is built. */
export interface Inputs {
  reactor: string;
  T: string;
  P: string;
  Tcool: string;
  N: string;
  V: string;
  fed: boolean;
  dosingTime: string;
  dosingAmount: string;
  feedFluid: string;
  feedT: string;
  simulateFilling: boolean;
  feedDiam: string;
  feedLocation: string;
  dTank: string;
  dImp: string;
  Np: string;
  Nq: string;
  fluid: string;
  rho: string;
  mu: string;
  dmol: string;
  sigma: string;
  solids: boolean;
  particle: string;
  rhoP: string;
  d50: string;
  phi: string;
  xWt: string;
  szw: string;
  gmbZ: string;
  cd: string;
  gas: boolean;
  gasTransfer: string;
  vs: string;
  coalescing: string;
  reactionSource: "measured" | "classes" | "none";
  reaction: string;
  order: ReactionOrder;
  k: string;
  c0: string;
  trxn: string;
  dH: string;
  corr: string;
}

export const INITIAL: Inputs = {
  reactor: "",
  T: "25",
  P: "1",
  Tcool: "15",
  N: "300",
  V: "1",
  fed: false,
  dosingTime: "1",
  dosingAmount: "0.1",
  feedFluid: "Water",
  feedT: "25",
  simulateFilling: false,
  feedDiam: "3",
  feedLocation: "bulk",
  dTank: "0.1",
  dImp: "0.05",
  Np: "1.27",
  Nq: "0.79",
  fluid: "Water",
  rho: "997",
  mu: "0.00089",
  dmol: "2.3e-9",
  sigma: "0.072",
  solids: false,
  particle: "",
  rhoP: "1500",
  d50: "50",
  phi: "1",
  xWt: "5",
  szw: "5.5",
  gmbZ: "3",
  cd: "0.33",
  gas: false,
  gasTransfer: "headspace",
  vs: "0.005",
  coalescing: "coalescing",
  reactionSource: "measured",
  reaction: "",
  order: "1",
  k: "0.01",
  c0: "0.1",
  trxn: "0",
  dH: "0",
  corr: "Literature",
};

const n = (s: string): number => (s.trim() === "" ? Number.NaN : Number(s));

/** Characteristic reaction time (utils.calculations.damkohler.characteristic_reaction_time). */
export function autoTrxn(order: string, k: number, c0: number, tSpecified: number): number {
  if (tSpecified > 0) return tSpecified;
  if (!(k > 0)) return 0;
  const o = order.trim();
  if (o === "1" || o === "pseudo-1") return 1 / k;
  if ((o === "2" || o === "pseudo-2") && c0 > 0) return 1 / (k * c0);
  if (o === "0" && c0 > 0) return c0 / k;
  return 0;
}

export const asOrder = (value: unknown): ReactionOrder =>
  ORDERS.includes(String(value) as ReactionOrder) ? (String(value) as ReactionOrder) : "1";

/** The API request for the current inputs, or the name of the first unusable number. */
export function buildRequest(i: Inputs): { request: PointRequest } | { error: string } {
  const noReaction = i.reactionSource === "none";
  const required: [string, string][] = [
    ["Temperature", i.T], ["Pressure", i.P], ["Coolant temp", i.Tcool], ["Agitation speed", i.N],
    ["Fill volume", i.V], ["D_tank", i.dTank], ["D_imp", i.dImp], ["Np", i.Np], ["Nq", i.Nq],
    ["ρ", i.rho], ["μ", i.mu], ["D_mol", i.dmol],
  ];
  if (!noReaction) required.push(["k", i.k], ["C0", i.c0], ["t_rxn", i.trxn], ["ΔH_rxn", i.dH]);
  if (i.solids)
    required.push(["ρ_p", i.rhoP], ["d50", i.d50], ["φ", i.phi], ["Solids loading", i.xWt],
      ["Zwietering S", i.szw], ["GMB z", i.gmbZ], ["C/D", i.cd]);
  if (i.fed) required.push(["Feed pipe ID", i.feedDiam], ["Dosing temperature", i.feedT]);
  if (i.gas && i.gasTransfer === "sparging") required.push(["v_s", i.vs]);
  const bad = required.find(([, v]) => !Number.isFinite(n(v)));
  if (bad) return { error: `Enter a number for ${bad[0]}.` };
  if (!i.reactor) return { error: "Select a vessel." };

  const sparged = i.gas && i.gasTransfer === "sparging";
  const rate = feedRateMlMin(i.dosingAmount, i.dosingTime);
  return {
    request: {
      reactor: i.reactor,
      N_rpm: n(i.N),
      V_L: n(i.V),
      corr_source: i.corr as PointRequest["corr_source"],
      fluid: {
        name: i.fluid,
        T_C: n(i.T),
        P_atm: n(i.P),
        rho_kg_m3: n(i.rho),
        mu_Pa_s: n(i.mu),
        D_mol_m2_s: n(i.dmol),
      },
      reaction: noReaction
        ? null
        : { order: i.order, k: n(i.k), C0_mol_L: n(i.c0), t_rxn_s: n(i.trxn), dH_kJ_mol: n(i.dH) },
      gas: { present: i.gas, v_s_m_s: sparged ? n(i.vs) : 0, coalescing: sparged ? i.coalescing === "coalescing" : true },
      solids: i.solids
        ? {
            rho_p_kg_m3: n(i.rhoP),
            d50_um: n(i.d50),
            sphericity: n(i.phi),
            loading_g_per_100g: n(i.xWt),
            zwietering_S: n(i.szw),
            gmb_z: n(i.gmbZ),
            clearance_ratio: n(i.cd),
          }
        : null,
      feed: i.fed
        ? {
            location: i.feedLocation as "bulk",
            d_pipe_mm: n(i.feedDiam),
            rate_mL_min: Number.isFinite(rate) ? rate : null,
            T_C: n(i.feedT),
            fluid: i.feedFluid || null,
          }
        : null,
      heat: { T_process_C: n(i.T), T_coolant_C: n(i.Tcool) },
      geometry: { D_tank_m: n(i.dTank), D_imp_m: n(i.dImp), Np: n(i.Np), Nq: n(i.Nq) },
    },
  };
}

export type FillingRequest = Schemas["FillingRequest"];
export type FillingResult = Schemas["FillingResult"];

/** Feed rate (mL/min) from the dosing amount (L) and time (h); NaN when either is unusable. */
export function feedRateMlMin(dosingAmountL: string, dosingTimeH: string): number {
  const amount = n(dosingAmountL);
  const time = n(dosingTimeH);
  return amount > 0 && time > 0 ? (amount * 1000) / (time * 60) : Number.NaN;
}

const nice125 = (x: number): number => {
  const e = Math.floor(Math.log10(x));
  const f = x / 10 ** e;
  return (f < 1.5 ? 1 : f < 3.5 ? 2 : f < 7.5 ? 5 : 10) * 10 ** e;
};

/** Slider increment for a span: about 20 steps below a span of 10, about 100 above, rounded to 1/2/5. */
export function sliderStep(span: number): number {
  if (!(span > 0)) return 1;
  return Number(nice125(span < 10 ? span / 20 : span / 100).toPrecision(1));
}

/** Default dosing amount: half the headroom to the vessel maximum, else 20 % of the fill. */
export function defaultDose(vL: number, vMax: number): number {
  const amount = vMax > vL ? (vMax - vL) / 2 : vL * 0.2;
  return Number(amount.toPrecision(2));
}

/** The filling-simulation request, null when not requested, or the first unusable input. */
export function buildFilling(i: Inputs, point: PointRequest): { filling: FillingRequest | null } | { error: string } {
  if (!i.fed || !i.simulateFilling) return { filling: null };
  if (!(n(i.dosingTime) > 0)) return { error: "Enter a dosing time above 0 h." };
  if (!(n(i.dosingAmount) > 0)) return { error: "Enter a dosing amount above 0 L." };
  if (!i.feedFluid) return { error: "Select the dosed fluid." };
  return {
    filling: {
      point,
      dosing_time_h: n(i.dosingTime),
      dosing_amount_L: n(i.dosingAmount),
      feed_fluid: i.feedFluid,
      n_steps: 50,
    },
  };
}

const g3 = (x: number | null | undefined) => (x === null || x === undefined ? "—" : formatG(x, 3));

export type TemperatureRequest = Schemas["TemperatureRequest"];
export type TemperatureResult = Schemas["TemperatureResult"];

/** Damköhler parameters are meaningless without a reaction. */
export const isDamkohler = (field: string) => field.startsWith("Da_");

/**
 * Batch-temperature request: the dosed scenario when fed-batch dosing is defined, else the
 * batch scenario when the reaction releases or absorbs heat; null when nothing heats the batch.
 */
export function buildTemperature(i: Inputs, point: PointRequest): TemperatureRequest | null {
  if (i.fed && n(i.dosingTime) > 0 && n(i.dosingAmount) > 0)
    return { point, dosing_time_h: n(i.dosingTime), dosing_amount_L: n(i.dosingAmount) };
  if (point.reaction && point.reaction.dH_kJ_mol) return { point };
  return null;
}

/** Headline tiles of a temperature profile. */
export function temperatureTiles(r: TemperatureResult): { label: string; value: string; unit?: string }[] {
  const reaction = r.Q_rxn_total_kJ !== 0;
  const tiles = [
    { label: "Start temperature", value: formatG(r.T_start_C, 4), unit: "°C" },
    { label: `Peak temperature (at ${g3(r.t_T_max_min)} min)`, value: formatG(r.T_max_C, 4), unit: "°C" },
  ];
  if (r.T_min_C < r.T_start_C - 0.05)
    tiles.push({ label: `Lowest temperature (at ${g3(r.t_T_min_min)} min)`, value: formatG(r.T_min_C, 4), unit: "°C" });
  tiles.push(
    { label: r.scenario === "dosed" ? "End of dosing" : "End (99 % conversion)", value: formatG(r.T_end_C, 4), unit: "°C" },
    {
      label: "No-cooling end temperature",
      value: `${formatG(r.T_ad_C, 4)} (${r.dT_ad_K >= 0 ? "+" : ""}${formatG(r.dT_ad_K, 3)} K)`,
      unit: "°C",
    },
  );
  if (reaction) {
    tiles.push(
      { label: "Reaction heat (total)", value: formatG(r.Q_rxn_total_kJ, 3), unit: "kJ" },
      { label: r.scenario === "dosed" ? "Conversion at end of dosing" : "Final conversion", value: formatG(r.final_conversion * 100, 3), unit: "%" },
    );
    if (r.t_99_min !== null && r.t_99_min !== undefined)
      tiles.push({ label: "Time to 99 % conversion", value: formatG(r.t_99_min, 3), unit: "min" });
  }
  return tiles;
}

// Series summarised as start -> end tiles above the Filling Dynamics charts.
const FILLING_TILES = ["V_L", "rho_kg_m3", "mu_Pa_s", "Re", "P_V_W_L", "blend_time_95_s", "Da_macro", "Da_micro"];

/** "start → end" tiles for the headline filling series that are present. */
export function fillingTiles(res: FillingResult): { label: string; value: string; unit?: string }[] {
  return FILLING_TILES.flatMap((field) => {
    const s = res.series.find((x) => x.field === field);
    if (!s) return [];
    const m = /^(.*?)\s*\(([^()]*)\)\s*$/.exec(s.label);
    return [{ label: m ? m[1] : s.label, value: `${g3(s.values[0])} → ${g3(s.values[s.values.length - 1])}`, unit: m?.[2] }];
  });
}

/** One row per time step (time, then every series) for the data table and CSV. */
export function fillingRows(res: FillingResult): Record<string, string>[] {
  return res.time_min.map((t, k) => ({
    "Time (min)": formatG(t, 4),
    ...Object.fromEntries(res.series.map((s) => [s.label, g3(s.values[k])])),
  }));
}

/** "Order 2 · k = 0.5 L/(mol·s) · exothermic (ΔH = -80 kJ/mol)" (pages/vessel_assessment._kinetic_model). */
export function kineticModel(order: string, k: number, kUnits: string, dH: number): string {
  const thermo =
    dH === 0
      ? "athermal"
      : dH < 0
        ? `exothermic (ΔH = ${formatG(dH)} kJ/mol)`
        : `endothermic (ΔH = ${formatG(dH)} kJ/mol)`;
  return `Order ${order} · k = ${formatG(k)} ${kUnits}`.trimEnd() + ` · ${thermo}`;
}

/** `POST /assessment/solve` response (tuples arrive as plain arrays). */
export interface SolveResult {
  parameter: string;
  target: number;
  solve_for: "N_rpm" | "V_L";
  status: "solved" | "outside_vessel_range" | "unreachable";
  best: number | null;
  solutions: { value: number; achieved: number | null; in_vessel_range: boolean }[];
  search_range: number[];
  vessel_range: number[];
  achievable_span: (number | null)[] | null;
}

/** Solve-for status line (pages/vessel_assessment.on_va_solve). */
export function solveMessage(
  res: SolveResult,
  label: string,
  context: { N_rpm: number; V_L: number; corrLabel: string },
): { kind: "success" | "error" | "info"; text: string } {
  const solveN = res.solve_for === "N_rpm";
  const [name, unit] = solveN ? ["N", "RPM"] : ["V", "L"];
  const fixed = solveN ? `V = ${formatG(context.V_L, 3)} L` : `N = ${context.N_rpm.toFixed(0)} RPM`;
  const g4 = (x: number) => formatG(x, 4);
  const [lo, hi] = res.search_range;
  const [wlo, whi] = res.vessel_range;
  if (res.status === "unreachable") {
    const span = res.achievable_span;
    const spanText =
      span && span[0] !== null && span[1] !== null ? `${g4(span[0])}–${g4(span[1])}` : "n/a";
    return {
      kind: "error",
      text: `No solution: ${label} = ${formatG(res.target)} is not reachable for ${name} = ${g4(lo)}–${g4(hi)} ${unit} at ${fixed} (achievable range ${spanText}).`,
    };
  }
  if (res.status === "outside_vessel_range")
    return {
      kind: "error",
      text: `Solution outside vessel range: ${label} = ${formatG(res.target)} needs ${name} = ${g4(res.solutions[0].value)} ${unit} at ${fixed}; vessel window is ${name} = ${g4(wlo)}–${g4(whi)} ${unit}.`,
    };
  const extra = res.solutions.length > 1 ? " (multiple solutions — see table)" : "";
  return {
    kind: "success",
    text: `Solution: ${name} = ${g4(res.best as number)} ${unit} gives ${label} = ${formatG(res.target)} at ${fixed} (${context.corrLabel})${extra}.`,
  };
}

function csvCell(v: unknown): string {
  const s = v === null || v === undefined ? "" : String(v);
  return /[",\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

/** pandas ``to_csv(index=False)`` for a list of records. */
export function toCsv(rows: Record<string, unknown>[]): string {
  if (!rows.length) return "";
  const cols = Object.keys(rows[0]);
  return [cols.map(csvCell).join(","), ...rows.map((r) => cols.map((c) => csvCell(r[c])).join(","))].join("\n") + "\n";
}

export function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

type Tone = "critical" | "warning" | "ok" | "unknown" | "info";

export interface SolveTile {
  label: string;
  value: string;
  unit?: string;
  tone?: Tone;
  hint?: string;
}

/** Solve-for outcome tiles: the solved variable, the target, the held input and the vessel window. */
export function solveTiles(res: SolveResult, label: string, fixed: { N_rpm: number; V_L: number }): SolveTile[] {
  const solveN = res.solve_for === "N_rpm";
  const unit = solveN ? "RPM" : "L";
  const g4 = (x: number) => formatG(x, 4);
  const [wlo, whi] = res.vessel_range;
  const achieved = res.solutions[0]?.achieved;
  const gives = achieved === null || achieved === undefined ? "" : ` · gives ${g4(achieved)}`;
  const headline: SolveTile =
    res.status === "solved"
      ? { label: solveN ? "Agitation speed N" : "Fill volume V", value: g4(res.best as number), unit, tone: "ok",
          hint: res.solutions.length > 1 ? `${res.solutions.length} solutions (see table)` : `Solution found${gives}` }
      : res.status === "outside_vessel_range"
        ? { label: solveN ? "Agitation speed N" : "Fill volume V", value: g4(res.solutions[0].value), unit,
            tone: "warning", hint: `Outside the vessel window${gives}` }
        : { label: solveN ? "Agitation speed N" : "Fill volume V", value: "No solution", tone: "critical",
            hint: res.achievable_span && res.achievable_span[0] !== null && res.achievable_span[1] !== null
              ? `Achievable ${label}: ${g4(res.achievable_span[0])}–${g4(res.achievable_span[1])}`
              : "Target not reachable" };
  return [
    headline,
    { label: `Target ${label}`, value: formatG(res.target) },
    solveN
      ? { label: "Held: fill volume V", value: formatG(fixed.V_L, 3), unit: "L" }
      : { label: "Held: agitation speed N", value: fixed.N_rpm.toFixed(0), unit: "RPM" },
    { label: "Vessel window", value: `${g4(wlo)}–${g4(whi)}`, unit },
  ];
}

/** Severity of a ``particle_suspension_criterion`` label. */
export function suspensionTone(state: string): Tone {
  if (/^poorly/i.test(state)) return "critical";
  if (/^(partially|just)/i.test(state)) return "warning";
  if (/^fully/i.test(state)) return "ok";
  return "info";
}

/** Severity of a ``heat_balance_assessment`` label. */
export function heatBalanceTone(balance: string): Tone {
  if (balance.includes("🔴")) return "critical";
  if (balance.includes("⚠️") || /^moderate/i.test(balance)) return "warning";
  if (/^(easily|comfortable|net cooling)/i.test(balance)) return "ok";
  return "info";
}

/** Severity of a mass-transfer screening label (``MT_SCREENING_LABELS``). */
export function transferTone(screening: string): Tone {
  if (/transfer-limited/i.test(screening)) return "critical";
  if (/comparable/i.test(screening)) return "warning";
  if (/exceeds/i.test(screening)) return "ok";
  return "unknown";
}

/** Headline parameters shown as large tiles; the rest are listed smaller. */
export const HYDRO_FEATURED = [
  "Reynolds number",
  "Power per volume",
  "Tip speed",
  "Blend time (95%)",
  "Micromixing time t_E",
  "Kolmogorov length η",
];
