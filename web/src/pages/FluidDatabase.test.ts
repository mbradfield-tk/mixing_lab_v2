import { describe, expect, it } from "vitest";
import { kinematicViscosity } from "./FluidDatabase";

describe("kinematicViscosity", () => {
  it("returns mu/rho in mm²/s (cSt) and NaN for missing properties", () => {
    expect(kinematicViscosity({ mu_Pa_s: 0.00089, rho_kg_m3: 997 })).toBeCloseTo(0.8927, 4);
    expect(kinematicViscosity({ mu_Pa_s: 0.000714, rho_kg_m3: 929.5 })).toBeCloseTo(0.7682, 4);
    expect(kinematicViscosity({ mu_Pa_s: null, rho_kg_m3: 997 })).toBeNaN();
    expect(kinematicViscosity({ mu_Pa_s: 0.001, rho_kg_m3: 0 })).toBeNaN();
  });
});
