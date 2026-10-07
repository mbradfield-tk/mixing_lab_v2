import { useRef, useState, type FormEvent, type ReactNode } from "react";
import { SEARCH_OPS, tableUrl, useTable, type Row, type TableKey } from "../api/tables";
import { useDebounced } from "../hooks";
import { useIsAdmin } from "./Admin";
import { DataTable, parseCell } from "./DataTable";
import type { useNotice } from "./Notice";
import { Card, ErrorNote } from "./ui";

type Run = ReturnType<typeof useNotice>["run"];

/** Search box + editable table for one database table (edits need the admin token). */
export function DatabaseTable({
  table,
  nameKey,
  run,
  rowFilter,
  searchLabel = "Search",
}: {
  table: TableKey;
  nameKey: string;
  run: Run;
  rowFilter?: (row: Row) => boolean;
  searchLabel?: string;
}) {
  const isAdmin = useIsAdmin();
  const [q, setQ] = useState("");
  const [field, setField] = useState("");
  const [op, setOp] = useState("contains");
  const query = useDebounced(q);
  const { list, columns, update, remove } = useTable(table, { q: query, field, op: field ? op : "contains" });

  const rows = (list.data?.records ?? []).filter(rowFilter ?? (() => true));
  const cols = columns.data ?? [];

  return (
    <>
      <div className="search-row">
        <label className="grow">
          {searchLabel}
          <input type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Type to filter…" />
        </label>
        <label>
          Column
          <select
            value={field}
            onChange={(e) => {
              setField(e.target.value);
              if (!e.target.value) setOp("contains");
            }}
          >
            <option value="">All columns</option>
            {cols.map((c) => (
              <option key={c.column} value={c.column}>
                {c.label}
              </option>
            ))}
          </select>
        </label>
        <label>
          Match
          <select value={op} onChange={(e) => setOp(e.target.value)} disabled={!field}>
            {SEARCH_OPS.map((o) => (
              <option key={o}>{o}</option>
            ))}
          </select>
        </label>
      </div>
      {list.data?.status && <p className="muted">{list.data.status}</p>}
      {list.isError && <ErrorNote error={list.error} />}
      {columns.isError && <ErrorNote error={columns.error} />}
      <DataTable
        rows={rows}
        columns={cols}
        nameKey={nameKey}
        editable={isAdmin}
        onEdit={(row, column, value) =>
          run(update.mutateAsync({ name: String(row[nameKey]), changes: { [column]: value } }), "Saved.")
        }
        onDelete={(row) => run(remove.mutateAsync(String(row[nameKey])), `Deleted '${String(row[nameKey])}'.`)}
      />
      <p className="muted">
        {list.isFetching ? "Loading…" : `${rows.length} row${rows.length === 1 ? "" : "s"} shown.`}{" "}
        {isAdmin ? "Click a cell to edit it; changes save immediately." : "Unlock the Admin panel to edit."}
      </p>
    </>
  );
}

export interface Field {
  key: string;
  label: ReactNode;
  type?: "text" | "number" | "select";
  options?: string[];
  initial: string | number;
}

/** Validated "Add …" form; the server checks the record and reports problems. */
export function AddForm({
  table,
  fields,
  nameKey,
  noun,
  run,
  submitLabel,
}: {
  table: TableKey;
  fields: Field[];
  nameKey: string;
  noun: string;
  run: Run;
  submitLabel: string;
}) {
  const isAdmin = useIsAdmin();
  const { create } = useTable(table);
  const initial = () => Object.fromEntries(fields.map((f) => [f.key, String(f.initial)]));
  const [values, setValues] = useState<Record<string, string>>(initial);

  async function submit(e: FormEvent) {
    e.preventDefault();
    const data: Row = Object.fromEntries(
      fields.map((f) => [f.key, parseCell(values[f.key] ?? "", f.type === "number")]),
    );
    const name = values[nameKey]?.trim() ?? "";
    await run(create.mutateAsync(data), `Added ${noun} '${name}'.`)
      .then(() => setValues((v) => ({ ...v, [nameKey]: "" })))
      .catch(() => undefined);
  }

  return (
    <form onSubmit={submit}>
      <div className="form-row">
        {fields.map((f) => (
          <label key={f.key}>
            {f.label}
            {f.type === "select" ? (
              <select value={values[f.key]} onChange={(e) => setValues({ ...values, [f.key]: e.target.value })}>
                {f.options?.map((o) => (
                  <option key={o}>{o}</option>
                ))}
              </select>
            ) : (
              <input
                type={f.type === "number" ? "number" : "text"}
                step="any"
                value={values[f.key]}
                onChange={(e) => setValues({ ...values, [f.key]: e.target.value })}
              />
            )}
          </label>
        ))}
      </div>
      <button type="submit" disabled={!isAdmin || create.isPending}>
        {submitLabel}
      </button>
      {!isAdmin && <span className="muted"> Unlock the Admin panel to add records.</span>}
    </form>
  );
}

/** CSV download (anyone) and replace-the-table upload (admin). */
export function ImportExport({
  table,
  noun,
  run,
  title = "Import / Export",
}: {
  table: TableKey;
  noun: string;
  run: Run;
  title?: string;
}) {
  const isAdmin = useIsAdmin();
  const { importCsv } = useTable(table);
  const input = useRef<HTMLInputElement>(null);

  function onFile(file: File | undefined) {
    if (input.current) input.current.value = "";
    if (!file) return;
    if (!window.confirm(`Replace ALL ${noun}s with the contents of '${file.name}'?`)) return;
    void run(importCsv.mutateAsync(file), (r) => `Imported ${r.count} ${noun}s (replaced database).`).catch(
      () => undefined,
    );
  }

  return (
    <Card title={title}>
      <div className="form-row">
        <div>
          <a className="button" href={`${tableUrl(table)}/export`} download>
            Download {noun} database (CSV)
          </a>
        </div>
        <label>
          Import CSV (replaces the database)
          <input
            ref={input}
            type="file"
            accept=".csv,text/csv"
            disabled={!isAdmin || importCsv.isPending}
            onChange={(e) => onFile(e.target.files?.[0])}
          />
        </label>
      </div>
    </Card>
  );
}
