import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { clearToken, getToken, setToken } from "../api/token";
import { DataTable, parseCell } from "./DataTable";

const COLUMNS = [
  { column: "particle_name", label: "Particle" },
  { column: "rho_p_kg_m3", label: "Density" },
  { column: "notes", label: "Notes" },
];
const ROWS = [
  { particle_name: "B", rho_p_kg_m3: 2500, notes: "" },
  { particle_name: "A", rho_p_kg_m3: 1300.123456789, notes: "needle" },
  { particle_name: "C", rho_p_kg_m3: null, notes: "x" },
];

const names = () => screen.getAllByRole("row").slice(1).map((r) => r.querySelector("td")?.textContent);

describe("parseCell", () => {
  it("sends numbers (or null) for numeric columns and raw text otherwise", () => {
    expect(parseCell(" 12.5 ", true)).toBe(12.5);
    expect(parseCell("", true)).toBeNull();
    expect(parseCell("abc", true)).toBe("abc"); // the server reports the error
    expect(parseCell(" keep spaces ", false)).toBe(" keep spaces ");
  });
});

describe("DataTable", () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it("formats numbers to 6 significant figures and blanks as a dash", () => {
    render(<DataTable rows={ROWS} columns={COLUMNS} nameKey="particle_name" />);
    expect(screen.getByText("1300.12")).toBeTruthy();
    expect(screen.getAllByText("—").length).toBe(2);
  });

  it("sorts by a column, numerically, with blanks last in both directions", () => {
    render(<DataTable rows={ROWS} columns={COLUMNS} nameKey="particle_name" />);
    fireEvent.click(screen.getByRole("button", { name: /Density/ }));
    expect(names()).toEqual(["A", "B", "C"]);
    fireEvent.click(screen.getByRole("button", { name: /Density/ }));
    expect(names()).toEqual(["B", "A", "C"]);
    fireEvent.click(screen.getByRole("button", { name: /Density/ }));
    expect(names()).toEqual(["B", "A", "C"]); // back to server order
  });

  it("pages long tables", () => {
    const rows = Array.from({ length: 30 }, (_, i) => ({ particle_name: `P${i}`, rho_p_kg_m3: i, notes: "" }));
    render(<DataTable rows={rows} columns={COLUMNS} nameKey="particle_name" pageSize={12} />);
    expect(screen.getAllByRole("row").length).toBe(13);
    expect(screen.getByText(/Page 1 of 3/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /Next/ }));
    expect(names()[0]).toBe("P12");
  });

  it("is read-only unless editable", () => {
    render(<DataTable rows={ROWS} columns={COLUMNS} nameKey="particle_name" />);
    fireEvent.click(screen.getByText("2500"));
    expect(screen.queryByRole("textbox")).toBeNull();
    expect(screen.queryByRole("button", { name: /Delete/ })).toBeNull();
  });

  it("commits an edit once (Enter then blur) with a typed value", async () => {
    const onEdit = vi.fn().mockResolvedValue({});
    render(<DataTable rows={ROWS} columns={COLUMNS} nameKey="particle_name" editable onEdit={onEdit} />);
    fireEvent.click(screen.getByText("2500"));
    const input = screen.getByRole("textbox", { name: "Density of B" });
    fireEvent.change(input, { target: { value: "2600" } });
    fireEvent.keyDown(input, { key: "Enter" });
    fireEvent.blur(input);
    expect(onEdit).toHaveBeenCalledTimes(1);
    expect(onEdit).toHaveBeenCalledWith(ROWS[0], "rho_p_kg_m3", 2600);
  });

  it("skips unchanged edits and cancels on Escape", () => {
    const onEdit = vi.fn().mockResolvedValue({});
    render(<DataTable rows={ROWS} columns={COLUMNS} nameKey="particle_name" editable onEdit={onEdit} />);
    fireEvent.click(screen.getByText("needle"));
    fireEvent.keyDown(screen.getByRole("textbox"), { key: "Enter" });
    fireEvent.click(screen.getByText("2500"));
    const input = screen.getByRole("textbox");
    fireEvent.change(input, { target: { value: "1" } });
    fireEvent.keyDown(input, { key: "Escape" });
    expect(onEdit).not.toHaveBeenCalled();
    expect(screen.getByText("2500")).toBeTruthy();
  });

  it("deletes only after confirmation", () => {
    const onDelete = vi.fn().mockResolvedValue(undefined);
    const confirm = vi.spyOn(window, "confirm").mockReturnValueOnce(false).mockReturnValueOnce(true);
    render(<DataTable rows={ROWS} columns={COLUMNS} nameKey="particle_name" editable onDelete={onDelete} />);
    fireEvent.click(screen.getByRole("button", { name: "Delete A" }));
    expect(onDelete).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Delete A" }));
    expect(confirm).toHaveBeenCalledTimes(2);
    expect(onDelete).toHaveBeenCalledWith(ROWS[1]);
  });
});

describe("admin token", () => {
  afterEach(() => {
    clearToken();
    vi.useRealTimers();
  });

  it("expires a minute before the server's TTL", () => {
    vi.useFakeTimers();
    setToken("t", 3600);
    expect(getToken()).toBe("t");
    vi.advanceTimersByTime(3540 * 1000);
    expect(getToken()).toBeNull();
  });
});
