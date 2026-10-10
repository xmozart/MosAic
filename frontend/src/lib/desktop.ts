declare global {
  interface Window {
    /** Injected by the desktop shell into its own webview only (ADR 0057). */
    __MOSAIC_DESKTOP__?: { token?: string };
    /** Tauri's API in the desktop shell's own webview (withGlobalTauri; ADR 0060). */
    __TAURI__?: { dialog?: { open: (o: { directory: boolean; multiple: boolean; title?: string }) => Promise<string | string[] | null> } };
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

/** The desktop shell's native folder picker is here (only inside the Mac app). */
export function hasNativeFolderPicker(): boolean {
  return typeof window !== "undefined" && typeof window.__TAURI__?.dialog?.open === "function";
}

/** The folder the user picked in the native dialog, or null when they cancelled. */
export async function nativeFolder(title: string): Promise<string | null> {
  const picked = await window.__TAURI__!.dialog!.open({ directory: true, multiple: false, title });
  return typeof picked === "string" ? picked : null;
}
