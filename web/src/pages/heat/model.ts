import type { Schemas } from "../../api/client";
import { formatG } from "../../format";
import type { ReactionOrder } from "../assessment/model";

export type HeatBody = Schemas["HeatCoolRequest"];
export type SweepKey = NonNullable<Schemas["UaSurfaceRequest"]["x_parameter"]>;

export const MODES = [
  { code: "heat", label: "Heat / cool vessel" },
  { code: "reaction", label: "Reaction temperature profile" },
  { code: "sweep", label: "Parameter Sweep" },
] as const;
export type Mode = (typeof MODES)[number]["code"];

export const MODE_HINT: Record<Mode, string> = {
  heat: "Set the start / target / jacket temperatures, then Compute.",
  reaction: "Select a reaction and coolant temperature, then Compute.",
  sweep: "Choose two parameters and their ranges, then Compute.",
};

/** Form state. Number fields named after the API's sweep keys keep sweep defaults trivial. */
export interface Inputs extends Record<SweepKey, string> {
  reactor: string;
  fluid: string;
  htm: string;
  nusselt: string;
  np_in: string;
  a_ht: string;
  q_rxn: string;
  includeAgitator: boolean;
  wallMaterial: string;
  liningMaterial: string;
  m_dot_jacket: string;
  cp_jacket: string;
  t_start: string;
  t_jacket: string;
  t_target: string;
  timeUnit: "Seconds" | "Minutes" | "Hours";
  reactionSource: "measured" | "classes";
  reaction: string;
  order: ReactionOrder;
  rxnK: string;
  rxnC0: string;
  rxnDH: string;
  sweepX: SweepKey;
  sweepY: SweepKey;
  xMin: string;
  xMax: string;
  yMin: string;
  yMax: string;
  colorTheme: "Turbo" | "Viridis" | "Cool/Warm" | "X-ray";
  colorMode: "Automatic" | "Custom";
  uMin: string;
  uMax: string;
  uaMin: string;
  uaMax: string;
  projectName: string;
  step: string;
  unitOperation: string;
  processVersion: string;
}

export const INITIAL: Inputs = {
  reactor: "",
  fluid: "Water",
  htm: "",
  nusselt: "",
  n_rpm: "300",
  v_l: "1",
  d_imp: "0.05",
  d_tank: "0.1",
  rho: "997",
  mu: "0.00089",
  cp: "4182",
  k_fluid: "0.607",
  v_jacket: "1",
  d_hyd_jacket: "0.05",
  wall_k: "16",
  wall_thickness_mm: "5",
  lining_k: "0",
  lining_thickness_mm: "0",
  fouling: "0.0002",
  mu_wall: "0",
  np_in: "1.27",
  a_ht: "0.01",
  q_rxn: "0",
  includeAgitator: true,
  wallMaterial: "stainless steel",
  liningMaterial: "None",
  m_dot_jacket: "1",
  cp_jacket: "3500",
  t_start: "25",
  t_jacket: "-10",
  t_target: "5",
  timeUnit: "Minutes",
  reactionSource: "measured",
  reaction: "",
  order: "2",
  rxnK: "0.5",
  rxnC0: "1",
  rxnDH: "-50",
  sweepX: "n_rpm",
  sweepY: "v_l",
  xMin: "",
  xMax: "",
  yMin: "",
  yMax: "",
  colorTheme: "Turbo",
  colorMode: "Automatic",
  uMin: "0",
  uMax: "0",
  uaMin: "0",
  uaMax: "0",
  projectName: "",
  step: "",
  unitOperation: "",
  processVersion: "",
};

const n = (s: string): number => (s.trim() === "" ? Number.NaN : Number(s));

/** The request shared by every mode (geometry, materials, fluid, jacket), or the first bad number. */
export function buildBody(i: Inputs): { body: HeatBody } | { error: string } {
  const required: [string, string][] = [
    ["N", i.n_rpm], ["Liquid volume", i.v_l], ["D_tank", i.d_tank], ["D_imp", i.d_imp], ["Np", i.np_in],
    ["A_ht", i.a_ht], ["T_start", i.t_start], ["Jacket T", i.t_jacket], ["rho", i.rho], ["mu", i.mu],
    ["Cp", i.cp], ["k fluid", i.k_fluid], ["Jacket velocity", i.v_jacket],
    ["Jacket hydraulic diameter", i.d_hyd_jacket], ["Jacket mass flow", i.m_dot_jacket],
    ["Jacket Cp", i.cp_jacket], ["Wall k", i.wall_k], ["Wall thickness", i.wall_thickness_mm],
    ["Lining k", i.lining_k], ["Lining thickness", i.lining_thickness_mm], ["Fouling", i.fouling],
    ["mu at wall", i.mu_wall], ["Extra heat input", i.q_rxn], ["T_target", i.t_target],
  ];
  const bad = required.find(([, v]) => !Number.isFinite(n(v)));
  if (bad) return { error: `Enter a number for ${bad[0]}.` };
  if (!i.reactor) return { error: "Select a reactor." };
  return {
    body: {
      reactor: i.reactor,
      fluid: i.fluid,
      N_rpm: n(i.n_rpm),
      V_L: n(i.v_l),
      D_tank_m: n(i.d_tank),
      D_imp_m: n(i.d_imp),
      Np: n(i.np_in),
      A_ht_m2: n(i.a_ht),
      T_start_C: n(i.t_start),
      T_jacket_C: n(i.t_jacket),
      T_target_C: n(i.t_target),
      q_rxn_W: n(i.q_rxn),
      htm: i.htm || null,
      nusselt_correlation: i.nusselt || null,
      v_jacket_m_s: n(i.v_jacket),
      d_hyd_jacket_m: n(i.d_hyd_jacket),
      m_dot_jacket_kg_s: n(i.m_dot_jacket),
      wall_material: i.wallMaterial,
      wall_thickness_mm: n(i.wall_thickness_mm),
      lining_material: i.liningMaterial,
      fouling_m2K_W: n(i.fouling),
      include_agitator: i.includeAgitator,
      mu_wall_Pa_s: n(i.mu_wall),
      rho_kg_m3: n(i.rho),
      mu_Pa_s: n(i.mu),
      cp_J_kgK: n(i.cp),
      k_W_mK: n(i.k_fluid),
      cp_jacket_J_kgK: n(i.cp_jacket),
      wall_k_W_mK: n(i.wall_k),
      lining_k_W_mK: n(i.lining_k),
      lining_thickness_mm: n(i.lining_thickness_mm),
      time_unit: i.timeUnit,
      project: {
        project_name: i.projectName,
        step_number: i.step,
        unit_operation: i.unitOperation,
        process_version: i.processVersion,
      },
    },
  };
}

/** core.heat_transfer.adiabatic_rise. */
export function adiabaticRise(rho: number, cp: number, c0: number, dH: number): number {
  if (rho <= 0 || cp <= 0) return 0;
  return (-dH * 1000 * c0 * 1000) / (rho * cp);
}

const signed1 = (x: number) => `${x >= 0 ? "+" : ""}${x.toFixed(1)}`;
const thermalWord = (dH: number) => (dH < 0 ? "exothermic" : dH > 0 ? "endothermic" : "athermal");

/** pages/heat_transfer._adiabatic_text (Markdown). */
export function adiabaticText(rho: number, cp: number, c0: number, dH: number, tStart: number): string {
  const rise = adiabaticRise(rho, cp, c0, dH);
  return (
    `**Adiabatic (${thermalWord(dH)}):** ΔT ≈ ${signed1(rise)} °C → T_ad ≈ ${(tStart + rise).toFixed(1)} °C ` +
    `(no cooling, from T_start = ${tStart.toFixed(1)} °C).`
  );
}

/** pages/heat_transfer._build_resistance_breakdown agitator line (Markdown). */
export function agitatorText(pAgitatorW: number, qMaxW: number): string {
  if (!(pAgitatorW > 0)) return "**Agitator heat:** not included (toggle *Include agitator heat* to add it).";
  const q = Math.abs(qMaxW);
  const pct = q > 0 ? `${((pAgitatorW / q) * 100).toFixed(1)}%` : "∞";
  return `**Agitator heat:** ${pAgitatorW.toFixed(2)} W — about **${pct}** of the initial jacket duty (Q_max = ${q.toFixed(1)} W).`;
}

const minutes = (s: number | null | undefined) =>
  s === null || s === undefined || !Number.isFinite(s) ? null : `${(s / 60).toFixed(2)} min`;

export function heatStatus(U: number, tConstS: number | null, tAnalyticalS: number | null): string {
  return (
    `Computed successfully. U = ${U.toFixed(1)} W/(m2.K), simulated time (const jacket) = ` +
    `${minutes(tConstS) ?? "Infinity"}, analytical = ${minutes(tAnalyticalS) ?? "Infinity"}.`
  );
}

export function reactionStatus(dH: number, tPeak: number, tAd: number, tCompleteS: number | null): string {
  return (
    `Reaction simulated (${thermalWord(dH)}). Peak T = ${tPeak.toFixed(1)} C, adiabatic T = ${tAd.toFixed(1)} C, ` +
    `time to 99% conversion = ${minutes(tCompleteS) ?? "not reached"}.`
  );
}

/** Rounded core KPIs (pages/heat_transfer.on_compute kpi_df). */
export function kpiRows(c: Schemas["Coefficients"]): { Metric: string; Value: string }[] {
  const r = (x: number | null | undefined, d: number) =>
    x === null || x === undefined ? "—" : formatG(Math.round(x * 10 ** d) / 10 ** d, 12);
  return [
    { Metric: "h_i (W/m2.K)", Value: r(c.h_i_W_m2K, 2) },
    { Metric: "h_o (W/m2.K)", Value: r(c.h_o_W_m2K, 2) },
    { Metric: "U (W/m2.K)", Value: r(c.U_W_m2K, 2) },
    { Metric: "UA (W/K)", Value: r(c.UA_W_K, 2) },
    { Metric: "Nu", Value: r(c.Nu, 2) },
    { Metric: "Re", Value: r(c.Re, 0) },
    { Metric: "Pr", Value: r(c.Pr, 2) },
  ];
}

/** core.heat_transfer.sweep_range_defaults: vessel bounds for N / V, else ±50 % of the value. */
export function sweepRange(
  key: SweepKey,
  current: number,
  ranges: { N_rpm_range?: number[] | null; V_L_range?: number[] | null },
  zeroMax: Record<string, number>,
): [number, number] {
  const bounds = key === "n_rpm" ? ranges.N_rpm_range : key === "v_l" ? ranges.V_L_range : null;
  if (bounds && bounds.length === 2) return [bounds[0], bounds[1]];
  if (current > 0) return [current * 0.5, current * 1.5];
  return [0, zeroMax[key] ?? 1];
}

/** core.heat_transfer.surface_color_limits for a figure's z grid. */
export function colorLimits(z: (number | null)[][]): [number, number] {
  const flat = z.flat().filter((v): v is number => typeof v === "number" && Number.isFinite(v));
  if (!flat.length) return [0, 1];
  let lo = Math.min(...flat);
  let hi = Math.max(...flat);
  if (Math.abs(hi - lo) <= 1e-8 + 1e-5 * Math.abs(hi)) {
    const pad = Math.max(Math.abs(lo) * 0.01, 1e-6);
    lo -= pad;
    hi += pad;
  }
  return [lo, hi];
}
