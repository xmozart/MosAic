// Every package shipped in the web UI bundle has an allowed license (CLAUDE.md:
// dependency licensing). Dev-only tools are not shipped and are not checked here.
import { spawnSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { join } from "node:path";

const ALLOWED = /^(MIT|ISC|BSD-[23]-Clause|Apache-2\.0|0BSD|MPL-2\.0|Unlicense|CC0-1\.0|SIL OPEN FONT LICENSE|OFL-1\.1)$/;

const BUILD_ONLY_EXTRANEOUS = new Set(["@napi-rs/wasm-runtime", "@tybys/wasm-util"]);
const LICENSES_MD = readFileSync(join(__dirname, "../../../LICENSES.md"), "utf8");

interface Tree {
  dependencies?: Record<string, Tree & { path?: string; extraneous?: boolean }>;
}

function walk(tree: Tree, out: Map<string, string>): void {
  for (const [name, dep] of Object.entries(tree.dependencies ?? {})) {
    if (!dep.path || out.has(dep.path)) continue;
    // Extraneous: left in node_modules by an optional build tool's wasm fallback. Only the
    // known ones are skipped; anything else extraneous is checked like a shipped package.
    if (dep.extraneous && BUILD_ONLY_EXTRANEOUS.has(name)) continue;
    const pkg = JSON.parse(readFileSync(join(dep.path, "package.json"), "utf8")) as {
      license?: string | { type?: string };
    };
    const license = typeof pkg.license === "string" ? pkg.license : (pkg.license?.type ?? "");
    out.set(dep.path, `${name}|${license}`);
    walk(dep, out);
  }
}

describe("shipped dependency licenses", () => {
  it("are permissive or font licenses", () => {
    // npm exits non-zero for tree problems (extraneous optional packages) but still prints
    // the tree; the tree is what is checked.
    const json = spawnSync("npm", ["ls", "--omit=dev", "--all", "--json", "--long"], {
      encoding: "utf8",
      maxBuffer: 64 * 1024 * 1024,
    }).stdout;
    const found = new Map<string, string>();
    walk(JSON.parse(json) as Tree, found);
    expect(found.size).toBeGreaterThan(10);
    const bad = [...found.values()].filter((v) => {
      const license = v.split("|")[1] ?? "";
      // "(MIT OR Apache-2.0)": one allowed alternative is enough.
      const options = license.replace(/[()]/g, "").split(/\s+OR\s+/);
      return !options.some((o) => ALLOWED.test(o.trim()));
    });
    expect(bad).toEqual([]);
  });

  it("are each listed in LICENSES.md", () => {
    const json = spawnSync("npm", ["ls", "--omit=dev", "--all", "--json", "--long"], {
      encoding: "utf8",
      maxBuffer: 64 * 1024 * 1024,
    }).stdout;
    const found = new Map<string, string>();
    walk(JSON.parse(json) as Tree, found);
    const names = new Set([...found.values()].map((v) => v.split("|")[0] ?? ""));
    // Whole names only: "react" must have its own mention, not just be part of "react-dom".
    const listed = (n: string) =>
      new RegExp(`(^|[\\s|,(\`])${n.replace(/[.*+?^${}()|[\]\\/]/g, "\\$&")}([\\s|,)\`]|$)`, "m").test(
        LICENSES_MD,
      );
    const missing = [...names].filter((n) => !listed(n));
    expect(missing).toEqual([]);
  });
});
