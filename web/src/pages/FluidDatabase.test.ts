import { describe, expect, it } from "vitest";
import { blendRows, kinematicViscosity } from "./FluidDatabase";

describe("blendRows", () => {
  it("lists components then the blend, with ν in m²/s", () => {
    const fluid = { rho_kg_m3: 997, mu_Pa_s: 0.00089, surface_tension_N_m: 0.072, D_mol_m2_s: 2.3e-9, Cp_J_per_kgK: 4182, k_W_per_mK: 0.607 };
    const rows = blendRows({
      components: [{ name: "Water", vol_frac: 0.25, mass_frac: 0.3, ...fluid }],
      blend: fluid,
      pairs: [],
      dispersion: [],
      status: "ok",
    } as never);
    expect(rows.map((r) => r.Component)).toEqual(["Water", "Blend"]);
    expect(rows[0]["Vol %"]).toBe("25.0");
    expect(rows[1]["ν (m²/s)"]).toBe("8.927e-07");
  });
});

describe("kinematicViscosity", () => {
  it("returns mu/rho in mm²/s (cSt) and NaN for missing properties", () => {
    expect(kinematicViscosity({ mu_Pa_s: 0.00089, rho_kg_m3: 997 })).toBeCloseTo(0.8927, 4);
    expect(kinematicViscosity({ mu_Pa_s: 0.000714, rho_kg_m3: 929.5 })).toBeCloseTo(0.7682, 4);
    expect(kinematicViscosity({ mu_Pa_s: null, rho_kg_m3: 997 })).toBeNaN();
    expect(kinematicViscosity({ mu_Pa_s: 0.001, rho_kg_m3: 0 })).toBeNaN();
  });
});
