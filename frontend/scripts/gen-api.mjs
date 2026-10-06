// Regenerates the typed API client inputs (M2 acceptance 9):
//   src/api/openapi.json  ← the FastAPI app's OpenAPI document
//   src/api/schema.d.ts   ← openapi-typescript types used by openapi-fetch
import { execFileSync } from "node:child_process";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const json = resolve(root, "src/api/openapi.json");
execFileSync("uv", ["run", "python", "-m", "mosaic.app.openapi_export", json], {
  cwd: resolve(root, ".."),
  stdio: "inherit",
});
execFileSync("npx", ["openapi-typescript", json, "-o", resolve(root, "src/api/schema.d.ts")], {
  cwd: root,
  stdio: "inherit",
});
