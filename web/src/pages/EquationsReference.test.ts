import { describe, expect, it } from "vitest";
import { filterSections } from "./EquationsReference";

const entry = (id: string, title: string, extra: Partial<{ equation: string; body: string }> = {}) => ({
  id,
  title,
  used_in: ["Vessel Assessment"],
  equation: extra.equation ?? null,
  body: extra.body ?? "",
  sources: ["Zwietering (1958)"],
});

const sections = [
  { id: "power", title: "Power & flow", intro: "", entries: [entry("re", "Reynolds number", { equation: "Re = \\frac{\\rho N D^2}{\\mu}" })] },
  {
    id: "solids",
    title: "Solid suspension",
    intro: "",
    entries: [entry("zw", "Just-suspended speed"), entry("vt", "Settling velocity", { body: "Schiller–Naumann drag" })],
  },
];

describe("filterSections", () => {
  it("returns everything for a blank query", () => {
    expect(filterSections(sections, "  ")).toBe(sections);
  });

  it("matches titles, LaTeX, body text and sources, case-insensitively", () => {
    expect(filterSections(sections, "\\mu").map((s) => s.id)).toEqual(["power"]);
    expect(filterSections(sections, "schiller")[0].entries.map((e) => e.id)).toEqual(["vt"]);
    expect(filterSections(sections, "ZWIETERING").flatMap((s) => s.entries).length).toBe(3);
  });

  it("keeps a whole section when its title matches and drops empty sections", () => {
    expect(filterSections(sections, "suspension")[0].entries).toHaveLength(2);
    expect(filterSections(sections, "nothing here")).toEqual([]);
  });
});
