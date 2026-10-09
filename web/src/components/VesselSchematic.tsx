import { useMemo, useRef, useState, type CSSProperties, type PointerEvent, type ReactNode } from "react";

type Pt = [number, number];

export interface DrawingImpeller {
  index: number;
  d_mm: number;
  cy_mm: number;
  h_mm: number;
  clearance_mm: number;
  type: string;
  style: "pitched" | "hydrofoil" | "rushton" | "curved" | "halfmoon" | "chevron" | "anchor" | "flat" | "generic";
  blades: number | null;
  angle_deg: number | null;
  wall_hit: boolean;
}

export interface Drawing {
  D_mm: number;
  H_mm: number;
  bot_depth_mm: number;
  top_depth_mm: number;
  bot_kind: string;
  top_kind: string;
  bottom_label: string;
  top_label: string;
  full_top_mm: number | null;
  wall_mm: number;
  glass_lined: boolean;
  baffles: number | null;
  bottom: Pt[];
  top: Pt[];
  impellers: DrawingImpeller[];
  capacity: { z_mm: number[]; V_L: number[] };
  total_L: number;
  V_min_L: number | null;
  V_max_L: number | null;
  vortex: { fill_L: number | null; rpm: number; regime: string; r_mm: number[]; z_mm: number[] } | null;
}

const IMP_COLORS = ["#1976D2", "#F57C00", "#388E3C"];

/** Linear interpolation of ``x`` over ascending ``xs``. */
export function interp(x: number, xs: number[], ys: number[]): number {
  if (!xs.length) return Number.NaN;
  if (x <= xs[0]) return ys[0];
  for (let i = 1; i < xs.length; i++) {
    if (x <= xs[i]) {
      const span = xs[i] - xs[i - 1];
      return span > 0 ? ys[i - 1] + ((x - xs[i - 1]) / span) * (ys[i] - ys[i - 1]) : ys[i];
    }
  }
  return ys[ys.length - 1];
}

/** A round graduation step giving roughly ``n`` divisions of ``span``. */
export function niceStep(span: number, n = 8): number {
  if (!(span > 0)) return 1;
  const raw = span / n;
  const p = 10 ** Math.floor(Math.log10(raw));
  return ([1, 2, 2.5, 5, 10].find((m) => m * p >= raw) ?? 10) * p;
}

const fmtL = (v: number) => (v >= 100 ? v.toFixed(0) : v >= 10 ? v.toFixed(1) : String(Number(v.toPrecision(3))));
const path = (pts: Pt[]) => pts.map(([x, z], i) => `${i ? "L" : "M"}${x.toFixed(3)} ${(-z).toFixed(3)}`).join(" ");

/** Vessel interior outline (x, z) clockwise from the left tangent line. */
function interior(d: Drawing): Pt[] {
  const R = d.D_mm / 2;
  const bottom = d.bottom;
  const top = d.top;
  return [
    ...[...bottom].reverse().map(([r, z]): Pt => [-r, z]),
    ...bottom.slice(1).map(([r, z]): Pt => [r, z]),
    [R, d.H_mm],
    ...[...top].reverse().map(([r, z]): Pt => [r, z]),
    ...top.slice(1).map(([r, z]): Pt => [-r, z]),
  ];
}

function Impeller({ imp, k, spin }: { imp: DrawingImpeller; k: number; spin: CSSProperties | undefined }) {
  const r = imp.d_mm / 2;
  const h = Math.max(imp.h_mm, 0.6 * k);
  const top = -(imp.cy_mm + h / 2);
  const bot = -(imp.cy_mm - h / 2);
  const y = -imp.cy_mm;
  const color = IMP_COLORS[(imp.index - 1) % IMP_COLORS.length];
  const stroke = imp.wall_hit ? "#C62828" : color;
  const common = { fill: color, fillOpacity: 0.75, stroke, strokeWidth: imp.wall_hit ? 2.2 : 1.2, vectorEffect: "non-scaling-stroke" as const };
  const hub = Math.max(r * 0.12, k * 0.8);
  const pitch = ((imp.angle_deg ?? 45) * Math.PI) / 180;
  let blades: ReactNode;
  switch (imp.style) {
    case "pitched":
    case "flat": {
      const skew = imp.style === "pitched" ? (h / Math.tan(pitch)) * 0.5 : 0;
      blades = (
        <>
          <rect x={-r} y={top} width={r - hub} height={h} {...common} />
          <rect x={hub} y={top} width={r - hub} height={h} {...common} />
          <polygon points={`${-hub * 1.6 - skew},${bot} ${hub * 1.6 - skew},${bot} ${hub * 1.6 + skew},${top} ${-hub * 1.6 + skew},${top}`} {...common} fillOpacity={0.95} />
        </>
      );
      break;
    }
    case "hydrofoil": {
      const tip = h * 0.4;
      const foil = (s: 1 | -1) =>
        `M ${s * hub} ${bot} L ${s * r} ${y + tip / 2} Q ${s * (r + h * 0.15)} ${y - tip / 2} ${s * r} ${y - tip / 2} Q ${s * (hub + (r - hub) * 0.45)} ${top - h * 0.25} ${s * hub} ${top} Z`;
      blades = (
        <>
          <path d={foil(-1)} {...common} />
          <path d={foil(1)} {...common} />
        </>
      );
      break;
    }
    case "rushton":
    case "curved": {
      const disc = r * 0.72;
      const rx = imp.style === "curved" ? h * 0.35 : 0;
      blades = (
        <>
          <rect x={-disc} y={y - Math.max(h * 0.06, 0.25 * k)} width={2 * disc} height={Math.max(h * 0.12, 0.5 * k)} {...common} />
          <rect x={-r} y={top} width={r - disc + hub * 0.3} height={h} rx={rx} {...common} />
          <rect x={disc - hub * 0.3} y={top} width={r - disc + hub * 0.3} height={h} rx={rx} {...common} />
          <rect x={-hub * 1.4} y={top} width={hub * 2.8} height={h} rx={rx} {...common} fillOpacity={0.95} />
        </>
      );
      break;
    }
    case "halfmoon":
      blades = <path d={`M ${-r} ${top} L ${r} ${top} A ${r} ${h} 0 0 1 ${-r} ${top} Z`} {...common} />;
      break;
    case "chevron": {
      const drop = Math.max(h, r * 0.5);
      blades = (
        <polygon
          points={`${-r},${bot - drop - h} 0,${bot - h} ${r},${bot - drop - h} ${r},${bot - drop} 0,${bot} ${-r},${bot - drop}`}
          {...common}
        />
      );
      break;
    }
    default:
      blades = <rect x={-r} y={top} width={2 * r} height={h} rx={h * 0.2} {...common} />;
  }
  const detail = [
    imp.type,
    `⌀ ${imp.d_mm.toFixed(0)} mm`,
    `clearance ${imp.clearance_mm.toFixed(0)} mm`,
    imp.blades ? `${imp.blades} blades` : "",
    imp.wall_hit ? "⚠ touches the wall / dish" : "",
  ].filter(Boolean);
  return (
    <g className="schem-impeller">
      <title>{`Impeller ${imp.index}: ${detail.join(" · ")}`}</title>
      <g className={spin ? "schem-spin" : undefined} style={spin}>
        {blades}
      </g>
      <rect x={-hub} y={top - h * 0.1} width={2 * hub} height={h * 1.2} rx={hub * 0.3} fill="#5c6670" />
    </g>
  );
}

/**
 * Interactive vessel cross-section drawn from ``/media/vessels/{name}/drawing``: true head profiles,
 * baffles and impellers, a volume-graduated wall, and a liquid surface you can drag to set the fill.
 */
export function VesselSchematic({
  data,
  fillL,
  rpm,
  fillRange,
  onFill,
  name,
}: {
  data: Drawing;
  fillL: number | null;
  rpm: number | null;
  fillRange: [number, number] | null;
  onFill?: (litres: number) => void;
  name: string;
}) {
  const svg = useRef<SVGSVGElement>(null);
  const [hover, setHover] = useState<number | null>(null);
  const [dragging, setDragging] = useState(false);

  const R = data.D_mm / 2;
  const H = data.H_mm;
  const zBottom = -data.bot_depth_mm;
  const zRoof = H + data.top_depth_mm;
  const k = Math.max(data.D_mm, zRoof - zBottom) / 100;
  const font = 3.4 * k;
  const wall = Math.max(data.wall_mm, 1.1 * k);
  const cap = data.capacity;
  const zOf = (v: number) => interp(v, cap.V_L, cap.z_mm);
  const vOf = (z: number) => interp(z, cap.z_mm, cap.V_L);
  const outline = useMemo(() => interior(data), [data]);

  const level = fillL !== null && fillL > 0 ? zOf(Math.min(fillL, data.total_L)) : null;
  const vortexLive =
    !!data.vortex && rpm !== null && data.vortex.fill_L !== null && fillL !== null && Math.abs(data.vortex.fill_L - fillL) < 1e-9;

  // Graduations along the left wall.
  const step = niceStep(data.total_L);
  const ticks: number[] = [];
  for (let v = step; v < data.total_L * 0.999; v += step) ticks.push(v);
  const gx = -R - wall;
  const labelChars = Math.max(...ticks.map((v) => fmtL(v).length), 4);
  const scaleW = labelChars * font * 0.6 + 4 * k;
  const dimX = gx - scaleW - 3 * k;

  // Impeller labels on the right, nudged apart when they would overlap.
  const labels = [...data.impellers]
    .sort((a, b) => a.cy_mm - b.cy_mm)
    .map((imp) => ({ imp, z: imp.cy_mm }));
  for (let i = 1; i < labels.length; i++) labels[i].z = Math.max(labels[i].z, labels[i - 1].z + font * 1.3);
  const labelX = R + wall + 3 * k;
  const labelText = (imp: DrawingImpeller) => `Imp ${imp.index} · ⌀${imp.d_mm.toFixed(0)} · C ${imp.clearance_mm.toFixed(0)} mm`;
  const labelW = Math.max(0, ...data.impellers.map((i) => labelText(i).length)) * font * 0.56;

  const driveH = 9 * k;
  const zTop = Math.max(zRoof, data.full_top_mm ?? 0) + driveH + font * 1.6;
  const zBot = zBottom - 4 * k - font * 1.6;
  const xL = dimX - font * 1.6;
  const xR = labelX + labelW + 2 * k;
  const viewBox = `${xL} ${-zTop} ${xR - xL} ${zTop - zBot}`;

  function zFromEvent(e: PointerEvent): number {
    const m = svg.current?.getScreenCTM();
    if (!m) return Number.NaN;
    const p = new DOMPoint(e.clientX, e.clientY).matrixTransform(m.inverse());
    return -p.y;
  }
  function setFromZ(z: number) {
    if (!onFill) return;
    const lo = fillRange?.[0] ?? 0;
    const hi = fillRange?.[1] ?? data.total_L;
    const v = Math.min(Math.max(vOf(Math.min(Math.max(z, zBottom), H)), lo), hi);
    onFill(Number(v.toPrecision(3)));
  }

  const spinPeriod = rpm && rpm > 0 ? Math.max(0.5, 120 / rpm) : null;
  const spin = spinPeriod ? ({ animationDuration: `${spinPeriod}s` } as CSSProperties) : undefined;
  const shaftW = Math.max(R * 0.035, 0.7 * k);
  const lowest = data.impellers.length ? Math.min(...data.impellers.map((i) => i.cy_mm - i.h_mm / 2)) : 0;
  const hoverV = hover !== null ? vOf(hover) : null;
  const baffleW = data.baffles && data.baffles > 1 ? data.D_mm / 12 : 0;

  const liquid =
    level === null ? null : vortexLive ? (
      <path
        d={
          path([
            ...[...data.vortex!.r_mm].reverse().map((r, i): Pt => [-r, data.vortex!.z_mm[data.vortex!.z_mm.length - 1 - i]]),
            ...data.vortex!.r_mm.map((r, i): Pt => [r, data.vortex!.z_mm[i]]),
            [R + wall, zBottom - k],
            [-R - wall, zBottom - k],
          ]) + " Z"
        }
        fill="url(#schem-liquid)"
      />
    ) : (
      <rect x={-R} y={-level} width={2 * R} height={level - zBottom + k} fill="url(#schem-liquid)" />
    );

  return (
    <figure className="schematic-figure">
      <svg
        ref={svg}
        className={`vessel-schematic${onFill ? " draggable" : ""}${dragging ? " dragging" : ""}`}
        viewBox={viewBox}
        role="img"
        aria-label={`Cross-section of ${name}`}
        style={{ fontSize: font }}
        onPointerDown={(e) => {
          if (!onFill) return;
          e.currentTarget.setPointerCapture(e.pointerId);
          setDragging(true);
          setFromZ(zFromEvent(e));
        }}
        onPointerMove={(e) => {
          const z = zFromEvent(e);
          if (dragging) setFromZ(z);
          else setHover(z >= zBottom && z <= H ? z : null);
        }}
        onPointerUp={() => setDragging(false)}
        onPointerLeave={() => setHover(null)}
      >
        <defs>
          <linearGradient id="schem-liquid" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stopColor="#7fd3f7" stopOpacity="0.75" />
            <stop offset="1" stopColor="#0277bd" stopOpacity="0.55" />
          </linearGradient>
          <linearGradient id="schem-steel" x1="0" y1="0" x2="1" y2="0">
            <stop offset="0" stopColor="#9aa3ab" />
            <stop offset="0.5" stopColor="#e3e7ea" />
            <stop offset="1" stopColor="#9aa3ab" />
          </linearGradient>
          <clipPath id="schem-interior">
            <path d={path(outline) + " Z"} />
          </clipPath>
          <marker
            id="schem-arrow"
            viewBox="0 0 10 10"
            refX="9"
            refY="5"
            markerUnits="userSpaceOnUse"
            markerWidth={2.2 * k}
            markerHeight={2.2 * k}
            orient="auto-start-reverse"
          >
            <path d="M0,1 L10,5 L0,9 z" fill="#555" />
          </marker>
        </defs>

        {/* Drive: gearbox + motor above the top head */}
        <rect x={-R * 0.16} y={-(zRoof + driveH)} width={R * 0.32} height={driveH * 0.62} rx={k} fill="#5c6670" />
        <rect x={-R * 0.09} y={-(zRoof + driveH * 0.38)} width={R * 0.18} height={driveH * 0.38} fill="#8a939b" />

        {/* Wall: thick steel band behind a light interior */}
        <path d={path(outline) + " Z"} fill="none" stroke="url(#schem-steel)" strokeWidth={2 * wall} strokeLinejoin="round" />
        <path d={path(outline) + " Z"} fill="#fbfdff" stroke="#3a4148" strokeWidth={1.4} vectorEffect="non-scaling-stroke" />
        {data.glass_lined && (
          <path d={path(outline) + " Z"} fill="none" stroke="#4f86c6" strokeWidth={2.2} strokeOpacity={0.6} vectorEffect="non-scaling-stroke" />
        )}

        <g clipPath="url(#schem-interior)">
          {liquid}
          {level !== null && (
            <line x1={-R} x2={R} y1={-level} y2={-level} className={vortexLive ? "schem-static-level" : "schem-surface"} vectorEffect="non-scaling-stroke" />
          )}
          {vortexLive && (
            <polyline
              points={[...data.vortex!.r_mm].reverse().map((r, i) => `${-r},${-data.vortex!.z_mm[data.vortex!.z_mm.length - 1 - i]}`)
                .concat(data.vortex!.r_mm.map((r, i) => `${r},${-data.vortex!.z_mm[i]}`))
                .join(" ")}
              className="schem-surface"
              fill="none"
              vectorEffect="non-scaling-stroke"
            />
          )}
          {[data.V_min_L, data.V_max_L].map((v, i) =>
            v && v > 0 && v < data.total_L ? (
              <g key={i} className="schem-range">
                <line x1={-R} x2={R} y1={-zOf(v)} y2={-zOf(v)} vectorEffect="non-scaling-stroke" />
                <text x={-R + baffleW + 1.5 * k} y={-zOf(v) - 0.8 * k} fontSize={font * 0.8}>
                  {i ? "max" : "min"} {fmtL(v)} L
                </text>
              </g>
            ) : null,
          )}
        </g>

        {/* Baffles (side view: edge-on at the wall; a single glass-lined baffle as a rod) */}
        {data.baffles !== null && data.baffles > 0 && (
          <g className="schem-baffle">
            <title>{`${data.baffles} baffle${data.baffles > 1 ? "s" : ""}`}</title>
            {data.baffles === 1 ? (
              <rect x={R * 0.62} y={-H * 0.88} width={R * 0.1} height={H * 0.72} rx={R * 0.05} vectorEffect="non-scaling-stroke" />
            ) : (
              [-1, 1].map((s) => (
                <rect key={s} x={s > 0 ? R - data.D_mm / 12 : -R} y={-H * 0.97} width={data.D_mm / 12} height={H * 0.97} vectorEffect="non-scaling-stroke" />
              ))
            )}
          </g>
        )}

        {/* Shaft + impellers */}
        <rect x={-shaftW / 2} y={-(zRoof + driveH * 0.38)} width={shaftW} height={zRoof + driveH * 0.38 - lowest} fill="#6b737b" />
        {data.impellers.map((imp) => (
          <Impeller key={imp.index} imp={imp} k={k} spin={spin} />
        ))}

        {/* Graduated volume scale + fill pointer */}
        <g className="schem-scale">
          <line x1={gx} x2={gx} y1={-zBottom} y2={-H} vectorEffect="non-scaling-stroke" />
          {ticks.map((v) => {
            const y = -zOf(v);
            const nearPointer = level !== null && Math.abs(-level - y) < font * 0.9;
            return (
              <g key={v}>
                <line x1={gx} x2={gx - 2 * k} y1={y} y2={y} vectorEffect="non-scaling-stroke" />
                {!nearPointer && (
                  <text x={gx - 2.6 * k} y={y} dominantBaseline="middle" textAnchor="end">
                    {fmtL(v)}
                  </text>
                )}
              </g>
            );
          })}
          <text x={gx - 2.6 * k} y={-H - font * 0.6} textAnchor="end" className="schem-unit">
            L
          </text>
        </g>
        {level !== null && fillL !== null && (
          <g className="schem-pointer">
            <polygon points={`${gx},${-level} ${gx - 2.4 * k},${-level - 1.4 * k} ${gx - 2.4 * k},${-level + 1.4 * k}`} />
            <text x={gx - 3 * k} y={-level} dominantBaseline="middle" textAnchor="end">
              {fmtL(fillL)}
            </text>
          </g>
        )}

        {/* Hover read-out */}
        {hover !== null && !dragging && hoverV !== null && (
          <g className="schem-hover" pointerEvents="none">
            <line x1={-R} x2={R} y1={-hover} y2={-hover} vectorEffect="non-scaling-stroke" />
            <text x={-R + baffleW + 1.5 * k} y={-hover - 0.8 * k} fontSize={font * 0.85}>
              {fmtL(hoverV)} L · {hover.toFixed(0)} mm
            </text>
          </g>
        )}

        {/* Impeller labels */}
        {labels.map(({ imp, z }) => {
          const color = IMP_COLORS[(imp.index - 1) % IMP_COLORS.length];
          return (
            <g key={imp.index} className="schem-label" fill={imp.wall_hit ? "#C62828" : color}>
              <polyline
                points={`${imp.d_mm / 2},${-imp.cy_mm} ${R + wall + 1.5 * k},${-z} ${labelX - 0.6 * k},${-z}`}
                fill="none"
                stroke={color}
                strokeOpacity={0.6}
                vectorEffect="non-scaling-stroke"
              />
              <text x={labelX} y={-z} dominantBaseline="middle">
                {labelText(imp)}
              </text>
            </g>
          );
        })}

        {/* Dimensions */}
        <g className="schem-dim">
          <line x1={-R} x2={R} y1={-(zBottom - 3 * k)} y2={-(zBottom - 3 * k)} markerStart="url(#schem-arrow)" markerEnd="url(#schem-arrow)" vectorEffect="non-scaling-stroke" />
          <line x1={-R} x2={-R} y1={-(zBottom - 4 * k)} y2={0} className="schem-witness" vectorEffect="non-scaling-stroke" />
          <line x1={R} x2={R} y1={-(zBottom - 4 * k)} y2={0} className="schem-witness" vectorEffect="non-scaling-stroke" />
          <text x={0} y={-(zBottom - 3 * k) + font * 1.05} textAnchor="middle">
            ⌀ {data.D_mm.toFixed(0)} mm
          </text>
          <line x1={dimX} x2={dimX} y1={0} y2={-H} markerStart="url(#schem-arrow)" markerEnd="url(#schem-arrow)" vectorEffect="non-scaling-stroke" />
          <line x1={dimX - k} x2={gx} y1={0} y2={0} className="schem-witness" vectorEffect="non-scaling-stroke" />
          <line x1={dimX - k} x2={gx} y1={-H} y2={-H} className="schem-witness" vectorEffect="non-scaling-stroke" />
          <text x={dimX - 0.8 * k} y={-H / 2} textAnchor="middle" transform={`rotate(-90 ${dimX - 0.8 * k} ${-H / 2})`}>
            H {H.toFixed(0)} mm
          </text>
          {data.full_top_mm !== null && (
            <>
              <line x1={-R} x2={R} y1={-data.full_top_mm} y2={-data.full_top_mm} className="schem-full" vectorEffect="non-scaling-stroke" />
              <text x={R + wall + 1.5 * k} y={-data.full_top_mm} dominantBaseline="middle" className="schem-full-text">
                H full {(data.full_top_mm + data.bot_depth_mm).toFixed(0)} mm
              </text>
            </>
          )}
        </g>
      </svg>
      <figcaption className="schematic-legend">
        <span className="chip liquid">Liquid</span>
        {vortexLive && <span className="chip static">Level at rest</span>}
        {(data.V_min_L || data.V_max_L) && <span className="chip range">Working range</span>}
        {data.baffles ? <span className="chip baffle">Baffles ({data.baffles})</span> : null}
        <span className="muted">
          {data.bottom_label || "Bottom"} bottom · {data.top_label || "flat"} top
          {onFill ? " · drag inside the vessel to set the fill" : ""}
        </span>
      </figcaption>
    </figure>
  );
}
