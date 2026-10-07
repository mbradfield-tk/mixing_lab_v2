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
  feedRate: string;
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
  reactionSource: "measured" | "classes";
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
  feedRate: "5",
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
  const required: [string, string][] = [
    ["Temperature", i.T], ["Pressure", i.P], ["Coolant temp", i.Tcool], ["Agitation speed", i.N],
    ["Working volume", i.V], ["D_tank", i.dTank], ["D_imp", i.dImp], ["Np", i.Np], ["Nq", i.Nq],
    ["ρ", i.rho], ["μ", i.mu], ["D_mol", i.dmol], ["k", i.k], ["C0", i.c0], ["t_rxn", i.trxn],
    ["ΔH_rxn", i.dH],
  ];
  if (i.solids)
    required.push(["ρ_p", i.rhoP], ["d50", i.d50], ["φ", i.phi], ["Solids loading", i.xWt],
      ["Zwietering S", i.szw], ["GMB z", i.gmbZ], ["C/D", i.cd]);
  if (i.fed) required.push(["Feed pipe ID", i.feedDiam]);
  if (i.gas && i.gasTransfer === "sparging") required.push(["v_s", i.vs]);
  const bad = required.find(([, v]) => !Number.isFinite(n(v)));
  if (bad) return { error: `Enter a number for ${bad[0]}.` };
  if (!i.reactor) return { error: "Select a vessel." };

  const sparged = i.gas && i.gasTransfer === "sparging";
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
      reaction: { order: i.order, k: n(i.k), C0_mol_L: n(i.c0), t_rxn_s: n(i.trxn), dH_kJ_mol: n(i.dH) },
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
      feed: i.fed ? { location: i.feedLocation as "bulk", d_pipe_mm: n(i.feedDiam) } : null,
      heat: { T_process_C: n(i.T), T_coolant_C: n(i.Tcool) },
      geometry: { D_tank_m: n(i.dTank), D_imp_m: n(i.dImp), Np: n(i.Np), Nq: n(i.Nq) },
    },
  };
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
