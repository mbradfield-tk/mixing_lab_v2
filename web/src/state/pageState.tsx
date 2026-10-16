import {
  createContext, useCallback, useContext, useEffect, useRef, useState, type Dispatch, type ReactNode, type SetStateAction,
} from "react";

// Page state kept in memory for the browser session, so navigating away and back restores it.
const store = new Map<string, unknown>();

interface PageScope {
  page: string;
  reset: () => void;
}
const PageContext = createContext<PageScope | null>(null);

function clearPage(page: string) {
  for (const key of [...store.keys()]) if (key.startsWith(`${page}:`)) store.delete(key);
}

/** Scope for ``usePageState`` / ``usePageRef``; ``usePageReset`` clears it and remounts the page. */
export function PersistentPage({ page, children }: { page: string; children: ReactNode }) {
  const [epoch, setEpoch] = useState(0);
  const reset = useCallback(() => {
    clearPage(page);
    setEpoch((e) => e + 1);
  }, [page]);
  return (
    <PageContext.Provider value={{ page, reset }}>
      <PageBody key={epoch}>{children}</PageBody>
    </PageContext.Provider>
  );
}

const PageBody = ({ children }: { children: ReactNode }) => <>{children}</>;

function useId(key: string): string {
  const scope = useContext(PageContext);
  return scope ? `${scope.page}:${key}` : "";
}

/** ``useState`` whose value survives page navigation (within ``PersistentPage``). */
export function usePageState<T>(key: string, initial: T | (() => T)): [T, Dispatch<SetStateAction<T>>] {
  const id = useId(key);
  const [value, setValue] = useState<T>(() =>
    id && store.has(id) ? (store.get(id) as T) : typeof initial === "function" ? (initial as () => T)() : initial,
  );
  useEffect(() => {
    if (id) store.set(id, value);
  }, [id, value]);
  return [value, setValue];
}

/** ``useRef`` whose object survives page navigation (within ``PersistentPage``). */
export function usePageRef<T>(key: string, initial: T): { current: T } {
  const id = useId(key);
  const local = useRef(initial);
  if (!id) return local;
  if (!store.has(id)) store.set(id, { current: initial });
  return store.get(id) as { current: T };
}

/** Clears the page's saved state and remounts it with its defaults. */
export function usePageReset(): () => void {
  return useContext(PageContext)?.reset ?? (() => undefined);
}

// --- case files ----------------------------------------------------------------

export const CASE_APP = "Mixing Lab";
export const CASE_FORMAT = 1;

export interface CaseFile {
  app: typeof CASE_APP;
  format_version: number;
  page: string;
  exported_at: string;
  inputs: Record<string, unknown>;
  [extra: string]: unknown;
}

export function caseFile(page: string, inputs: object, extra: Record<string, unknown> = {}): CaseFile {
  return {
    app: CASE_APP,
    format_version: CASE_FORMAT,
    page,
    exported_at: new Date().toISOString(),
    inputs: { ...inputs },
    ...extra,
  };
}

/** The case file in ``text`` for ``page``, or an error message. */
export function parseCaseFile(text: string, page: string): { file: CaseFile } | { error: string } {
  let data: unknown;
  try {
    data = JSON.parse(text);
  } catch {
    return { error: "Not a valid case file (JSON could not be read)." };
  }
  const d = data as Partial<CaseFile>;
  if (!d || typeof d !== "object" || d.app !== CASE_APP || typeof d.inputs !== "object" || !d.inputs)
    return { error: "Not a Mixing Lab case file." };
  if (d.page !== page) return { error: `This case file is for the "${d.page}" page, not "${page}".` };
  return { file: d as CaseFile };
}

/** ``defaults`` overlaid with the fields of ``raw`` that exist in ``defaults`` with the same type. */
export function mergeKnown<T extends object>(defaults: T, raw: unknown): T {
  const out = { ...defaults } as Record<string, unknown>;
  if (!raw || typeof raw !== "object") return out as T;
  for (const [k, v] of Object.entries(raw as Record<string, unknown>)) {
    if (!(k in out)) continue;
    const d = out[k];
    const sameType =
      Array.isArray(d) ? Array.isArray(v) : d === null || v === null ? true : typeof d === typeof v;
    if (sameType) out[k] = v;
  }
  return out as T;
}
