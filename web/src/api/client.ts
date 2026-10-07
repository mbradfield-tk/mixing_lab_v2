import createClient from "openapi-fetch";
import type { components, paths } from "./schema";
import { clearToken, getToken } from "./token";

/** Typed client for the FastAPI back end; paths and bodies come from api/openapi.json. */
export const api = createClient<paths>({ baseUrl: "" });

api.use({
  onRequest({ request }) {
    const token = getToken();
    if (token) request.headers.set("Authorization", `Bearer ${token}`);
    return request;
  },
  onResponse({ response }) {
    if (response.status === 401) clearToken(); // expired / revoked: lock editing again
    return response;
  },
});

export type Schemas = components["schemas"];

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
  ) {
    super(message);
  }
}

type FetchResult<T> = { data?: T; error?: unknown; response: Response };

function errorMessage(body: unknown, response: Response): string {
  const detail = (body as { detail?: unknown } | undefined)?.detail;
  return typeof detail === "string"
    ? detail
    : Array.isArray(detail)
      ? detail.map((d: { msg?: string }) => d.msg ?? String(d)).join("; ")
      : response.statusText || `HTTP ${response.status}`;
}

/** Return the response body (undefined for 204), or throw an ApiError carrying the server's `detail`. */
export function unwrap<T>(res: FetchResult<T>): T {
  if (res.response.ok) return res.data as T;
  throw new ApiError(res.response.status, errorMessage(res.error, res.response));
}

/** POST JSON and receive a file (e.g. a PDF report): the blob plus the server's filename. */
export async function postForFile(url: string, body: unknown): Promise<{ blob: Blob; filename: string }> {
  const token = getToken();
  const response = await fetch(url, {
    method: "POST",
    body: JSON.stringify(body),
    headers: { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}) },
  });
  if (!response.ok) {
    const err: unknown = await response.json().catch(() => undefined);
    throw new ApiError(response.status, errorMessage(err, response));
  }
  const disposition = response.headers.get("Content-Disposition") ?? "";
  const filename = /filename="?([^"]+)"?/.exec(disposition)?.[1] ?? "report.pdf";
  return { blob: await response.blob(), filename };
}

/** Multipart upload of one file (e.g. `PUT /particles/import`) plus form fields, with the admin token. */
export async function uploadFile<T>(
  url: string,
  file: File,
  method = "PUT",
  fields: Record<string, string> = {},
): Promise<T> {
  const form = new FormData();
  form.append("file", file);
  for (const [key, value] of Object.entries(fields)) form.append(key, value);
  const token = getToken();
  const response = await fetch(url, {
    method,
    body: form,
    headers: token ? { Authorization: `Bearer ${token}` } : undefined,
  });
  const body: unknown = await response.json().catch(() => undefined);
  if (response.status === 401) clearToken();
  if (!response.ok) throw new ApiError(response.status, errorMessage(body, response));
  return body as T;
}
