import type { Schemas } from "../../api/client";
import { formatG } from "../../format";
import { autoTrxn, type ReactionOrder } from "../assessment/model";

export type ComparisonRequest = Schemas["ComparisonRequest"];
export type PageRequest = Schemas["ComparisonPageRequest"];

export const DEFAULT_VESSELS = ["TMA EasyMax-102", "TMA 15 L Buchi", "Cambrex R-101", "Cambrex R-B01"];

/** This page's own wording for the coalescence options (pages/vessel_comparison._COAL_LABELS). */
export const COALESCENCE = [
  { code: "coalescing", label: "Coalescing (pure liquid)" },
  { code: "non_coalescing", label: "Non-coalescing (electrolyte)" },
];

export interface Inputs {
  reactors: string[];
  corr: string;
  fluid: string;
  T: string;
  P: string;
  reactionSource: "measured" | "classes";
  reaction: string;
  Tcool: string;
  order: ReactionOrder;
  k: string;
  c0: string;
  trxn: string;
  dH: string;
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
  fed: boolean;
  feedLocation: string;
  feedPipe: Record<string, string>;
  feedBasis: string;
  feedVolume: string;
  feedTime: string;
  scaling: boolean;
  basis: string;
  scaleParam: string;
  solveFor: "N_rpm" | "V_L";
  basisRpm: string;
  basisVol: string;
  targets: Record<string, string>;
}

export const INITIAL: Inputs = {
  reactors: [],
  corr: "Literature",
  fluid: "Water",
  T: "25",
  P: "1",
  reactionSource: "measured",
  reaction: "",
  Tcool: "15",
  order: "1",
  k: "0",
  c0: "0",
  trxn: "0",
  dH: "0",
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
  gasTransfer: "sparging",
  vs: "0.005",
  coalescing: "coalescing",
  fed: false,
  feedLocation: "bulk",
  feedPipe: {},
  feedBasis: "",
  feedVolume: "100",
  feedTime: "1",
  scaling: false,
  basis: "",
  scaleParam: "P_V_W_L",
  solveFor: "N_rpm",
  basisRpm: "100",
  basisVol: "1",
  targets: {},
};

const n = (s: string): number => (s.trim() === "" ? Number.NaN : Number(s));
const n0 = (s: string): number => (Number.isFinite(n(s)) ? n(s) : 0);

/** Effective t_rxn with the comparison page's 1 s fallback (kinetics.effective_t_rxn(fallback=1)). */
export const comparisonTrxn = (order: string, k: number, c0: number, tSpec: number) =>
  autoTrxn(order, k, c0, tSpec) || 1;

/** pages/vessel_comparison._kin_caption (Markdown). */
export function kineticsCaption(order: string, k: number, c0: number, tSpec: number, dH: number): string {
  const t = comparisonTrxn(order, k, c0, tSpec);
  const basis = tSpec > 0 ? "specified" : k > 0 ? "derived from k" : "fallback";
  let txt = `Effective reaction time **t_rxn = ${formatG(t, 4)} s** (${basis})  •  ΔH = ${dH.toFixed(1)} kJ/mol`;
  if (dH === 0) txt += " (heat balance disabled)";
  return txt;
}

/** The comparison request (shared by tables, chart, PDF and save) and the full page request. */
export function buildRequests(i: Inputs): { comparison: ComparisonRequest; page: PageRequest } | { error: string } {
  if (!i.reactors.length) return { error: "Select at least one vessel to compare." };
  const required: [string, string][] = [["Temperature", i.T], ["Pressure", i.P], ["Coolant temperature", i.Tcool]];
  const bad = required.find(([, v]) => !Number.isFinite(n(v)));
  if (bad) return { error: `Enter a number for ${bad[0]}.` };

  const d50 = n0(i.d50);
  const comparison: ComparisonRequest = {
    reactors: i.reactors,
    reaction_name: i.reaction,
    scale_param: "",
    scale_basis_reactor: "",
    corr_source: i.corr as ComparisonRequest["corr_source"],
    T_coolant_C: n(i.Tcool),
    fluid: { name: i.fluid, T_C: n(i.T), P_atm: n(i.P) },
    reaction: { order: i.order, k: n0(i.k), C0_mol_L: n0(i.c0), t_rxn_s: n0(i.trxn), dH_kJ_mol: n0(i.dH) },
    gas: {
      present: i.gas,
      v_s_m_s: i.gas && i.gasTransfer === "sparging" ? n0(i.vs) : 0,
      coalescing: i.coalescing === "coalescing",
    },
    solids:
      i.solids && d50 > 0
        ? {
            rho_p_kg_m3: n0(i.rhoP),
            d50_um: d50,
            sphericity: n0(i.phi),
            loading_g_per_100g: n0(i.xWt),
            zwietering_S: n0(i.szw) || 5.5,
            gmb_z: n0(i.gmbZ) || 3,
            clearance_ratio: n0(i.cd) || 0.33,
          }
        : null,
    feed: i.fed
      ? {
          location: i.feedLocation as "bulk",
          pipe_id_mm: Object.fromEntries(i.reactors.map((r) => [r, n0(i.feedPipe[r] ?? "0")])),
        }
      : null,
  };
  const page: PageRequest = {
    comparison,
    scale_up:
      i.scaling && i.reactors.length >= 2
        ? {
            basis_reactor: i.basis,
            parameter: i.scaleParam,
            basis_N_rpm: n0(i.basisRpm),
            basis_V_L: n0(i.basisVol),
            solve_for: i.solveFor,
            fixed: Object.fromEntries(
              i.reactors.filter((r) => r !== i.basis && i.targets[r] !== undefined).map((r) => [r, n0(i.targets[r])]),
            ),
          }
        : null,
    feed_schedule: i.fed
      ? { basis_reactor: i.feedBasis || i.reactors[0], volume_mL: n0(i.feedVolume), time_h: n0(i.feedTime) || 1 }
      : null,
  };
  return { comparison, page };
}
