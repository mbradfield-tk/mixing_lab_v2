import { useEffect, useRef, useState } from "react";

/** Compact multi-select: a button that opens a checkbox list. */
export function MultiSelect({
  label,
  options,
  value,
  onChange,
  placeholder = "All",
}: {
  label: string;
  options: string[];
  value: string[];
  onChange: (value: string[]) => void;
  placeholder?: string;
}) {
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => {
      if (!box.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [open]);

  const toggle = (option: string) =>
    onChange(value.includes(option) ? value.filter((v) => v !== option) : [...value, option]);

  const summary = value.length === 0 ? placeholder : value.length <= 2 ? value.join(", ") : `${value.length} selected`;

  return (
    <div className="multi-select" ref={box}>
      <span className="ms-label">{label}</span>
      <button type="button" aria-haspopup="listbox" aria-expanded={open} onClick={() => setOpen(!open)}>
        <span className="ms-summary">{summary}</span> ▾
      </button>
      {open && (
        <div className="ms-menu" role="listbox" aria-multiselectable aria-label={label}>
          <div className="ms-actions">
            <button type="button" onClick={() => onChange(options)}>
              All
            </button>
            <button type="button" onClick={() => onChange([])}>
              None
            </button>
          </div>
          {options.map((o) => (
            <label key={o} className="ms-option">
              <input type="checkbox" checked={value.includes(o)} onChange={() => toggle(o)} />
              {o}
            </label>
          ))}
        </div>
      )}
    </div>
  );
}
