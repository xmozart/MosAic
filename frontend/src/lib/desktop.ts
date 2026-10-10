declare global {
  interface Window {
    /** Injected by the desktop shell into its own webview only (ADR 0057). */
    __MOSAIC_DESKTOP__?: { token?: string };
  }
}

/** Trades the shell's token for an HttpOnly session cookie, then forgets the token. */
export async function startDesktopSession(): Promise<boolean> {
  const token = window.__MOSAIC_DESKTOP__?.token;
  if (!token) return false;
  delete window.__MOSAIC_DESKTOP__!.token;
  const r = await fetch("/api/auth/desktop-session", { method: "POST", headers: { Authorization: `Bearer ${token}` }, credentials: "same-origin" });
  return r.ok;
}
