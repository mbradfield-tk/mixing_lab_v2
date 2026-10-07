import { useCallback, useState } from "react";

export interface Notice {
  kind: "success" | "error" | "info";
  text: string;
}

/** Page-level toast; `run` reports a promise's success or failure and re-throws errors. */
export function useNotice() {
  const [notice, setNotice] = useState<Notice | null>(null);
  const run = useCallback(
    async <T,>(promise: Promise<T>, ok: string | ((result: T) => string)): Promise<T> => {
      try {
        const result = await promise;
        setNotice({ kind: "success", text: typeof ok === "function" ? ok(result) : ok });
        return result;
      } catch (err) {
        setNotice({ kind: "error", text: err instanceof Error ? err.message : String(err) });
        throw err;
      }
    },
    [],
  );
  return { notice, setNotice, run };
}

export function NoticeBar({ notice, onClose }: { notice: Notice | null; onClose: () => void }) {
  if (!notice) return null;
  return (
    <div className={`notice notice-${notice.kind}`} role={notice.kind === "error" ? "alert" : "status"}>
      <span>{notice.text}</span>
      <button type="button" className="icon-btn" aria-label="Dismiss" onClick={onClose}>
        ×
      </button>
    </div>
  );
}
