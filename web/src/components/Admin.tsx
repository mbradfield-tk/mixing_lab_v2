import { useState, useSyncExternalStore, type FormEvent } from "react";
import { api, ApiError, unwrap } from "../api/client";
import { clearToken, getToken, setToken, subscribeToken } from "../api/token";
import { Card } from "./ui";

/** True while an unexpired admin token is held (shared by every page). */
export function useIsAdmin(): boolean {
  return useSyncExternalStore(subscribeToken, () => getToken() !== null);
}

export async function login(username: string, password: string): Promise<void> {
  const res = unwrap(await api.POST("/api/v1/auth/login", { body: { username, password } }));
  setToken(res.access_token, res.expires_in_s);
}

/** Unlock / lock panel, as on the Taipy database pages. */
export function AdminPanel() {
  const isAdmin = useIsAdmin();
  const [user, setUser] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function unlock(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await login(user, password);
      setPassword("");
    } catch (err) {
      setError(
        err instanceof ApiError && err.status === 401
          ? "❌ Invalid credentials. Editing remains locked."
          : `🔒 ${err instanceof Error ? err.message : String(err)}`,
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card title="Admin">
      {isAdmin ? (
        <>
          <p>🔓 Editing unlocked. Changes save automatically to the database.</p>
          <button type="button" onClick={() => clearToken()}>
            Lock editing
          </button>
        </>
      ) : (
        <form onSubmit={unlock}>
          <p>{error ?? "🔒 Editing is locked. Unlock with admin credentials to modify the database."}</p>
          <div className="form-row admin-row">
            <label>
              Admin username
              <input value={user} onChange={(e) => setUser(e.target.value)} autoComplete="username" />
            </label>
            <label>
              Admin password
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete="current-password"
              />
            </label>
            <button type="submit" disabled={busy || !user || !password}>
              Unlock editing
            </button>
          </div>
        </form>
      )}
    </Card>
  );
}
