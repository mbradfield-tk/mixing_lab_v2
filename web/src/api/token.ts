/** The admin bearer token, kept in memory only (a reload locks editing again). */
let token: string | null = null;
let expiresAt = 0;
const listeners = new Set<() => void>();

function emit() {
  listeners.forEach((l) => l());
}

export function getToken(): string | null {
  if (token && Date.now() >= expiresAt) clearToken();
  return token;
}

export function setToken(value: string, expiresInS: number) {
  token = value;
  // Treat the token as expired a minute early so a write never races the server's TTL.
  expiresAt = Date.now() + Math.max(0, expiresInS - 60) * 1000;
  emit();
}

export function clearToken() {
  if (token === null) return;
  token = null;
  expiresAt = 0;
  emit();
}

export function subscribeToken(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}
