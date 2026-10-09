import {
  Children, Fragment, isValidElement, useEffect, useRef, useState, type CSSProperties, type KeyboardEvent, type PointerEvent,
  type ReactElement, type ReactNode,
} from "react";

/** Arc of the knob scale, in degrees clockwise from 12 o'clock. */
const SWEEP = 270;
const START = -SWEEP / 2;

const decimalsOf = (step: number) => Math.max(0, -Math.floor(Math.log10(step)));
const show = (v: number) => String(Number(v.toPrecision(4)));

export function clamp(x: number, min: number, max: number): number {
  return Math.min(Math.max(x, min), max);
}

/** Round to the step grid, then clamp to the range, as text. */
export function snap(x: number, min: number, max: number, step: number): string {
  const v = Number((Math.round(x / step) * step).toFixed(decimalsOf(step)));
  return String(clamp(v, min, max));
}

/** Flatten fragments so each control can be placed individually. */
function flatten(children: ReactNode): ReactElement[] {
  return Children.toArray(children).flatMap((c) =>
    isValidElement<{ children?: ReactNode }>(c) && c.type === Fragment ? flatten(c.props.children) : isValidElement(c) ? [c] : [],
  );
}

/** Bezel grouping instrument controls, like the front panel of a lab device: knobs on the left, the rest flowing beside. */
export function InstrumentPanel({ title, children }: { title?: ReactNode; children: ReactNode }) {
  const items = flatten(children);
  const knobs = items.filter((c) => c.type === Knob);
  const rest = items.filter((c) => c.type !== Knob);
  return (
    <section className="instrument-panel">
      {title && <div className="instrument-title">{title}</div>}
      <div className="instrument-controls">
        {knobs.length > 0 && <div className="instrument-knobs">{knobs}</div>}
        {rest.length > 0 && <div className="instrument-rest">{rest}</div>}
      </div>
    </section>
  );
}

/** Digital readout: free typing, committed (and clamped by the caller) on blur / Enter. */
function Readout({
  label,
  value,
  unit,
  onCommit,
  onStep,
}: {
  label: string;
  value: string;
  unit: string;
  onCommit: (text: string) => void;
  onStep: (dir: 1 | -1) => void;
}) {
  const [draft, setDraft] = useState<string | null>(null);
  const commit = () => {
    if (draft !== null) onCommit(draft);
    setDraft(null);
  };
  return (
    <div className="lcd-row">
      <button type="button" className="lcd-step" aria-label={`Decrease ${label}`} onClick={() => onStep(-1)}>
        −
      </button>
      <span className="lcd">
        <input
          type="number"
          step="any"
          aria-label={label}
          value={draft ?? value}
          onChange={(e) => setDraft(e.target.value)}
          onBlur={commit}
          onKeyDown={(e) => {
            if (e.key === "Enter") (e.target as HTMLInputElement).blur();
            if (e.key === "Escape") setDraft(null);
          }}
        />
        <span className="lcd-unit">{unit}</span>
      </span>
      <button type="button" className="lcd-step" aria-label={`Increase ${label}`} onClick={() => onStep(1)}>
        +
      </button>
    </div>
  );
}

interface RangeProps {
  label: string;
  value: string;
  onChange: (value: string) => void;
  min: number;
  max: number;
  step: number;
  unit?: string;
}

/** Shared range logic: the value always stays within [min, max]. */
function useRange({ value, onChange, min, max, step }: RangeProps) {
  const x = Number(value);
  const valid = value.trim() !== "" && Number.isFinite(x);
  const current = valid ? clamp(x, min, max) : min;
  useEffect(() => {
    if (valid && (x < min || x > max)) onChange(String(clamp(x, min, max)));
  }, [valid, x, min, max, onChange]);
  const set = (v: number) => onChange(snap(v, min, max, step));
  const commit = (text: string) => {
    const t = Number(text);
    if (text.trim() !== "" && Number.isFinite(t)) onChange(String(clamp(t, min, max)));
  };
  const keys = (e: KeyboardEvent) => {
    const big = Math.max(step, (max - min) / 10);
    const moves: Record<string, number> = {
      ArrowUp: step, ArrowRight: step, ArrowDown: -step, ArrowLeft: -step, PageUp: big, PageDown: -big,
    };
    if (e.key in moves) set(current + moves[e.key]);
    else if (e.key === "Home") set(min);
    else if (e.key === "End") set(max);
    else return;
    e.preventDefault();
  };
  return { current, set, commit, keys, display: valid ? show(current) : value };
}

const polar = (r: number, deg: number): [number, number] => {
  const a = ((deg - 90) * Math.PI) / 180;
  return [60 + r * Math.cos(a), 60 + r * Math.sin(a)];
};

function arc(r: number, from: number, to: number): string {
  const [x0, y0] = polar(r, from);
  const [x1, y1] = polar(r, to);
  return `M ${x0} ${y0} A ${r} ${r} 0 ${to - from > 180 ? 1 : 0} 1 ${x1} ${y1}`;
}

/** Rotary knob (e.g. stirrer speed): drag or use the arrow keys; digital readout below. */
export function Knob(props: RangeProps) {
  const { label, min, max, step, unit = "" } = props;
  const r = useRange(props);
  const svg = useRef<SVGSVGElement>(null);
  const frac = max > min ? (r.current - min) / (max - min) : 0;
  const angle = START + frac * SWEEP;

  function fromPointer(e: PointerEvent) {
    const box = svg.current!.getBoundingClientRect();
    const dx = e.clientX - (box.left + box.width / 2);
    const dy = e.clientY - (box.top + box.height / 2);
    let deg = (Math.atan2(dx, -dy) * 180) / Math.PI;
    // Dead zone at the bottom: snap to the nearer end stop.
    if (Math.abs(deg) > -START) deg = deg > 0 ? -START : START;
    r.set(min + ((deg - START) / SWEEP) * (max - min));
  }

  return (
    <div className="instrument knob-control">
      <div className="instrument-label">{label}</div>
      <svg
        ref={svg}
        className="knob"
        viewBox="0 0 120 120"
        role="slider"
        tabIndex={0}
        aria-label={label}
        aria-valuemin={min}
        aria-valuemax={max}
        aria-valuenow={r.current}
        aria-valuetext={`${show(r.current)} ${unit}`}
        onKeyDown={r.keys}
        onPointerDown={(e) => {
          e.currentTarget.setPointerCapture(e.pointerId);
          fromPointer(e);
        }}
        onPointerMove={(e) => {
          if (e.currentTarget.hasPointerCapture(e.pointerId)) fromPointer(e);
        }}
      >
        {Array.from({ length: 11 }, (_, i) => {
          const deg = START + (i * SWEEP) / 10;
          const [x0, y0] = polar(i % 5 === 0 ? 47 : 49, deg);
          const [x1, y1] = polar(55, deg);
          return <line key={i} className="knob-tick" x1={x0} y1={y0} x2={x1} y2={y1} />;
        })}
        <path className="knob-track" d={arc(42, START, -START)} />
        {frac > 0 && <path className="knob-level" d={arc(42, START, angle)} />}
        <circle className="knob-cap" cx="60" cy="60" r="33" />
        <circle className="knob-grip" cx="60" cy="60" r="27" />
        <line className="knob-pointer" x1={polar(12, angle)[0]} y1={polar(12, angle)[1]} x2={polar(26, angle)[0]} y2={polar(26, angle)[1]} />
      </svg>
      <div className="knob-scale">
        <span>{show(min)}</span>
        <span>{show(max)}</span>
      </div>
      <Readout label={label} value={r.display} unit={unit} onCommit={r.commit} onStep={(d) => r.set(r.current + d * step)} />
    </div>
  );
}

/** Linear fader with a graduated scale (e.g. fill volume); digital readout below. */
export function Fader(props: RangeProps) {
  const { label, min, max, step, unit = "" } = props;
  const r = useRange(props);
  const pct = max > min ? ((r.current - min) / (max - min)) * 100 : 0;
  return (
    <div className="instrument fader-control">
      <div className="instrument-label">{label}</div>
      <div className="fader" style={{ "--level": `${pct}%` } as CSSProperties}>
        <input
          type="range"
          aria-label={label}
          min={min}
          max={max}
          step={step}
          value={r.current}
          onKeyDown={r.keys}
          onChange={(e) => r.set(Number(e.target.value))}
        />
        <div className="fader-ticks" aria-hidden />
      </div>
      <div className="knob-scale">
        <span>
          {show(min)} {unit}
        </span>
        <span>
          {show(max)} {unit}
        </span>
      </div>
      <Readout label={label} value={r.display} unit={unit} onCommit={r.commit} onStep={(d) => r.set(r.current + d * step)} />
    </div>
  );
}

/** Numeric set-point box (e.g. temperature) with a digital look and ± step buttons. */
export function Setpoint({
  label,
  value,
  onChange,
  unit = "",
  step = 1,
  min,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  unit?: string;
  step?: number;
  min?: number;
}) {
  const bump = (d: 1 | -1) => {
    const x = Number(value);
    const next = Number(((Number.isFinite(x) ? x : 0) + d * step).toFixed(decimalsOf(step)));
    onChange(String(min === undefined ? next : Math.max(next, min)));
  };
  return (
    <div className="instrument setpoint-control">
      <div className="instrument-label">{label}</div>
      <div className="lcd-row">
        <button type="button" className="lcd-step" aria-label={`Decrease ${label}`} onClick={() => bump(-1)}>
          −
        </button>
        <span className="lcd">
          <input
            type="number"
            step="any"
            min={min}
            aria-label={label}
            value={value}
            onChange={(e) => onChange(e.target.value)}
          />
          <span className="lcd-unit">{unit}</span>
        </span>
        <button type="button" className="lcd-step" aria-label={`Increase ${label}`} onClick={() => bump(1)}>
          +
        </button>
      </div>
    </div>
  );
}

/** Mode selector with the digital-display look (e.g. coolant / heat-transfer fluid). */
export function Selector({
  label,
  value,
  onChange,
  options,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  options: (string | { code: string; label: string })[];
}) {
  return (
    <div className="instrument selector-control">
      <div className="instrument-label">{label}</div>
      <span className="lcd lcd-select">
        <select aria-label={label} value={value} onChange={(e) => onChange(e.target.value)}>
          {options.map((o) =>
            typeof o === "string" ? (
              <option key={o}>{o}</option>
            ) : (
              <option key={o.code} value={o.code}>
                {o.label}
              </option>
            ),
          )}
        </select>
      </span>
    </div>
  );
}
