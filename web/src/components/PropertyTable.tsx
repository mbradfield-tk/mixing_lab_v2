import type { ReactNode } from "react";

export interface PropertyRow {
  label: ReactNode;
  unit?: string;
  value: string;
  onChange?: (value: string) => void;
  /** Choice list for a dropdown cell; omit for a numeric cell. */
  options?: (string | { code: string; label: string })[];
  /** Free-text cell instead of a numeric one. */
  text?: boolean;
  hidden?: boolean;
  disabled?: boolean;
  /** Calculated value shown but not editable. */
  readOnly?: boolean;
}

export interface PropertyGroup {
  title: string;
  rows: PropertyRow[];
}

/** Compact editable parameter sheet: one group header row, then Parameter | Value | Unit rows. */
export function PropertyTable({ groups }: { groups: PropertyGroup[] }) {
  return (
    <table className="prop-table">
      <colgroup>
        <col className="prop-label" />
        <col className="prop-value" />
        <col className="prop-unit" />
      </colgroup>
      {groups.map((g) => (
        <tbody key={g.title}>
          <tr className="prop-group">
            <th colSpan={3} scope="colgroup">
              {g.title}
            </th>
          </tr>
          {g.rows.map((r, i) => {
            if (r.hidden) return null;
            const name = `${g.title} ${typeof r.label === "string" ? r.label : i}`;
            return (
              <tr key={i}>
                <th scope="row">{r.label}</th>
                <td>
                  {r.options ? (
                    <select aria-label={name} value={r.value} disabled={r.disabled} onChange={(e) => r.onChange?.(e.target.value)}>
                      {r.options.map((o) =>
                        typeof o === "string" ? (
                          <option key={o}>{o}</option>
                        ) : (
                          <option key={o.code} value={o.code}>
                            {o.label}
                          </option>
                        ),
                      )}
                    </select>
                  ) : (
                    <input
                      aria-label={name}
                      className={[r.text ? "prop-text" : "", r.readOnly ? "computed" : ""].join(" ").trim() || undefined}
                      type={r.text || r.readOnly ? "text" : "number"}
                      step={r.text || r.readOnly ? undefined : "any"}
                      value={r.value}
                      readOnly={r.readOnly}
                      disabled={r.disabled}
                      onChange={(e) => r.onChange?.(e.target.value)}
                    />
                  )}
                </td>
                <td className="muted">{r.unit}</td>
              </tr>
            );
          })}
        </tbody>
      ))}
    </table>
  );
}
