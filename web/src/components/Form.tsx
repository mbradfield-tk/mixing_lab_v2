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
