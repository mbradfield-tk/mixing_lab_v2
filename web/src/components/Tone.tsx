import type { ReactNode } from "react";

export type Tone = "critical" | "warning" | "caution" | "ok" | "unknown" | "info";

const ICON_TONES: [string, Tone][] = [
  ["🔴", "critical"],
  ["🟡", "warning"],
  ["⚠️", "warning"],
  ["🟢", "ok"],
  ["✅", "ok"],
  ["⚪", "unknown"],
];

/** Severity of a server status string from its traffic-light icon. */
export function toneOf(text: string | null | undefined): Tone {
  const t = String(text ?? "");
  return ICON_TONES.find(([icon]) => t.includes(icon))?.[1] ?? "info";
}

export const STATUS_ICON = /^\s*(🔴|🟡|⚠️|🟢|✅|⚪)\s*/u;

/** The status text without its leading traffic-light icon. */
export const stripIcon = (text: string) => text.replace(STATUS_ICON, "");

export function Pill({ tone, children }: { tone: Tone; children: ReactNode }) {
  return <span className={`pill tone-${tone}`}>{children}</span>;
}
