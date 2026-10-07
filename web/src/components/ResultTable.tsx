import type { Row } from "../api/tables";
import { downloadBlob, toCsv } from "../pages/assessment/model";

/** Pre-formatted result rows (server strings) with an optional CSV download. */
export function ResultTable({ rows, csvName, stale = false }: { rows: Row[]; csvName?: string; stale?: boolean }) {
  const cols = Object.keys(rows[0] ?? {});
  return (
    <>
      <div className="table-scroll">
        <table className="results">
          <thead>
            <tr>
              {cols.map((c) => (
                <th key={c}>{c}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={i}>
                {cols.map((c) => (
                  <td key={c}>{r[c] === null || r[c] === undefined ? "—" : String(r[c])}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {csvName && !stale && (
        <button
          type="button"
          className="link-btn"
          onClick={() => downloadBlob(new Blob([toCsv(rows)], { type: "text/csv" }), csvName)}
        >
          Download CSV
        </button>
      )}
    </>
  );
}
