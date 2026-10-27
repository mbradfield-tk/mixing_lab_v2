import { lazy, Suspense } from "react";

const MoleculeSvg = lazy(() => import("./MoleculeSvg"));

/** Molecular structure drawn client-side from a SMILES string; nothing when `smiles` is blank. */
export function Molecule({
  smiles,
  caption,
  size = 200,
}: {
  smiles: string | null | undefined;
  caption?: string;
  size?: number;
}) {
  const s = (smiles ?? "").trim();
  if (!s) return null;
  return (
    <figure className="molecule">
      <Suspense fallback={<p className="muted">Loading structure…</p>}>
        <MoleculeSvg smiles={s} size={size} />
      </Suspense>
      <figcaption className="muted">
        <code>{s}</code>
        {caption && <span>{caption}</span>}
      </figcaption>
    </figure>
  );
}

/** Caption for the aqueous-solution library entries, whose SMILES is the solute only. */
export function solventStructureCaption(name: string): string | undefined {
  return /\(aq\)\s*$/i.test(name) ? "Solute shown — aqueous solution" : undefined;
}
