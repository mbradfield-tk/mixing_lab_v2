import { useEffect, useRef, useState } from "react";
import SmilesDrawer from "smiles-drawer";

const drawers = new Map<number, InstanceType<typeof SmilesDrawer.SmiDrawer>>();

function drawerFor(size: number) {
  let d = drawers.get(size);
  if (!d) {
    d = new SmilesDrawer.SmiDrawer({ width: size, height: size, bondThickness: 1.2, padding: 12 });
    drawers.set(size, d);
  }
  return d;
}

/** Draws `smiles` into an inline SVG; renders a muted note when the string does not parse. */
export default function MoleculeSvg({ smiles, size }: { smiles: string; size: number }) {
  const ref = useRef<SVGSVGElement>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    const svg = ref.current;
    if (!svg) return;
    svg.replaceChildren();
    setFailed(false);
    drawerFor(size).draw(smiles, svg, "light", null, () => setFailed(true));
  }, [smiles, size]);

  return (
    <>
      <svg
        ref={ref}
        role="img"
        aria-label={`Structure ${smiles}`}
        width={size}
        height={size}
        viewBox={`0 0 ${size} ${size}`}
        style={{ display: failed ? "none" : "block" }}
      />
      {failed && <p className="muted">Structure unavailable (invalid SMILES).</p>}
    </>
  );
}
