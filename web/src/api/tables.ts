import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, unwrap, uploadFile } from "./client";

/** The name-keyed database tables served by `table_router`. */
export type TableKey = "vessels" | "particles" | "reactions" | "fluids/custom";
export type Row = Record<string, unknown>;

export interface Column {
  column: string;
  label: string;
}

export interface Search {
  q: string;
  field?: string;
  op?: string;
}

export const SEARCH_OPS = ["contains", "=", "<", "<=", ">", ">="] as const;

export const tableUrl = (table: TableKey) => `/api/v1/${table}`;

// Every table router has the same shape, so one representative path keeps openapi-fetch typed.
const LIST = (t: TableKey) => tableUrl(t) as "/api/v1/particles";
const ONE = (t: TableKey) => `${tableUrl(t)}/{name}` as "/api/v1/particles/{name}";
const COLUMNS = (t: TableKey) => `${tableUrl(t)}/columns` as "/api/v1/particles/columns";

/** Records (server-side search), column labels, and the write mutations of one table. */
export function useTable(table: TableKey, search: Search = { q: "" }) {
  const qc = useQueryClient();
  const q = search.q.trim();
  const query = q ? { q, field: search.field || undefined, op: search.op ?? "contains" } : {};

  const list = useQuery({
    queryKey: ["table", table, query],
    queryFn: async () =>
      unwrap(await api.GET(LIST(table), { params: { query } })) as {
        records: Row[];
        count: number;
        status: string;
      },
    placeholderData: keepPreviousData,
  });

  const columns = useQuery({
    queryKey: ["table", table, "columns"],
    queryFn: async () => unwrap(await api.GET(COLUMNS(table))) as unknown as Column[],
    staleTime: Infinity,
  });

  // Refresh this table's records everywhere (e.g. the blend component list); labels never change.
  const onSuccess = () =>
    qc.invalidateQueries({ queryKey: ["table", table], predicate: (q) => q.queryKey[2] !== "columns" });

  const create = useMutation({
    mutationFn: async (data: Row) => unwrap(await api.POST(LIST(table), { body: data })) as Row,
    onSuccess,
  });
  const update = useMutation({
    mutationFn: async ({ name, changes }: { name: string; changes: Row }) =>
      unwrap(await api.PATCH(ONE(table), { params: { path: { name } }, body: changes })) as Row,
    onSuccess,
  });
  const remove = useMutation({
    mutationFn: async (name: string) =>
      unwrap(await api.DELETE(ONE(table), { params: { path: { name } } })),
    onSuccess,
  });
  const importCsv = useMutation({
    mutationFn: (file: File) => uploadFile<{ count: number }>(`${tableUrl(table)}/import`, file),
    onSuccess,
  });

  return { list, columns, create, update, remove, importCsv };
}
