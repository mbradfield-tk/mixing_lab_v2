import { describe, expect, it } from "vitest";
import {
  BLANK_PROJECT, INITIAL, buildProtocol, bySeverity, daContext, daTone, findingRows, importPatch, reactionList,
  reactionPatch, severityCounts, splitHeadline, timescaleTiles, type BourneImport,
} from "./model";

const imp: BourneImport = {
  status: "confirmed",
  mechanism: null,
  tests_done: [1, 2],
  findings: [{ test: "Test 1 - impeller speed", finding: "Sensitive", sensitive_kpis: "Yield" }],
  meta: { reactor: "R1" },
  meta_caption: "Imported Bourne results - **Project:** P",
  fields: { project_name: "P", step_number: "3", unit_operation: "Reaction", process_version: "" },
};

describe("sensitivity model", () => {
  it("picks proxy classes for approximate kinetics", () => {
    expect(reactionList("approximate", ["m"], ["c"])).toEqual(["c"]);
    expect(reactionList("available", ["m"], ["c"])).toEqual(["m"]);
    expect(reactionList("available", [], ["c"])).toEqual(["(none available)"]);
  });

  it("auto-fills kinetics, heat C0 and rho*Cp from the reaction", () => {
    const d = { order: "2", k: 0.5, C0_mol_L: 0.123456, t_rxn_s: 0, T_C: 30, dH_kJ_mol: -80, reaction_type: "Nitration", solvent: "Water", rho_cp_kJ_m3K: null } as const;
    expect(reactionPatch("R", d)).toMatchObject({ order: "2", c0Heat: "0.1235", reactionType: "Nitration" });
    expect(reactionPatch("R", d)).not.toHaveProperty("rhoCp");
    expect(reactionPatch("R", { ...d, C0_mol_L: 0, rho_cp_kJ_m3K: 4170.2 })).toMatchObject({ c0Heat: "1", rhoCp: "4170.2" });
  });

  it("prefills only blank project fields on import", () => {
    const p = importPatch(imp, { ...BLANK_PROJECT, step: "9" }, ["Reaction"]);
    expect(p.project).toEqual({ projectName: "P", step: "9", processVersion: "", unitOperation: "Reaction" });
    expect(p.inputs).toMatchObject({ bourneStatus: "confirmed", bourneMech: "", bourneTests: [1, 2] });
    expect(importPatch({ ...imp, tests_done: [] }, BLANK_PROJECT, []).inputs.bourneTests).toEqual([1]);
    expect(findingRows(imp.findings)).toEqual([{ Test: "Test 1 - impeller speed", Finding: "Sensitive", "Sensitive KPI(s)": "Yield" }]);
  });

  it("builds the protocol request like the Taipy page", () => {
    const i = { ...INITIAL, k: "", dhAction: "estimate" as const, dhRef: "Ref", daOn: true, daReactor: "R1", solvent: "Water", T: "40" };
    const b = buildProtocol(i, { Ref: -120 });
    expect("body" in b && b.body).toMatchObject({
      reaction: { k: 0 },
      dh_reference_kJ_mol: -120,
      competing: null,
      screening_vessel: { reactor: "R1", N_rpm: 300, V_L: 1, solvent: "Water", T_C: 40 },
    });
    const off = buildProtocol({ ...i, dhAction: "calorimetry", daRpm: "0" }, { Ref: -120 });
    expect("body" in off && [off.body.dh_reference_kJ_mol, off.body.screening_vessel]).toEqual([0, null]);
    expect(buildProtocol({ ...INITIAL, c0: "-1" }, {})).toEqual({ error: "k, C₀ and the reaction time must not be negative." });
  });

  it("orders and counts findings by severity for the dashboard", () => {
    const f = [{ kind: "ok", a: 1 }, { kind: "critical", a: 2 }, { kind: "unknown", a: 3 }, { kind: "caution", a: 4 }, { kind: "critical", a: 5 }];
    expect(bySeverity(f).map((x) => x.a)).toEqual([2, 5, 4, 3, 1]);
    expect(severityCounts(f)).toEqual({ critical: 2, watch: 1, ok: 1, unknown: 1 });
  });

  it("splits the verdict into a headline and explanation", () => {
    expect(splitHeadline("🔴 Mixing sensitivity confirmed - the reaction may be **micro** limited.")).toEqual([
      "Mixing sensitivity confirmed",
      "The reaction may be **micro** limited.",
    ]);
    expect(splitHeadline("🟢 **Not mixing-sensitive**")).toEqual(["Not mixing-sensitive", ""]);
  });

  it("builds the timescale tiles, colouring Da by band", () => {
    expect(timescaleTiles(null, null)).toEqual([]);
    expect(timescaleTiles(69, null).map((t) => [t.label, t.value])).toEqual([["Reaction time t_rxn", "69"]]);
    const da = {
      reactor: "TMA EasyMax-102", N_rpm: 525, V_L: 0.055, fluid: "Methanol", t_blend_s: 1.2153, t_E_s: 0.02421,
      Re: 12168.4, P_V_W_L: 0.2581, Da_macro: 0.0176, Da_micro: 1.5,
    };
    expect(timescaleTiles(69, da).map((t) => [t.label, t.value, t.tone])).toEqual([
      ["Reaction time t_rxn", "69", undefined],
      ["Blend time θ95", "1.22", undefined],
      ["Micromixing time t_E", "0.0242", undefined],
      ["Da macro", "0.0176", "ok"],
      ["Da micro", "1.5", "critical"],
    ]);
    expect([daTone(0.099), daTone(0.1), daTone(1)]).toEqual(["ok", "warning", "critical"]);
    expect(daContext(da)).toBe("TMA EasyMax-102 · 525 RPM · 0.055 L · Methanol · Re 12,168 · P/V 0.258 W/L");
  });
});
