import { describe, expect, it } from "vitest";
import { clamp, snap } from "./Instrument";

describe("instrument range helpers", () => {
  it("rounds to the step grid and keeps values within the vessel range", () => {
    expect(snap(312, 50, 1000, 10)).toBe("310");
    expect(snap(1234, 50, 1000, 10)).toBe("1000");
    expect(snap(12, 50, 1000, 10)).toBe("50");
    expect(snap(0.0837, 0.03, 0.0836, 0.005)).toBe("0.0836");
    expect(snap(0.0412, 0.03, 0.1, 0.005)).toBe("0.04");
    expect(clamp(-3, 0, 5)).toBe(0);
  });
});
