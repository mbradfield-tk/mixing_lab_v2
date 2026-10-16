import { act, fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it } from "vitest";
import {
  PersistentPage, caseFile, mergeKnown, parseCaseFile, usePageRef, usePageReset, usePageState,
} from "./pageState";

function Counter() {
  const [n, setN] = usePageState("n", 0);
  const visits = usePageRef("visits", 0);
  const reset = usePageReset();
  return (
    <div>
      <span data-testid="n">{n}</span>
      <span data-testid="visits">{++visits.current}</span>
      <button onClick={() => setN((x) => x + 1)}>inc</button>
      <button onClick={reset}>reset</button>
    </div>
  );
}

function Shell() {
  const [shown, setShown] = useState(true);
  return (
    <>
      <button onClick={() => setShown((s) => !s)}>toggle</button>
      {shown && (
        <PersistentPage page="test-page">
          <Counter />
        </PersistentPage>
      )}
    </>
  );
}

describe("page state", () => {
  it("survives unmounting (page navigation) and clears on reset", () => {
    render(<Shell />);
    fireEvent.click(screen.getByText("inc"));
    fireEvent.click(screen.getByText("inc"));
    act(() => fireEvent.click(screen.getByText("toggle")));
    act(() => fireEvent.click(screen.getByText("toggle")));
    expect(screen.getByTestId("n").textContent).toBe("2");
    fireEvent.click(screen.getByText("reset"));
    expect(screen.getByTestId("n").textContent).toBe("0");
  });
});

describe("case files", () => {
  const defaults = { reactor: "", N: "300", solids: false, phases: ["liquid"] as string[] };

  it("round-trips and rejects other pages or foreign files", () => {
    const text = JSON.stringify(caseFile("vessel-assessment", { ...defaults, reactor: "R1" }));
    const ok = parseCaseFile(text, "vessel-assessment");
    expect("file" in ok && ok.file.inputs.reactor).toBe("R1");
    expect(parseCaseFile(text, "heat-transfer")).toHaveProperty("error");
    expect(parseCaseFile("{}", "vessel-assessment")).toHaveProperty("error");
    expect(parseCaseFile("not json", "vessel-assessment")).toHaveProperty("error");
  });

  it("keeps only known fields with matching types", () => {
    const merged = mergeKnown(defaults, { reactor: "R2", N: 5, solids: true, phases: ["liquid", "solid"], extra: 1 });
    expect(merged).toEqual({ reactor: "R2", N: "300", solids: true, phases: ["liquid", "solid"] });
  });
});
