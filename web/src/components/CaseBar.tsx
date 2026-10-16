import { useRef, useState } from "react";
import { caseFile, parseCaseFile, usePageReset, type CaseFile } from "../state/pageState";

function download(text: string, filename: string) {
  const url = URL.createObjectURL(new Blob([text], { type: "application/json" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

const slug = (s: string) => s.replace(/[^\w.-]+/g, "_").replace(/^_+|_+$/g, "");

/** Export / import of the page inputs as a JSON case file, and a full page reset. */
export function CaseBar({
  page,
  label,
  inputs,
  extra,
  onImport,
  onMessage,
}: {
  page: string;
  /** Short case description for the file name (e.g. the vessel). */
  label?: string;
  inputs: object;
  extra?: Record<string, unknown>;
  onImport?: (file: CaseFile) => void | Promise<void>;
  onMessage: (m: { kind: "success" | "error" | "info"; text: string }) => void;
}) {
  const reset = usePageReset();
  const fileInput = useRef<HTMLInputElement>(null);
  const [confirm, setConfirm] = useState(false);

  function onExport() {
    const date = new Date().toISOString().slice(0, 10);
    const name = [page, label ? slug(label) : "", date].filter(Boolean).join("_");
    download(JSON.stringify(caseFile(page, inputs, extra), null, 2), `${name}.json`);
    onMessage({ kind: "success", text: "Inputs exported as a case file." });
  }

  async function onFile(file: File) {
    const parsed = parseCaseFile(await file.text(), page);
    if ("error" in parsed) {
      onMessage({ kind: "error", text: parsed.error });
      return;
    }
    try {
      await onImport?.(parsed.file);
      onMessage({ kind: "success", text: `Inputs loaded from ${file.name}.` });
    } catch (e) {
      onMessage({ kind: "error", text: `Import failed: ${(e as Error).message}` });
    }
  }

  return (
    <div className="case-bar">
      {onImport && (
        <>
          <button type="button" onClick={onExport} title="Download all inputs on this page as a JSON case file">
            Export inputs
          </button>
          <button type="button" onClick={() => fileInput.current?.click()} title="Load inputs from a case file">
            Import inputs
          </button>
          <input
            ref={fileInput}
            type="file"
            accept=".json,application/json"
            hidden
            onChange={(e) => {
              const f = e.target.files?.[0];
              e.target.value = "";
              if (f) void onFile(f);
            }}
          />
        </>
      )}
      {confirm ? (
        <span className="case-confirm">
          Reset all inputs and results on this page?{" "}
          <button type="button" className="danger" onClick={reset}>
            Reset
          </button>{" "}
          <button type="button" onClick={() => setConfirm(false)}>
            Cancel
          </button>
        </span>
      ) : (
        <button type="button" onClick={() => setConfirm(true)} title="Clear all inputs and results on this page">
          Reset page
        </button>
      )}
    </div>
  );
}
