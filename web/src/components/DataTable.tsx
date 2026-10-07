import { useMemo, useRef, useState, type KeyboardEvent } from "react";
import type { Column, Row } from "../api/tables";
import { formatG } from "../format";

type SortDir = "asc" | "desc";

export interface DataTableProps {
  rows: Row[];
  columns: Column[];
  /** Column holding the row's unique name (used as the React key and in prompts). */
  nameKey: string;
  editable?: boolean;
  onEdit?: (row: Row, column: string, value: unknown) => Promise<unknown>;
  onDelete?: (row: Row) => Promise<unknown>;
  pageSize?: number;
  /** Significant figures for numbers (Python `.{digits}g`). */
  digits?: number;
}

const isBlank = (v: unknown) => v === null || v === undefined || v === "";

export function display(v: unknown, digits = 6): string {
  if (isBlank(v)) return "—";
  return typeof v === "number" ? formatG(v, digits) : String(v);
}

/** Text typed into a cell -> the value sent to the API (numeric columns send numbers / null). */
export function parseCell(text: string, numeric: boolean): unknown {
  const t = text.trim();
  if (!numeric) return text;
  if (t === "") return null;
  const n = Number(t);
  return Number.isFinite(n) ? n : text; // let the server reject non-numbers with a message
}

function compare(a: unknown, b: unknown): number {
  if (isBlank(a)) return isBlank(b) ? 0 : 1;
  if (isBlank(b)) return -1;
  if (typeof a === "number" && typeof b === "number") return a - b;
  return String(a).localeCompare(String(b), undefined, { numeric: true, sensitivity: "base" });
}

/** Sortable, paged table; when `editable`, click a cell to edit it (Enter saves, Esc cancels). */
export function DataTable({
  rows,
  columns,
  nameKey,
  editable = false,
  onEdit,
  onDelete,
  pageSize = 12,
  digits = 6,
}: DataTableProps) {
  const [sort, setSort] = useState<{ key: string; dir: SortDir } | null>(null);
  const [page, setPage] = useState(0);
  const [editing, setEditingState] = useState<{ name: string; column: string; text: string } | null>(null);
  // Mirrors `editing` so Enter followed by the input's blur commits only once.
  const editRef = useRef(editing);
  const setEditing = (value: typeof editing) => {
    editRef.current = value;
    setEditingState(value);
  };

  const numeric = useMemo(() => {
    const out = new Set<string>();
    for (const { column } of columns) {
      const values = rows.map((r) => r[column]).filter((v) => !isBlank(v));
      if (values.length && values.every((v) => typeof v === "number")) out.add(column);
    }
    return out;
  }, [rows, columns]);

  const sorted = useMemo(() => {
    if (!sort) return rows;
    const factor = sort.dir === "asc" ? 1 : -1;
    return [...rows].sort((a, b) => {
      const blankA = isBlank(a[sort.key]);
      const blankB = isBlank(b[sort.key]);
      if (blankA || blankB) return compare(a[sort.key], b[sort.key]); // blanks always last
      return factor * compare(a[sort.key], b[sort.key]);
    });
  }, [rows, sort]);

  const pages = Math.max(1, Math.ceil(sorted.length / pageSize));
  const current = Math.min(page, pages - 1);
  const visible = sorted.slice(current * pageSize, (current + 1) * pageSize);

  function toggleSort(key: string) {
    setSort((s) =>
      s?.key !== key ? { key, dir: "asc" } : s.dir === "asc" ? { key, dir: "desc" } : null,
    );
  }

  async function commit() {
    const edit = editRef.current;
    if (!edit) return;
    const { name, column, text } = edit;
    setEditing(null);
    const row = rows.find((r) => String(r[nameKey]) === name);
    if (!row || !onEdit) return;
    const value = parseCell(text, numeric.has(column));
    const unchanged = isBlank(row[column]) ? isBlank(value) : row[column] === value;
    if (!unchanged) await onEdit(row, column, value).catch(() => undefined);
  }

  function onKey(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Enter") void commit();
    if (e.key === "Escape") setEditing(null);
  }

  return (
    <div className="data-table">
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              {columns.map(({ column, label }) => (
                <th key={column} aria-sort={sort?.key === column ? (sort.dir === "asc" ? "ascending" : "descending") : "none"}>
                  <button type="button" className="th-sort" onClick={() => toggleSort(column)}>
                    {label}
                    <span className="sort-mark">
                      {sort?.key === column ? (sort.dir === "asc" ? " ▲" : " ▼") : ""}
                    </span>
                  </button>
                </th>
              ))}
              {editable && onDelete && <th aria-label="Actions" />}
            </tr>
          </thead>
          <tbody>
            {visible.map((row, i) => {
              const name = String(row[nameKey]);
              return (
                <tr key={`${current * pageSize + i}:${name}`}>
                  {columns.map(({ column, label }) => {
                    const isEditing = editing?.name === name && editing.column === column;
                    const text = display(row[column], digits);
                    return (
                      <td
                        key={column}
                        className={`${numeric.has(column) ? "num" : ""} ${editable ? "editable" : ""}`}
                        title={editable ? `${text} — click to edit` : text}
                        onClick={
                          editable && !isEditing
                            ? () =>
                                setEditing({
                                  name,
                                  column,
                                  text: isBlank(row[column]) ? "" : String(row[column]),
                                })
                            : undefined
                        }
                      >
                        {isEditing ? (
                          <input
                            autoFocus
                            aria-label={`${label} of ${name}`}
                            value={editing.text}
                            onChange={(e) => setEditing({ ...editing, text: e.target.value })}
                            onKeyDown={onKey}
                            onBlur={() => void commit()}
                          />
                        ) : (
                          text
                        )}
                      </td>
                    );
                  })}
                  {editable && onDelete && (
                    <td>
                      <button
                        type="button"
                        className="icon-btn"
                        title={`Delete ${name}`}
                        aria-label={`Delete ${name}`}
                        onClick={() => {
                          if (window.confirm(`Delete '${name}'? This cannot be undone.`))
                            void onDelete(row).catch(() => undefined);
                        }}
                      >
                        🗑
                      </button>
                    </td>
                  )}
                </tr>
              );
            })}
            {!visible.length && (
              <tr>
                <td colSpan={columns.length + 1} className="empty">
                  No matching rows.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      {pages > 1 && (
        <div className="pager">
          <button type="button" disabled={current === 0} onClick={() => setPage(current - 1)}>
            ‹ Prev
          </button>
          <span>
            Page {current + 1} of {pages} ({sorted.length} rows)
          </span>
          <button type="button" disabled={current >= pages - 1} onClick={() => setPage(current + 1)}>
            Next ›
          </button>
        </div>
      )}
    </div>
  );
}
