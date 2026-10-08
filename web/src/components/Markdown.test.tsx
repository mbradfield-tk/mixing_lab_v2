import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Markdown, TeX } from "./Markdown";

describe("Markdown", () => {
  it("renders tables and sub/superscripts from the equations data", () => {
    const { container } = render(
      <Markdown>{"| Symbol | Units |\n|---|---|\n| k<sub>L</sub>a | s<sup>-1</sup> |"}</Markdown>,
    );
    expect(container.querySelector("table")).not.toBeNull();
    expect(container.querySelector("sub")?.textContent).toBe("L");
    expect(container.querySelector("sup")?.textContent).toBe("-1");
  });

  it("strips scripts and event handlers", () => {
    const { container } = render(
      <Markdown>{'<img src="x" onerror="alert(1)"><script>alert(2)</script>ok'}</Markdown>,
    );
    expect(container.querySelector("script")).toBeNull();
    expect(container.innerHTML).not.toContain("onerror");
    expect(container.textContent).toContain("ok");
  });

  it("renders inline $LaTeX$ with KaTeX, including inside table cells", () => {
    const { container } = render(
      <Markdown>{"| Symbol | Units |\n|---|---|\n| $\\rho$ | kg/m³ |\n\nRe = $\\frac{\\rho N D^2}{\\mu}$"}</Markdown>,
    );
    expect(container.querySelectorAll(".katex").length).toBe(2);
    expect(container.querySelector("td .katex")).not.toBeNull();
    expect(container.querySelector("math")).not.toBeNull();
  });

  it("does not let raw HTML disguise itself as math", () => {
    const { container } = render(
      <Markdown>{'<span class="katex" onclick="alert(1)">x</span>'}</Markdown>,
    );
    expect(container.innerHTML).not.toContain("onclick");
  });

  it("emits the same KaTeX markup as TeX, so the bundled stylesheet sizes sub/superscripts", () => {
    const md = render(<Markdown>{"$D_T$"}</Markdown>).container.querySelector(".mtight")?.className;
    const tex = render(<TeX math="D_T" inline />).container.querySelector(".mtight")?.className;
    expect(md).toBeDefined();
    expect(md).toBe(tex);
  });
});

describe("TeX", () => {
  it("renders a display equation and never throws on bad input", () => {
    const { container } = render(
      <>
        <TeX math={"P = N_p \\, \\rho \\, N^3 \\, D^5"} />
        <TeX math={"\\notacommand{"} />
      </>,
    );
    expect(container.querySelectorAll(".katex-display").length).toBe(1);
    expect(container.querySelector(".katex-error")?.textContent).toContain("\\notacommand");
  });
});
