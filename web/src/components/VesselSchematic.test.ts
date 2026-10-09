import { describe, expect, it } from "vitest";
import { interp, niceStep } from "./VesselSchematic";

describe("schematic helpers", () => {
  it("interpolates within and clamps outside the curve", () => {
    expect(interp(5, [0, 10], [0, 100])).toBe(50);
    expect(interp(-1, [0, 10], [0, 100])).toBe(0);
    expect(interp(20, [0, 10], [0, 100])).toBe(100);
  });

  it("picks round graduation steps", () => {
    expect(niceStep(1.87)).toBe(0.25);
    expect(niceStep(870)).toBe(200);
    expect(niceStep(0)).toBe(1);
  });
});
