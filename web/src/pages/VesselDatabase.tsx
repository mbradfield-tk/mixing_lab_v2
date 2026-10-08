import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import { useSearchParams } from "react-router-dom";
import { api, ApiError, unwrap, uploadFile } from "../api/client";
import { tableUrl, useTable, type Row } from "../api/tables";
import { AdminPanel, useIsAdmin } from "../components/Admin";
import { AddForm, DatabaseTable, type Field } from "../components/Database";
import { SliderField } from "../components/Form";
import { MultiSelect } from "../components/MultiSelect";
import { NoticeBar, useNotice, type Notice } from "../components/Notice";
import { Card, ErrorNote, PageTitle } from "../components/ui";
import { VesselViewer, type VesselMedia } from "../components/VesselViewer";
import { formatG } from "../format";
import { useDebounced } from "../hooks";
import { sliderStep } from "./assessment/model";

type Run = ReturnType<typeof useNotice>["run"];

const DEFAULT_VESSEL = "TMA EasyMax-102";
// CSV columns (plus the derived D/T and H/T) shown by default, in display order.
const DEFAULT_COLUMNS = [
  "reactor_id", "reactor_name", "owner", "scale", "D_tank_m", "L_tan_tan_m", "H_bot_dish_m", "V_L_min", "V_L_max",
  "impeller_count", "D_imp_m", "D/T", "H/T", "N_rpm_min", "N_rpm_max", "shell_material",
];

/** Default property names under the server's current column labels. */
export function defaultProps(labels: Map<string, string>): string[] {
  return DEFAULT_COLUMNS.map((c) => splitLabel(labels.get(c) ?? c)[0]);
}

/** Bottom-dish height (m), as ``core.records.bottom_dish_height``: measured, else H_max - L_tan_tan, else 0. */
function bottomDishHeight(row: Row): number {
  for (const key of ["H_bot_dish_m", "H_bottom_dish_m"]) {
    const h = num(row[key]);
    if (h > 0) return h;
  }
  const hMax = num(row.H_max_m);
  const ltt = num(row.L_tan_tan_m);
  return hMax > 0 && ltt > 0 && hMax > ltt ? hMax - ltt : 0;
}

/** Geometry ratios derived from the vessel row (not stored in the CSV). */
export function vesselRatios(row: Row): { prop: string; value: string; unit: string; note: string }[] {
  const t = num(row.D_tank_m);
  const ratio = (x: number) => (t > 0 && x > 0 ? formatG(x / t, 3) : null);
  const ltt = num(row.L_tan_tan_m);
  const out = [
    { prop: "D/T", value: ratio(num(row.D_imp_m)), note: "Impeller 1 diameter / tank diameter" },
    {
      prop: "H/T",
      value: ltt > 0 ? ratio(bottomDishHeight(row) + ltt) : null,
      note: "(Bottom dish height + tan-tan length) / tank internal diameter",
    },
  ];
  return out.filter((r): r is { prop: string; value: string; note: string } => r.value !== null).map((r) => ({ ...r, unit: "–" }));
}

const ADD_FIELDS: Field[] = [
  { key: "reactor_name", label: "Vessel name *", initial: "" },
  { key: "owner", label: "Owner", initial: "" },
  { key: "scale", label: "Scale", initial: "" },
  { key: "D_tank_m", label: "Tank diameter (m)", type: "number", initial: "" },
  { key: "D_imp_m", label: "Impeller diameter (m)", type: "number", initial: "" },
  { key: "Np", label: "Power number Np", type: "number", initial: "" },
  { key: "V_L_min", label: "Min volume (L)", type: "number", initial: "" },
  { key: "V_L_max", label: "Max volume (L)", type: "number", initial: "" },
  { key: "N_rpm_min", label: "Min speed (rpm)", type: "number", initial: "" },
  { key: "N_rpm_max", label: "Max speed (rpm)", type: "number", initial: "" },
];

export interface Fill {
  total_L: number;
  level_mm: number | null;
  fill_pct: number | null;
  contact_area_m2: number | null;
  warnings: string[];
  level_warning_kind: "red" | "yellow" | null;
  other_level_warning: string;
}

/** "Name [unit]" -> [name, unit] (core.tables.split_label). */
export function splitLabel(label: string): [string, string] {
  const m = /^(.*?)\s*\[([^\]]+)\]\s*$/.exec(label);
  return m ? [m[1].trim(), m[2].trim()] : [label, ""];
}

const num = (v: unknown) => (v === null || v === undefined || v === "" ? Number.NaN : Number(v));
const fixed = (v: number, d: number) =>
  v.toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });

/** Mid working volume, else 70 % of brim-full (pages/vessel_database._default_fill_L). */
export function defaultFill(row: Row, totalL: number): number {
  const lo = num(row.V_L_min);
  const hi = num(row.V_L_max);
  const value = lo > 0 && hi > 0 ? (lo + hi) / 2 : totalL * 0.7;
  return Math.round(value * 100) / 100;
}

/** Fill slider span: the vessel's min-max volume (0 / brim-full when missing); null without a usable span. */
export function fillSliderRange(row: Row, totalL: number): [number, number] | null {
  const lo = num(row.V_L_min);
  const hi = num(row.V_L_max);
  const min = lo > 0 ? lo : 0;
  const max = hi > 0 ? hi : totalL;
  return max > min ? [min, max] : null;
}

/** One status line: volume band first, then the liquid-level / impeller warning. */
export function fillStatus(row: Row, fillL: number, res: Fill): string {
  const lo = num(row.V_L_min);
  const hi = num(row.V_L_max);
  if (lo > 0 && fillL < lo) return `🔴 Below Min Volume (${formatG(lo)} L)`;
  if (hi > 0 && fillL > hi) return `🔴 Above Max Volume (${formatG(hi)} L)`;
  if (res.level_warning_kind === "red") return "🔴 Liquid level is below the lowest impeller";
  if (res.level_warning_kind === "yellow") return "🟡 Liquid level is at the lowest impeller";
  return res.other_level_warning ? `🟡 ${res.other_level_warning}` : "";
}

function FillCaption({ res }: { res: Fill }) {
  return (
    <>
      {res.level_mm === null || res.fill_pct === null ? (
        <p>Brim-full working volume ≈ {fixed(res.total_L, 1)} L.</p>
      ) : (
        <p>
          Liquid surface at{" "}
          <strong>
            {res.level_mm >= 0 ? "+" : ""}
            {res.level_mm.toFixed(0)} mm
          </strong>{" "}
          relative to the bottom tangent line ({res.fill_pct.toFixed(0)}% of the {fixed(res.total_L, 1)} L
          brim-full volume).
          {res.contact_area_m2 !== null && (
            <>
              {" "}
              Wetted contact area ≈ <strong>{fixed(res.contact_area_m2, 3)} m²</strong>.
            </>
          )}
        </p>
      )}
      {res.warnings.length > 0 && (
        <p>
          ⚠️ <strong>Impeller–wall interference:</strong> {res.warnings.join(" ")}
        </p>
      )}
    </>
  );
}

function ExploreVessel({ names, labels }: { names: string[]; labels: Map<string, string> }) {
  const [params, setParams] = useSearchParams();
  const fallback = names.includes(DEFAULT_VESSEL) ? DEFAULT_VESSEL : (names[0] ?? "");
  const vessel = names.includes(params.get("vessel") ?? "") ? (params.get("vessel") as string) : fallback;
  const [picked, setProps] = useState<string[] | null>(null);
  const defaults = useMemo(() => defaultProps(labels), [labels]);
  const props = picked ?? defaults;
  const [fillText, setFillText] = useState("");
  const defaultedFor = useRef("");

  const row = useQuery({
    queryKey: ["table", "vessels", "row", vessel],
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/vessels/{name}", { params: { path: { name: vessel } } })) as Row,
    enabled: !!vessel,
  });
  const media = useQuery({
    queryKey: ["vessel-media", vessel],
    queryFn: async () => {
      const res = await api.GET("/api/v1/media/vessels/{name}", { params: { path: { name: vessel } } });
      if (res.response.status === 404) return null;
      return unwrap(res) as unknown as VesselMedia;
    },
    enabled: !!vessel,
  });
  const brim = useQuery({
    queryKey: ["vessel-fill", vessel, null],
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/media/vessels/{name}/fill", { params: { path: { name: vessel } } })) as unknown as Fill,
    enabled: !!vessel,
  });

  useEffect(() => {
    if (row.data && brim.data && defaultedFor.current !== vessel) {
      defaultedFor.current = vessel;
      setFillText(String(defaultFill(row.data, brim.data.total_L)));
    }
  }, [row.data, brim.data, vessel]);

  const total = brim.data?.total_L ?? 0;
  const maxFill = total > 0 ? Math.round(total * 100) / 100 : Infinity;
  const typed = Number(fillText);
  const fillL = fillText === "" || !Number.isFinite(typed) ? null : Math.min(Math.max(0, typed), maxFill);
  const debouncedFill = useDebounced(fillL, 300);
  const fill = useQuery({
    queryKey: ["vessel-fill", vessel, debouncedFill],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/media/vessels/{name}/fill", {
          params: { path: { name: vessel }, query: { fill_L: debouncedFill } },
        }),
      ) as unknown as Fill,
    enabled: !!vessel && debouncedFill !== null && defaultedFor.current === vessel,
  });

  const allProps = useMemo(() => {
    const out: string[] = [];
    for (const label of labels.values()) {
      const [prop] = splitLabel(label);
      if (prop && !out.includes(prop)) out.push(prop);
    }
    return [...out, "D/T", "H/T"];
  }, [labels]);

  const stored = Object.entries(row.data ?? {})
    .filter(([, v]) => v !== null && v !== undefined && String(v).trim() !== "")
    .map(([col, v]) => {
      const [prop, unit] = splitLabel(labels.get(col) ?? col);
      return { prop, value: String(v), unit: unit || "–", note: "" };
    });
  const derived = row.data ? vesselRatios(row.data) : [];
  const order = (p: string) => {
    const i = defaults.indexOf(p);
    return i < 0 ? defaults.length : i;
  };
  const details = [...stored, ...derived]
    .filter((d) => props.length === 0 || props.includes(d.prop))
    .sort((a, b) => order(a.prop) - order(b.prop));

  const schematicUrl =
    debouncedFill === null
      ? undefined
      : `/api/v1/media/vessels/${encodeURIComponent(vessel)}/schematic.png?fill_L=${debouncedFill}`;
  const status = row.data && fill.data && fillL !== null ? fillStatus(row.data, fillL, fill.data) : "";
  const fillRange = row.data ? fillSliderRange(row.data, total) : null;

  return (
    <Card title="Explore Vessel">
      <label className="narrow">
        Select vessel
        <select value={vessel} onChange={(e) => setParams({ vessel: e.target.value }, { replace: true })}>
          {names.map((n) => (
            <option key={n}>{n}</option>
          ))}
        </select>
      </label>
      {row.isError && <ErrorNote error={row.error} />}
      <div className="explore-top">
        <figure className="viewer-panel">
          {media.data ? (
            <VesselViewer media={media.data} name={vessel} />
          ) : media.isSuccess ? (
            <p className="muted placeholder">No image or 3D model available for this vessel.</p>
          ) : null}
        </figure>
        <section className="spec-panel" aria-label={`Properties of ${vessel}`}>
          <header>
            <h3>{vessel}</h3>
            <MultiSelect label="Properties to show" options={allProps} value={props} onChange={setProps} />
          </header>
          <dl className="spec-list">
            {details.map((d) => (
              <div key={d.prop} className={d.note ? "derived" : undefined} title={d.note || undefined}>
                <dt>{d.prop}</dt>
                <dd>
                  {d.value}
                  {d.unit !== "–" && <span className="spec-unit"> {d.unit}</span>}
                </dd>
              </div>
            ))}
          </dl>
          {derived.length > 0 && (
            <p className="muted spec-note">
              Calculated: D/T = impeller 1 diameter / tank diameter; H/T = (bottom dish height + tan-tan length) / tank
              diameter — the aspect ratio of the liquid-holding volume.
            </p>
          )}
        </section>
      </div>

      <h3>2D Schematic &amp; Liquid Level</h3>
      <div className="grid-2 explore">
        <div className="media-box">
          {schematicUrl && <img className="schematic" src={schematicUrl} alt={`Cross-section of ${vessel}`} />}
        </div>
        <div>
          <p>Enter a fill volume to draw the liquid surface on the vessel cross-section.</p>
          <div className="form-row">
            {fillRange ? (
              <SliderField
                label="Liquid fill volume (L)"
                value={fillText}
                onChange={setFillText}
                min={fillRange[0]}
                max={fillRange[1]}
                step={sliderStep(fillRange[1] - fillRange[0])}
                unit="L"
              />
            ) : (
              <label>
                Liquid fill volume (L)
                <input
                  type="number"
                  step="any"
                  min="0"
                  max={total > 0 ? maxFill : undefined}
                  value={fillText}
                  onChange={(e) => setFillText(e.target.value)}
                  onBlur={() => fillL !== null && setFillText(String(fillL))}
                />
              </label>
            )}
            <p className="fill-status">{status}</p>
          </div>
          {fill.isError && <ErrorNote error={fill.error} />}
          {fill.data && <FillCaption res={fill.data} />}
        </div>
      </div>
    </Card>
  );
}

interface ImportChange {
  id: number;
  desc: string;
}

interface ImportResult {
  applied: number;
  skipped: number;
  new_reactor_ids: number;
  count: number;
}

/** Merge an uploaded CSV, reviewing each change (approve / skip / accept all / cancel). */
function VesselImport({ run, notify }: { run: Run; notify: (n: Notice) => void }) {
  const isAdmin = useIsAdmin();
  const qc = useQueryClient();
  const input = useRef<HTMLInputElement>(null);
  const [review, setReview] = useState<{ file: File; changes: ImportChange[]; index: number; accepted: number[] } | null>(null);
  const [busy, setBusy] = useState(false);

  async function preview(file: File | undefined) {
    if (input.current) input.current.value = "";
    if (!file) return;
    setBusy(true);
    try {
      const changes = await run(
        uploadFile<ImportChange[]>(`${tableUrl("vessels")}/import/preview`, file, "POST"),
        (c) => (c.length ? `${c.length} change(s) to review.` : "No differences found — database is already up to date."),
      );
      if (changes.length) setReview({ file, changes, index: 0, accepted: [] });
    } catch {
      // reported by run()
    } finally {
      setBusy(false);
    }
  }

  async function finish(file: File, accepted: number[]) {
    setBusy(true);
    try {
      await run(
        uploadFile<ImportResult>(`${tableUrl("vessels")}/import/apply`, file, "POST", {
          accept: JSON.stringify(accepted),
        }),
        (r) =>
          `Import complete — ${r.applied} change(s) applied, ${r.skipped} skipped.` +
          (r.new_reactor_ids ? ` Assigned ${r.new_reactor_ids} new reactor ID(s).` : ""),
      );
      setReview(null);
      await qc.invalidateQueries({ queryKey: ["table", "vessels"] });
    } catch (err) {
      if (!(err instanceof ApiError && err.status === 422)) setReview(null);
    } finally {
      setBusy(false);
    }
  }

  function step(approve: boolean) {
    if (!review) return;
    const accepted = approve ? [...review.accepted, review.changes[review.index].id] : review.accepted;
    if (review.index + 1 >= review.changes.length) void finish(review.file, accepted);
    else setReview({ ...review, index: review.index + 1, accepted });
  }

  function acceptAll() {
    if (!review) return;
    const rest = review.changes.slice(review.index).map((c) => c.id);
    void finish(review.file, [...review.accepted, ...rest]);
  }

  return (
    <Card title="Import / Export">
      <p>
        Importing <strong>merges</strong> an uploaded CSV into the current database: matching vessels
        (by ID, then name) are updated and new vessels are added. Review each change individually, or
        use <strong>Accept all remaining</strong> to apply everything at once. Missing reactor IDs and
        search names are filled in automatically.
      </p>
      <div className="form-row">
        <div>
          <a className="button" href={`${tableUrl("vessels")}/export`} download>
            Download vessel database (CSV)
          </a>
        </div>
        <label>
          Import CSV (merge &amp; review changes)
          <input
            ref={input}
            type="file"
            accept=".csv,text/csv"
            disabled={!isAdmin || busy || !!review}
            onChange={(e) => void preview(e.target.files?.[0])}
          />
        </label>
      </div>

      {review && (
        <div className="modal-backdrop">
          <div className="modal" role="dialog" aria-modal="true" aria-labelledby="import-title">
            <h2 id="import-title">Review Import Changes</h2>
            <p className="muted">
              Change {review.index + 1} of {review.changes.length}
            </p>
            <div className="change-desc">
              <ReactMarkdown>{review.changes[review.index].desc}</ReactMarkdown>
            </div>
            <div className="modal-actions">
              <button type="button" className="primary" disabled={busy} onClick={() => step(true)}>
                ✅ Approve
              </button>
              <button type="button" disabled={busy} onClick={() => step(false)}>
                ⏭️ Skip
              </button>
              <button type="button" disabled={busy} onClick={acceptAll}>
                ⏩ Accept all remaining
              </button>
              <button
                type="button"
                disabled={busy}
                onClick={() => {
                  setReview(null);
                  notify({ kind: "info", text: "Import cancelled — no changes applied." });
                }}
              >
                ✖️ Cancel import
              </button>
            </div>
          </div>
        </div>
      )}
    </Card>
  );
}

export function VesselDatabase() {
  const { notice, setNotice, run } = useNotice();
  const { list, columns } = useTable("vessels");
  const names = useMemo(
    () => [...new Set((list.data?.records ?? []).map((r) => String(r.reactor_name ?? "")).filter(Boolean))].sort(),
    [list.data],
  );
  const labels = useMemo(() => new Map((columns.data ?? []).map((c) => [c.column, c.label])), [columns.data]);

  return (
    <>
      <PageTitle pageKey="Vessel_Database">Vessel Database</PageTitle>
      <p>{list.data ? `${list.data.count} vessels in database.` : "…"}</p>

      <Card title="Database">
        <p>
          Editing is enabled only when unlocked in the <strong>Admin</strong> panel at the bottom of the
          page. Choose a single column and a comparison to filter numerically — for example, set{" "}
          <strong>Column</strong> to Max Volume, <strong>Match</strong> to &gt; and search for 100.
        </p>
        <details>
          <summary>Vessel database</summary>
          <DatabaseTable table="vessels" nameKey="reactor_name" run={run} searchLabel="Search vessels" />
        </details>
      </Card>

      <ExploreVessel names={names} labels={labels} />

      <Card title="Add Vessel">
        <p className="muted">
          Enter the core geometry here; every other column can then be filled in by editing the table.
          A reactor ID and search name are assigned automatically.
        </p>
        <AddForm table="vessels" fields={ADD_FIELDS} nameKey="reactor_name" noun="vessel" run={run} submitLabel="Add vessel" />
      </Card>

      <VesselImport run={run} notify={setNotice} />
      <AdminPanel />
      <NoticeBar notice={notice} onClose={() => setNotice(null)} />
    </>
  );
}
