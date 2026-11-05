import { describe, expect, it } from "vitest";
import { formatConverted, formatE, formatF, formatSig, tidyNumber } from "./format";

describe("formatSig / tidyNumber (result tiles)", () => {
  it("rounds to 3 significant figures with grouping", () => {
    expect([8822, 0.3748, 0.02666, 37.09, 3550, 0.9996, 1.36e-5, 0].map((x) => formatSig(x))).toEqual([
      "8,820", "0.375", "0.0267", "37.1", "3,550", "1", "1.36e-05", "0",
    ]);
  });
  it("only touches bare numbers", () => {
    expect(tidyNumber("8,822")).toBe("8,820");
    expect(tidyNumber("0.0003749")).toBe("0.000375");
    expect(tidyNumber("1.36e-05")).toBe("1.36e-05");
    expect(tidyNumber("0.5 → 0.7")).toBe("0.5 → 0.7");
    expect(tidyNumber("Run Test 2")).toBe("Run Test 2");
    expect(tidyNumber("—")).toBe("—");
    expect(tidyNumber(" ")).toBe(" ");
  });
});

// Expected strings produced by Python's pages/unit_converter._fmt.
const PYTHON: [number, string][] = [
  [0, "0"], [1, "1"], [-1, "-1"], [0.5, "0.5"], [123.456, "123.456"], [1234.5, "1,234.5"],
  [12345.678, "12,345.7"], [123456.7, "123,457"], [1234567.8, "1.23457e+06"],
  [99999999, "1e+08"], [1e8, "1e+08"], [1.5e9, "1.5e+09"], [-2.5e-7, "-2.5e-07"],
  [9.99e-5, "9.99e-05"], [1e-4, "0.0001"], [0.000123456, "0.000123456"],
  [3.14159265, "3.14159"], [100000, "100,000"], [999999.5, "1e+06"], [-40, "-40"],
  [101325, "101,325"], [6894.757293168, "6,894.76"], [1e-19, "1e-19"], [0.002, "0.002"],
  [0.1 + 0.2, "0.3"],
];

describe("formatConverted", () => {
  it.each(PYTHON)("formats %s like Python", (value, expected) => {
    expect(formatConverted(value)).toBe(expected);
  });

  it("shows a dash for values the API could not express", () => {
    expect(formatConverted(null)).toBe("—");
  });
});

describe("formatF / formatE", () => {
  it("match Python's .Nf and .Ne", () => {
    expect(formatF(997, 2)).toBe("997.00");
    expect(formatF(0.00089, 6)).toBe("0.000890");
    expect(formatE(2.3e-9, 3)).toBe("2.300e-09");
    expect(formatE(1.5e12, 2)).toBe("1.50e+12");
    expect(formatE(-4.2e-105, 1)).toBe("-4.2e-105");
  });

  it("show a dash for missing values", () => {
    expect(formatF(null, 2)).toBe("—");
    expect(formatE(undefined, 3)).toBe("—");
    expect(formatF(Number.NaN, 1)).toBe("—");
  });
});
