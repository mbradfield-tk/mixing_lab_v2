import { lazy, Suspense } from "react";

const MoleculeSvg = lazy(() => import("./MoleculeSvg"));

// smiles-drawer labels an isolated atom element-first ("OH₂", "ClH"); use the conventional hydride formula.
const HYDRIDES: Record<string, string> = {
  O: "H₂O", S: "H₂S", F: "HF", Cl: "HCl", Br: "HBr", I: "HI", N: "NH₃", C: "CH₄",
};

/** Conventional formula for a single-heavy-atom SMILES (e.g. "O" → "H₂O"); undefined otherwise. */
export function singleAtomFormula(smiles: string): string | undefined {
  return HYDRIDES[smiles.trim()];
}

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
  const formula = singleAtomFormula(s);
  return (
    <figure className="molecule">
      {formula ? (
        <div className="molecule-formula" style={{ width: size, height: size }} role="img" aria-label={formula}>
          {formula}
        </div>
      ) : (
        <Suspense fallback={<p className="muted">Loading structure…</p>}>
          <MoleculeSvg smiles={s} size={size} />
        </Suspense>
      )}
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
