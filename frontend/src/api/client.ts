import createClient from "openapi-fetch";

import type { paths } from "./schema";

/** The typed API client, generated from the backend's OpenAPI document (`npm run api`). */
export const api = createClient<paths>({ baseUrl: "", credentials: "same-origin" });

export type { paths };
