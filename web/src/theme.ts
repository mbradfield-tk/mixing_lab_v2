import { useSyncExternalStore } from "react";

export type Theme = "light" | "dark";

const KEY = "mixing-lab-theme";
const listeners = new Set<() => void>();

function initial(): Theme {
  try {
    const saved = localStorage.getItem(KEY);
    if (saved === "light" || saved === "dark") return saved;
  } catch {
    // storage blocked: fall through to the OS preference
  }
  return window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

let current: Theme = initial();

/** Apply the stored / OS theme to <html data-theme>; call before the first render. */
export function applyTheme(theme: Theme = current) {
  current = theme;
  document.documentElement.dataset.theme = theme;
}

export function setTheme(theme: Theme) {
  applyTheme(theme);
  try {
    localStorage.setItem(KEY, theme);
  } catch {
    // not persisted; still applies for this session
  }
  listeners.forEach((l) => l());
}

export function useTheme(): Theme {
  return useSyncExternalStore(
    (l) => {
      listeners.add(l);
      return () => listeners.delete(l);
    },
    () => current,
  );
}

// viz/theme.py light-theme layout colours -> dark equivalents (trace colours are left as built).
const DARK_COLORS: Record<string, string> = {
  "#ffffff": "#1b1f24",
  white: "#1b1f24",
  "#f7f8f9": "#22272d",
  "#2a2e33": "#d0d5dd",
  "#5c6670": "#aab2bd",
  "#6b7280": "#98a2b3",
  "#c9ced3": "#5c6670",
  "#eceef0": "#353b43",
  "rgba(255,255,255,0.75)": "rgba(27,31,36,0.85)",
};

function recolour(v: unknown): unknown {
  if (typeof v === "string") return DARK_COLORS[v.toLowerCase().replace(/\s+/g, "")] ?? v;
  if (Array.isArray(v)) return v.map(recolour);
  if (v && typeof v === "object") return Object.fromEntries(Object.entries(v).map(([k, x]) => [k, recolour(x)]));
  return v;
}

/** Plotly layout recoloured for the dark theme (figures are built server-side on a white theme). */
export function darkLayout(layout: Record<string, unknown>): Record<string, unknown> {
  const { template: _template, ...rest } = layout; // plotly_white template would re-impose light defaults
  return recolour(rest) as Record<string, unknown>;
}
