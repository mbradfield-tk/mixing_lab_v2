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
