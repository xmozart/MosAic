// Regenerates the shipped npm package table in ../LICENSES.md (between the
// npm-packages markers) from `npm ls --omit=dev --all`. src/test/licenses.test.ts fails
// when a shipped package is missing or its license is not allowed.
import { spawnSync } from "node:child_process";
import { readFileSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const file = resolve(root, "../LICENSES.md");
const BEGIN = "<!-- BEGIN npm-packages -->";
const END = "<!-- END npm-packages -->";
const SKIP = new Set(["@napi-rs/wasm-runtime", "@tybys/wasm-util"]); // build tools' wasm fallbacks

export function shipped() {
  const json = spawnSync("npm", ["ls", "--omit=dev", "--all", "--json", "--long"], {
    cwd: root,
    encoding: "utf8",
    maxBuffer: 64 * 1024 * 1024,
  }).stdout;
  const out = new Map();
  const walk = (tree) => {
    for (const [name, dep] of Object.entries(tree.dependencies ?? {})) {
      if (!dep.path || out.has(name) || (dep.extraneous && SKIP.has(name))) continue;
      const pkg = JSON.parse(readFileSync(join(dep.path, "package.json"), "utf8"));
      const license = typeof pkg.license === "string" ? pkg.license : (pkg.license?.type ?? "");
      out.set(name, { version: pkg.version, license });
      walk(dep);
    }
  };
  walk(JSON.parse(json));
  return [...out.entries()].sort(([a], [b]) => a.localeCompare(b));
}

function main() {
  const rows = shipped().map(([n, p]) => `| ${n} | ${p.version} | ${p.license} |`);
  const table = [BEGIN, "| Package | Version | License |", "|---|---|---|", ...rows, END].join("\n");
  const text = readFileSync(file, "utf8");
  const i = text.indexOf(BEGIN);
  const j = text.indexOf(END);
  if (i < 0 || j < 0) throw new Error("LICENSES.md has no npm-packages markers");
  writeFileSync(file, text.slice(0, i) + table + text.slice(j + END.length));
}

if (process.argv[1] === fileURLToPath(import.meta.url)) main();
