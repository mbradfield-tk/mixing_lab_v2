import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { api, unwrap } from "../api/client";
import type { Column, Row } from "../api/tables";
import { DataTable } from "../components/DataTable";
import { MultiSelect } from "../components/MultiSelect";
import { NoticeBar, useNotice } from "../components/Notice";
import { Card, ErrorNote, PageLink, PageTitle } from "../components/ui";

interface ResultsList {
  records: Row[];
  count: number;
  counts: { reaction_limited: number; potentially_sensitive: number; mixing_sensitive: number };
}

interface Filters {
  reactor: string[];
  reaction: string[];
  fluid: string[];
}

const FILTERS: [keyof Filters, string][] = [
  ["reactor", "Reactor"],
  ["reaction", "Reaction"],
  ["fluid", "Fluid"],
];

const NO_FILTERS: Filters = { reactor: [], reaction: [], fluid: [] };

async function fetchResults(filters: Filters): Promise<ResultsList> {
  const query = Object.fromEntries(Object.entries(filters).filter(([, v]) => v.length));
  return unwrap(await api.GET("/api/v1/results", { params: { query } })) as unknown as ResultsList;
}

const distinct = (rows: Row[], key: string) =>
  [...new Set(rows.map((r) => r[key]).filter((v) => v !== null && v !== undefined && v !== "").map(String))].sort();

export function RecordedResults() {
  const qc = useQueryClient();
  const { notice, setNotice, run } = useNotice();
  const [filters, setFilters] = useState<Filters>(NO_FILTERS);
  const [confirmClear, setConfirmClear] = useState(false);

  const all = useQuery({ queryKey: ["results", NO_FILTERS], queryFn: () => fetchResults(NO_FILTERS) });
  const options = useMemo(
    () => Object.fromEntries(FILTERS.map(([key]) => [key, distinct(all.data?.records ?? [], key)])) as unknown as Filters,
    [all.data],
  );
  // Drop selections that no longer exist (e.g. after a refresh or clear).
  const active: Filters = {
    reactor: filters.reactor.filter((v) => options.reactor.includes(v)),
    reaction: filters.reaction.filter((v) => options.reaction.includes(v)),
    fluid: filters.fluid.filter((v) => options.fluid.includes(v)),
  };
  const view = useQuery({
    queryKey: ["results", active],
    queryFn: () => fetchResults(active),
    placeholderData: keepPreviousData,
    enabled: all.isSuccess,
  });

  const rows = view.data?.records ?? [];
  const columns: Column[] = Object.keys(all.data?.records[0] ?? {}).map((c) => ({ column: c, label: c }));
  const exportQuery = new URLSearchParams();
  for (const [key] of FILTERS) for (const v of active[key]) exportQuery.append(key, v);

  const clear = useMutation({
    mutationFn: async () => unwrap(await api.DELETE("/api/v1/results")),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["results"] }),
  });

  async function refresh() {
    const res = await all.refetch();
    await qc.invalidateQueries({ queryKey: ["results"] });
    setNotice({ kind: "info", text: `Reloaded — ${res.data?.count ?? 0} record(s) on file.` });
  }

  return (
    <>
      <PageTitle pageKey="Recorded_Results">Recorded Results</PageTitle>
      <p>
        View, filter and bulk-export the case results saved from the analysis pages (
        <strong>Save results to Recorded Results</strong> on the{" "}
        <PageLink pageKey="Vessel_Assessment" /> and <PageLink pageKey="Vessel_Comparison" /> pages).
      </p>
      <button type="button" onClick={() => void refresh()}>
        Refresh
      </button>
      {all.isError && <ErrorNote error={all.error} />}

      {all.data && all.data.count === 0 ? (
        <Card>
          <p>
            <strong>No results recorded yet.</strong> Compute a case on the Vessel Assessment or Vessel
            Comparison page and use <em>Save results to Recorded Results</em>, then click{" "}
            <strong>Refresh</strong> here.
          </p>
        </Card>
      ) : (
        all.data && (
          <>
            <Card title="Filter Results">
              <div className="form-row">
                {FILTERS.map(([key, label]) => (
                  <MultiSelect
                    key={key}
                    label={label}
                    options={options[key]}
                    value={active[key]}
                    onChange={(value) => setFilters({ ...active, [key]: value })}
                  />
                ))}
              </div>
            </Card>

            <Card title="Results Table">
              {view.isError && <ErrorNote error={view.error} />}
              <DataTable rows={rows} columns={columns} nameKey="reactor" pageSize={15} digits={4} />
              <p className="muted">
                Showing {view.data?.count ?? 0} of {all.data.count} records.
              </p>
            </Card>

            <Card title="Assessment Summary">
              <div className="summary-row">
                <p>
                  <strong>🟢 Reaction-limited:</strong> {view.data?.counts.reaction_limited ?? 0}
                </p>
                <p>
                  <strong>🟡 Potentially sensitive:</strong> {view.data?.counts.potentially_sensitive ?? 0}
                </p>
                <p>
                  <strong>🔴 Mixing-sensitive / limited:</strong> {view.data?.counts.mixing_sensitive ?? 0}
                </p>
              </div>
            </Card>

            <Card title="Export">
              <p>Downloads the currently filtered set as CSV.</p>
              <a className="button" href={`/api/v1/results/export?${exportQuery.toString()}`} download>
                Download results (CSV)
              </a>
            </Card>

            <Card title="Manage Records">
              {confirmClear ? (
                <>
                  <p>
                    <strong>⚠️ Are you sure? This will permanently delete all recorded results.</strong>
                  </p>
                  <div className="modal-actions">
                    <button
                      type="button"
                      className="primary"
                      disabled={clear.isPending}
                      onClick={() =>
                        void run(clear.mutateAsync(), "All recorded results cleared.")
                          .then(() => {
                            setConfirmClear(false);
                            setFilters(NO_FILTERS);
                          })
                          .catch(() => undefined)
                      }
                    >
                      Yes, delete all
                    </button>
                    <button type="button" onClick={() => setConfirmClear(false)}>
                      Cancel
                    </button>
                  </div>
                </>
              ) : (
                <button type="button" onClick={() => setConfirmClear(true)}>
                  Clear all recorded results
                </button>
              )}
            </Card>
          </>
        )
      )}
      <NoticeBar notice={notice} onClose={() => setNotice(null)} />
    </>
  );
}
