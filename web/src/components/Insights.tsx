import type { ReactNode } from "react";
import type { Row } from "../api/tables";
import { Markdown } from "./Markdown";
import { ResultTable } from "./ResultTable";
import { Pill, type Tone } from "./Tone";

export { Pill, stripIcon, toneOf, type Tone } from "./Tone";

/** "U (W/m2.K)" -> ["U", "W/m2.K"]. */
export function splitUnit(label: string): [string, string] {
  const m = /^(.*?)\s*\(([^()]*)\)\s*$/.exec(label);
  return m ? [m[1], m[2]] : [label, ""];
}

/** Headline result: large, colour-coded by severity. */
export function VerdictBanner({
  tone,
  eyebrow,
  title,
  children,
}: {
  tone: Tone;
  eyebrow?: ReactNode;
  title: ReactNode;
  children?: ReactNode;
}) {
  return (
    <section className={`verdict tone-${tone}`} role="status">
      {eyebrow && <div className="verdict-eyebrow">{eyebrow}</div>}
      <div className="verdict-title">{title}</div>
      {children && <div className="verdict-body">{children}</div>}
    </section>
  );
}

export function InsightGrid({ children }: { children: ReactNode }) {
  return <div className="insight-grid">{children}</div>;
}

/** One finding: area, severity pill and supporting detail. */
export function InsightCard({
  tone,
  title,
  status,
  children,
}: {
  tone: Tone;
  title: ReactNode;
  status?: ReactNode;
  children?: ReactNode;
}) {
  return (
    <article className={`insight tone-${tone}`}>
      <header>
        <span className="insight-title">{title}</span>
        {status && <Pill tone={tone}>{status}</Pill>}
      </header>
      {children && <div className="insight-body">{children}</div>}
    </article>
  );
}

export interface Stat {
  label: ReactNode;
  value: ReactNode;
  unit?: string;
  tone?: Tone;
  hint?: ReactNode;
  /** Text status: spans two columns with a smaller value font. */
  wide?: boolean;
}

export function StatGrid({ stats, size = "md" }: { stats: Stat[]; size?: "md" | "sm" }) {
  return (
    <div className={`stat-grid stat-${size}`}>
      {stats.map((s, i) => (
        <div key={i} className={`stat tone-${s.tone ?? "info"}${s.wide ? " stat-wide" : ""}`}>
          <div className="stat-label">{s.label}</div>
          <div className="stat-value">
            {s.value}
            {s.unit && s.unit !== "–" && <span className="stat-unit"> {s.unit}</span>}
          </div>
          {s.hint && <div className="stat-hint">{s.hint}</div>}
        </div>
      ))}
    </div>
  );
}

/** Stats from Parameter/Value/Units-style rows. */
export function statsFromRows(rows: Row[], label = "Parameter", value = "Value", unit = "Units"): Stat[] {
  return rows.map((r) => {
    const raw = String(r[label] ?? "");
    const [name, inline] = unit in r ? [raw, String(r[unit] ?? "")] : splitUnit(raw);
    const v = r[value];
    return { label: name, value: v === null || v === undefined || v === "" ? "—" : String(v), unit: inline };
  });
}

/** Numbered recommended actions with their area tag. */
export function ActionList({ items }: { items: { area: string; action: string }[] }) {
  return (
    <ol className="action-list">
      {items.map((a, i) => (
        <li key={i}>
          <span className="action-area">{a.area}</span>
          <span className="action-text">
            <Markdown inline>{a.action}</Markdown>
          </span>
        </li>
      ))}
    </ol>
  );
}

/** Horizontal stage tracker (e.g. Bourne Tests 1-3). */
export function Stages({ items }: { items: { label: string; status: string; tone: Tone; detail?: ReactNode }[] }) {
  return (
    <ol className="stages">
      {items.map((s, i) => (
        <li key={i} className={`stage tone-${s.tone}`}>
          <div className="stage-dot">{i + 1}</div>
          <div className="stage-label">{s.label}</div>
          <Pill tone={s.tone}>{s.status}</Pill>
          {s.detail && <div className="stage-detail">{s.detail}</div>}
        </li>
      ))}
    </ol>
  );
}

/** Measured change against its threshold; the marker shows the threshold. */
export function ThresholdBar({ value, threshold, tone }: { value: number; threshold: number; tone: Tone }) {
  const scale = Math.max(value, threshold) * 1.25 || 1;
  return (
    <div className="threshold-bar" aria-label={`${value.toFixed(1)}% vs threshold ${threshold.toFixed(0)}%`}>
      <div className={`threshold-fill tone-${tone}`} style={{ width: `${Math.min(100, (value / scale) * 100)}%` }} />
      <div className="threshold-mark" style={{ left: `${(threshold / scale) * 100}%` }} title={`Threshold ${threshold}%`} />
    </div>
  );
}

export interface ScaleZone {
  to: number;
  label: string;
  tone: Tone;
}

/** Position (0-100 %) of ``value`` on a log axis from ``min`` to ``max``, clamped. */
export function logPosition(value: number, min: number, max: number): number {
  const v = Math.min(Math.max(value, min), max);
  return ((Math.log10(v) - Math.log10(min)) / (Math.log10(max) - Math.log10(min))) * 100;
}

/** Log-scale track of coloured zones with value markers (e.g. Da against the 0.1 / 1 thresholds). */
export function LogScale({
  min,
  max,
  zones,
  markers,
  unit = "",
}: {
  min: number;
  max: number;
  zones: ScaleZone[];
  markers: { label: string; value: number }[];
  unit?: string;
}) {
  const ticks: number[] = [];
  for (let e = Math.ceil(Math.log10(min)); e <= Math.floor(Math.log10(max)); e++) ticks.push(10 ** e);
  const edges = zones.map((z) => logPosition(z.to, min, max));
  const placed = markers
    .map((m) => ({ ...m, pos: logPosition(m.value, min, max) }))
    .sort((a, b) => a.pos - b.pos)
    .map((m, i, all) => ({ ...m, row: i > 0 && m.pos - all[i - 1].pos < 22 ? (i % 2) : 0 }));
  const rows = Math.max(1, ...placed.map((m) => m.row + 1));
  return (
    <div className="log-scale">
      <div className="log-markers" style={{ height: `${rows * 26 + 4}px` }}>
        {placed.map((m) => (
          <span
            key={m.label}
            className={`log-marker${m.pos < 10 ? " edge-start" : m.pos > 90 ? " edge-end" : ""}`}
            style={{ left: `${m.pos}%`, bottom: `${m.row * 26}px` }}
          >
            <b>{m.label}</b> {Number(m.value.toPrecision(3))}
            {unit}
          </span>
        ))}
      </div>
      <div className="log-track">
        {zones.map((z, i) => (
          <span key={z.label} className={`log-zone tone-${z.tone}`} style={{ width: `${edges[i] - (edges[i - 1] ?? 0)}%` }}>
            {z.label}
          </span>
        ))}
      </div>
      <div className="log-ticks">
        {ticks.map((t) => (
          <span key={t} style={{ left: `${logPosition(t, min, max)}%` }}>
            {t >= 1 ? t : t.toPrecision(1)}
          </span>
        ))}
      </div>
    </div>
  );
}

/** The source table, collapsed, for reference and CSV download. */
export function TableDetails({ rows, csvName, stale, summary = "Show as table" }: { rows: Row[]; csvName?: string; stale?: boolean; summary?: string }) {
  if (!rows.length) return null;
  return (
    <details className="table-details">
      <summary>{summary}</summary>
      <ResultTable rows={rows} csvName={csvName} stale={stale} />
    </details>
  );
}
