import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { sym } from "./Sym";

describe("sym", () => {
  it("renders x_sub and x^n as sub/superscripts", () => {
    const { container } = render(<p>{sym("N/N_js = 0.47, t_{rxn} and 10^4")}</p>);
    expect([...container.querySelectorAll("sub")].map((e) => e.textContent)).toEqual(["js", "rxn"]);
    expect(container.querySelector("sup")?.textContent).toBe("4");
    expect(container.textContent).toBe("N/Njs = 0.47, trxn and 104");
  });
  it("returns plain text unchanged", () => {
    expect(sym("Heat balance")).toBe("Heat balance");
  });
});
