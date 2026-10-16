import type { ReactNode } from "react";

// "N_js", "t_{rxn}", "Da_macro" -> subscript; "10^4" -> superscript.
const TOKEN = /([A-Za-zΑ-Ωα-ωµ]+)_(\{[^}]+\}|[A-Za-z0-9]+)|\^(-?\d+)/g;

/** Plain text with ``x_sub`` / ``x^n`` notation rendered as real sub- and superscripts. */
export function sym(text: string): ReactNode {
  const out: ReactNode[] = [];
  let last = 0;
  let key = 0;
  for (const m of text.matchAll(TOKEN)) {
    out.push(text.slice(last, m.index));
    if (m[1]) out.push(m[1], <sub key={key++}>{m[2].replace(/[{}]/g, "")}</sub>);
    else out.push(<sup key={key++}>{m[3]}</sup>);
    last = m.index + m[0].length;
  }
  if (!out.length) return text;
  out.push(text.slice(last));
  return <>{out}</>;
}

/** ``sym`` for strings; other nodes unchanged. */
export const symNode = (node: ReactNode): ReactNode => (typeof node === "string" ? sym(node) : node);
