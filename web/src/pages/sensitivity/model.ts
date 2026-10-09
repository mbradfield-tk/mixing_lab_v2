import type { Schemas } from "../../api/client";

export type ProtocolBody = Schemas["ProtocolRequest"];
export type BourneImport = Schemas["BourneImport"];
export type ReactionDefaults = Schemas["SensitivityReactionDefaults"];
type BourneRow = Schemas["BourneTestRow"];

export interface Project {
  projectName: string;
  step: string;
  unitOperation: string;
  processVersion: string;
}

export interface Inputs {
  bourneStatus: Schemas["BourneStatus"];
  bourneMech: Schemas["Mechanism"] | "";
  bourneTests: (1 | 2 | 3)[];
  bourneFindings: BourneRow[];
  bourneMeta: Record<string, string>;
  bourneMetaCaption: string;
  kineticsAvail: Schemas["Kinetics"];
  reaction: string;
  order: string;
  k: string;
  c0: string;
  tRxn: string;
  T: string;
  dH: string;
  reactionType: string;
  solvent: string;
  semiBatch: boolean;
  phases: Schemas["Phase"][];
  competing: Schemas["Competing"] | "";
  dhAction: Schemas["DhAction"] | "";
  dhRef: string;
  dhOverride: string;
  dhMeasured: "measured" | "estimated";
  rhoCp: string;
  c0Heat: string;
  daOn: boolean;
  daReactor: string;
  daRpm: string;
  daVl: string;
}

export const BLANK_PROJECT: Project = { projectName: "", step: "", unitOperation: "", processVersion: "" };

export const INITIAL: Inputs = {
  bourneStatus: "skip",
  bourneMech: "",
  bourneTests: [1],
  bourneFindings: [],
  bourneMeta: {},
  bourneMetaCaption: "",
  kineticsAvail: "available",
  reaction: "",
  order: "1",
  k: "0",
  c0: "0",
  tRxn: "0",
  T: "25",
  dH: "0",
  reactionType: "",
  solvent: "",
  semiBatch: false,
  phases: ["liquid"],
  competing: "",
  dhAction: "",
  dhRef: "",
  dhOverride: "0",
  dhMeasured: "estimated",
  rhoCp: "1800",
  c0Heat: "1",
  daOn: false,
  daReactor: "",
  daRpm: "300",
  daVl: "1",
};

export const SUMMARY_PRE_START = "*Run the assessment to see the verdict and next steps.*";

/** ``core.records.sf``: blank / non-numeric text counts as 0. */
export const sf = (v: string, fallback = 0): number => {
  const x = v.trim() === "" ? Number.NaN : Number(v);
  return Number.isFinite(x) ? x : fallback;
};
const round = (x: number, digits: number) => Math.round(x * 10 ** digits) / 10 ** digits;

/** The reaction list for a kinetics answer: proxy classes for "approximate", else measured. */
export function reactionList(kineticsAvail: string, measured: string[], classes: string[]): string[] {
  const list = kineticsAvail === "approximate" ? classes : measured;
  return list.length ? list : ["(none available)"];
}

/** Input patch after loading a reaction's database kinetics (Taipy ``on_ms_reaction_change``). */
export function reactionPatch(name: string, d: ReactionDefaults): Partial<Inputs> {
  return {
    reaction: name,
    order: d.order,
    k: String(d.k),
    c0: String(d.C0_mol_L),
    tRxn: String(d.t_rxn_s),
    T: String(d.T_C),
    dH: String(d.dH_kJ_mol),
    reactionType: d.reaction_type,
    solvent: d.solvent,
    c0Heat: String(d.C0_mol_L > 0 ? round(d.C0_mol_L, 4) : 1),
    ...(d.rho_cp_kJ_m3K != null ? { rhoCp: String(d.rho_cp_kJ_m3K) } : {}),
  };
}

/** Input patch after a Bourne results import, plus project fields to prefill when blank. */
export function importPatch(
  imp: BourneImport,
  project: Project,
  unitOperations: string[],
): { inputs: Partial<Inputs>; project: Project } {
  const f = imp.fields;
  const fill = (cur: string, key: string) => (cur.trim() || !f[key] ? cur : f[key]);
  const unitOp = f.unit_operation ?? "";
  return {
    inputs: {
      bourneStatus: imp.status,
      bourneMech: imp.mechanism ?? "",
      bourneTests: imp.tests_done.length ? imp.tests_done : [1],
      bourneFindings: imp.findings,
      bourneMeta: imp.meta,
      bourneMetaCaption: imp.meta_caption,
    },
    project: {
      projectName: fill(project.projectName, "project_name"),
      step: fill(project.step, "step_number"),
      processVersion: fill(project.processVersion, "process_version"),
      unitOperation: unitOperations.includes(unitOp) && project.unitOperation === "" ? unitOp : project.unitOperation,
    },
  };
}

/** Request body for ``/sensitivity/page`` (and the PDF), or the first input problem. */
export function buildProtocol(i: Inputs, dhReferences: Record<string, number>): { body: ProtocolBody } | { error: string } {
  const k = sf(i.k);
  const c0 = sf(i.c0);
  const tRxn = sf(i.tRxn);
  const c0Heat = sf(i.c0Heat);
  const rhoCp = sf(i.rhoCp);
  if (k < 0 || c0 < 0 || tRxn < 0) return { error: "k, C₀ and the reaction time must not be negative." };
  if (c0Heat < 0 || rhoCp < 0) return { error: "ρ·Cp and the limiting-reagent C₀ must not be negative." };
  const rpm = sf(i.daRpm);
  const vl = sf(i.daVl);
  return {
    body: {
      reaction: { order: i.order as ProtocolBody["reaction"]["order"], k, C0_mol_L: c0, t_rxn_s: tRxn, dH_kJ_mol: sf(i.dH) },
      reaction_type: i.reactionType,
      kinetics: i.kineticsAvail,
      bourne: i.bourneStatus,
      bourne_mechanism: i.bourneMech || null,
      bourne_tests_done: [...i.bourneTests].sort(),
      bourne_results: i.bourneFindings,
      semi_batch: i.semiBatch,
      phases: i.phases,
      competing: i.competing || null,
      dh_override_kJ_mol: sf(i.dhOverride),
      dh_override_measured: i.dhMeasured === "measured",
      dh_action: i.dhAction || null,
      dh_reference_kJ_mol: i.dhAction === "estimate" ? (dhReferences[i.dhRef] ?? 0) : 0,
      c0_heat_mol_L: c0Heat,
      rho_cp_kJ_m3K: rhoCp,
      screening_vessel:
        i.daOn && i.daReactor && rpm > 0 && vl > 0
          ? { reactor: i.daReactor, N_rpm: rpm, V_L: vl, solvent: i.solvent, T_C: sf(i.T, 25) }
          : null,
    },
  };
}

/** Display rows of the Bourne findings (page column names). */
export const findingRows = (rows: BourneRow[]) =>
  rows.map((r) => ({ Test: r.test, Finding: r.finding, "Sensitive KPI(s)": r.sensitive_kpis }));

const SEVERITY: Record<string, number> = { critical: 0, warning: 1, caution: 2, unknown: 3, ok: 4 };

/** Findings ordered most severe first (stable within a severity). */
export const bySeverity = <T extends { kind: string }>(items: T[]): T[] =>
  [...items].sort((a, b) => (SEVERITY[a.kind] ?? 9) - (SEVERITY[b.kind] ?? 9));

/** Count of findings per severity group for the summary tiles. */
export function severityCounts(items: { kind: string }[]): { critical: number; watch: number; ok: number; unknown: number } {
  const n = (kinds: string[]) => items.filter((f) => kinds.includes(f.kind)).length;
  return { critical: n(["critical"]), watch: n(["warning", "caution"]), ok: n(["ok"]), unknown: n(["unknown"]) };
}

/** Verdict Markdown -> headline (before the first " - ") and the remaining explanation. */
export function splitHeadline(verdict: string): [string, string] {
  const text = verdict.replace(/^\s*(🔴|🟡|🟢|⚪|⚠️|✅)\s*/u, "");
  const m = /^(.+?)\s+[-—]\s+(.*)$/s.exec(text);
  return m ? [m[1].replace(/\*\*/g, ""), m[2].charAt(0).toUpperCase() + m[2].slice(1)] : [text.replace(/\*\*/g, ""), ""];
}

// The server's pending note names the Taipy step numbers, so the page uses its own wording.
export const SUMMARY_PENDING = "*Complete Steps 2, 3, 5 and 6 to see the verdict.*";

type Tone = "critical" | "warning" | "caution" | "ok" | "unknown" | "info";

export const DA_ZONES: { to: number; label: string; tone: Tone }[] = [
  { to: 0.1, label: "Mixing-insensitive", tone: "ok" },
  { to: 1, label: "Transitional", tone: "warning" },
  { to: 100, label: "Mixing-limited", tone: "critical" },
];

/** Reaction-time bands of the vessel-free screen (``assess_protocol`` Step 5). */
export const SPEED_ZONES: { to: number; label: string; tone: Tone }[] = [
  { to: 0.1, label: "Very fast", tone: "critical" },
  { to: 1, label: "Fast", tone: "warning" },
  { to: 10, label: "Moderate", tone: "caution" },
  { to: 1000, label: "Slow", tone: "ok" },
];

/** ``rules.da_band`` colour of a Damköhler number. */
export const daTone = (da: number): Tone => (da >= 1 ? "critical" : da >= 0.1 ? "warning" : "ok");

const g3 = (x: number) => String(Number(x.toPrecision(3)));

/** Timescale and Damköhler tiles for the mixing-time step. */
export function timescaleTiles(
  tRxn: number | null | undefined,
  da: Schemas["ScreeningDamkohler"] | null | undefined,
): { label: string; value: string; unit?: string; tone?: Tone; hint?: string }[] {
  if (!tRxn) return [];
  const tiles: { label: string; value: string; unit?: string; tone?: Tone; hint?: string }[] = [
    { label: "Reaction time t_rxn", value: g3(tRxn), unit: "s" },
  ];
  if (!da) return tiles;
  const num = (x: number | null | undefined) => (x === null || x === undefined ? Number.NaN : x);
  const [blend, tE, dMacro, dMicro] = [num(da.t_blend_s), num(da.t_E_s), num(da.Da_macro), num(da.Da_micro)];
  if (Number.isFinite(blend)) tiles.push({ label: "Blend time θ95", value: g3(blend), unit: "s", hint: "macromixing" });
  if (Number.isFinite(tE)) tiles.push({ label: "Micromixing time t_E", value: g3(tE), unit: "s", hint: "micromixing" });
  if (Number.isFinite(dMacro)) tiles.push({ label: "Da macro", value: g3(dMacro), tone: daTone(dMacro), hint: "θ95 / t_rxn" });
  if (Number.isFinite(dMicro)) tiles.push({ label: "Da micro", value: g3(dMicro), tone: daTone(dMicro), hint: "t_E / t_rxn" });
  return tiles;
}

/** One-line vessel / operating-point context of the Damköhler screen. */
export function daContext(da: Schemas["ScreeningDamkohler"]): string {
  const parts = [da.reactor, `${Math.round(da.N_rpm)} RPM`, `${g3(da.V_L)} L`, da.fluid];
  if (da.Re !== null && da.Re !== undefined) parts.push(`Re ${Math.round(da.Re).toLocaleString("en-US")}`);
  if (da.P_V_W_L !== null && da.P_V_W_L !== undefined) parts.push(`P/V ${g3(da.P_V_W_L)} W/L`);
  return parts.join(" · ");
}
