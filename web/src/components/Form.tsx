import type { ReactNode } from "react";

/** Labelled number input that keeps the typed text (parsed by the caller). */
export function NumberField({
  label,
  value,
  onChange,
  step = "any",
  min,
}: {
  label: ReactNode;
  value: string;
  onChange: (value: string) => void;
  step?: string;
  min?: number;
}) {
  return (
    <label>
      {label}
      <input type="number" step={step} min={min} value={value} onChange={(e) => onChange(e.target.value)} />
    </label>
  );
}

export function SelectField({
  label,
  value,
  onChange,
  options,
}: {
  label: ReactNode;
  value: string;
  onChange: (value: string) => void;
  options: (string | { code: string; label: string })[];
}) {
  return (
    <label>
      {label}
      <select value={value} onChange={(e) => onChange(e.target.value)}>
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
    </label>
  );
}

/** On/off switch (the Taipy "Off | On" toggle). */
export function Switch({ label, checked, onChange }: { label: ReactNode; checked: boolean; onChange: (on: boolean) => void }) {
  return (
    <label className="switch">
      <input type="checkbox" role="switch" checked={checked} onChange={(e) => onChange(e.target.checked)} />
      <span>{label}</span>
    </label>
  );
}

/** Number input paired with a range slider over [min, max]; typed values may leave the range. */
export function SliderField({
  label,
  value,
  onChange,
  min,
  max,
  step,
  unit = "",
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  min: number;
  max: number;
  step: number;
  unit?: string;
}) {
  const x = Number(value);
  const inRange = value.trim() !== "" && Number.isFinite(x) && x >= min && x <= max;
  const decimals = Math.max(0, -Math.floor(Math.log10(step)));
  const fmt = (v: number) => String(Number(v.toPrecision(4)));
  return (
    <div className="slider-field">
      <label>
        {label}
        <input type="number" step="any" value={value} onChange={(e) => onChange(e.target.value)} />
      </label>
      <input
        type="range"
        aria-label={`${label} slider`}
        min={min}
        max={max}
        step={step}
        value={Number.isFinite(x) ? Math.min(Math.max(x, min), max) : min}
        onChange={(e) => onChange(String(Number(Number(e.target.value).toFixed(decimals))))}
      />
      <div className="slider-scale">
        <span>
          {fmt(min)} {unit}
        </span>
        {!inRange && value.trim() !== "" && <span className="slider-out">outside vessel range</span>}
        <span>
          {fmt(max)} {unit}
        </span>
      </div>
    </div>
  );
}

/** Segmented choice between a few coded options. */
export function Segmented({
  label,
  value,
  onChange,
  options,
}: {
  label: ReactNode;
  value: string;
  onChange: (value: string) => void;
  options: { code: string; label: string }[];
}) {
  return (
    <div className="segmented-field">
      <span className="ms-label">{label}</span>
      <div className="segmented" role="radiogroup">
        {options.map((o) => (
          <button
            key={o.code}
            type="button"
            role="radio"
            aria-checked={value === o.code}
            className={value === o.code ? "active" : ""}
            onClick={() => onChange(o.code)}
          >
            {o.label}
          </button>
        ))}
      </div>
    </div>
  );
}
