import { describe, expect, it } from "vitest";
import SmilesDrawer from "smiles-drawer";
import { solventStructureCaption } from "./Molecule";

function parses(smiles: string): boolean {
  let ok = false;
  SmilesDrawer.parse(smiles, () => (ok = true), () => (ok = false));
  return ok;
}

describe("Molecule", () => {
  it("smiles-drawer parses the library SMILES, including the ionic aqueous solutes", () => {
    for (const s of ["O", "Cc1ccccc1", "FC(F)(F)C(=O)OC(=O)C(F)(F)F", "[Na+].[OH-]", "[K+].[K+].[O-]C([O-])=O", "Cl"]) {
      expect(parses(s), s).toBe(true);
    }
    expect(parses("C(C")).toBe(false);
  });

  it("captions only the aqueous-solution entries", () => {
    expect(solventStructureCaption("6 M NaOH (aq)")).toMatch(/aqueous/);
    expect(solventStructureCaption("Toluene")).toBeUndefined();
  });
});
