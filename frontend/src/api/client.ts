import createClient, { type Middleware } from "openapi-fetch";

import type { paths } from "./schema";

const MUTATING = new Set(["POST", "PUT", "PATCH", "DELETE"]);

/** The page reads the CSRF cookie and echoes it on writes (double submit, ADR 0034). */
export function csrfToken(cookie: string = document.cookie): string | undefined {
  const m = /(?:^|;\s*)mosaic_csrf=([^;]+)/.exec(cookie);
  return m?.[1] ? decodeURIComponent(m[1]) : undefined;
}

const csrf: Middleware = {
  onRequest({ request }) {
    if (MUTATING.has(request.method)) {
      const token = csrfToken();
      if (token) request.headers.set("X-CSRF-Token", token);
    }
    return request;
  },
};

/** Called when the server says the session ended (401), so the app shows sign-in. */
export const onSignedOut = { handler: () => {} };

const signedOut: Middleware = {
  onResponse({ response, request }) {
    if (response.status === 401 && !new URL(request.url).pathname.startsWith("/api/auth/")) {
      onSignedOut.handler();
    }
    return response;
  },
};

/** The typed API client, generated from the backend's OpenAPI document (`npm run api`). */
export const api = createClient<paths>({
  baseUrl: typeof window === "undefined" ? "" : window.location.origin,
  credentials: "same-origin",
});
api.use(csrf, signedOut);

export type { paths };
