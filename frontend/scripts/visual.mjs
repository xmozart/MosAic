// Visual regression for every Storybook story in both themes (M2 acceptance 7; ADR 0056).
//
//   npm run visual                     compare with the baselines in visual/
//   npm run visual -- --update         (re)write the baselines
//
// `npm run visual` runs this inside the pinned Playwright image (scripts/visual-docker.sh),
// so text renders the same on every host: one set of baselines for macOS and Linux CI.
//
// Serves the built Storybook (`npm run build-storybook`), renders each story in headless
// Chromium at 1280 × 800 with animations off, and compares it pixel by pixel. A story whose
// render differs in more than 0.1 % of its pixels fails; its diff image is written to
// visual-diff/ for review.
import { createReadStream, existsSync, mkdirSync, readdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { createServer } from "node:http";
import { extname, join, normalize } from "node:path";
import { fileURLToPath } from "node:url";

import pixelmatch from "pixelmatch";
import { chromium } from "playwright";
import { PNG } from "pngjs";

const ROOT = fileURLToPath(new URL("..", import.meta.url));
const STATIC = join(ROOT, "storybook-static");
const BASE = join(ROOT, "visual");
const DIFF = join(ROOT, "visual-diff");
const UPDATE = process.argv.includes("--update");
const THEMES = ["dark", "light"];
const MAX_DIFF = 0.001;
const TYPES = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".json": "application/json", ".woff2": "font/woff2", ".svg": "image/svg+xml", ".png": "image/png", ".jpg": "image/jpeg", ".mp4": "video/mp4" };

if (!existsSync(join(STATIC, "index.json"))) {
  console.error("Build Storybook first: npm run build-storybook");
  process.exit(2);
}

const server = createServer((req, res) => {
  const path = normalize(decodeURIComponent(new URL(req.url, "http://x").pathname)).replace(/^(\.\.[/\\])+/, "");
  const file = join(STATIC, path === "/" ? "index.html" : path);
  if (!file.startsWith(STATIC) || !existsSync(file)) {
    res.writeHead(404).end();
    return;
  }
  res.writeHead(200, { "Content-Type": TYPES[extname(file)] ?? "application/octet-stream" });
  createReadStream(file).pipe(res);
});
await new Promise((r) => server.listen(0, "127.0.0.1", r));
const origin = `http://127.0.0.1:${server.address().port}`;

const stories = Object.values(JSON.parse(readFileSync(join(STATIC, "index.json"), "utf8")).entries)
  .filter((e) => e.type === "story")
  .map((e) => e.id)
  .sort();

rmSync(DIFF, { recursive: true, force: true });
mkdirSync(BASE, { recursive: true });
const browser = await chromium.launch();
const context = await browser.newContext({ viewport: { width: 1280, height: 800 }, deviceScaleFactor: 1, reducedMotion: "reduce", timezoneId: "UTC", locale: "en-US" });
// Stories that read the clock see one fixed moment.
await context.addInitScript(() => {
  const fixed = new Date("2026-07-20T12:00:00Z").valueOf();
  const RealDate = Date;
  globalThis.Date = class extends RealDate {
    constructor(...a) {
      super(...(a.length ? a : [fixed]));
    }
    static now() {
      return fixed;
    }
  };
});
const page = await context.newPage();
const failed = [];
let written = 0;

for (const id of stories) {
  for (const theme of THEMES) {
    await page.goto(`${origin}/iframe.html?id=${id}&viewMode=story&globals=theme:${theme}`);
    try {
      await page.waitForSelector("#storybook-root > *", { timeout: 15000 });
      // The theme decorator ran (a story may pin its own theme, e.g. a "Light" story).
      await page.waitForFunction(() => document.documentElement.dataset.theme !== undefined, null, { timeout: 5000 });
    } catch {
      failed.push(`${id} (${theme}): did not render`);
      continue;
    }
    await page.evaluate(() => document.fonts.ready);
    await page.waitForTimeout(150); // effects that settle after the first paint
    const shot = PNG.sync.read(await page.screenshot({ animations: "disabled", caret: "hide" }));
    const file = join(BASE, `${id}.${theme}.png`);
    if (UPDATE) {
      writeFileSync(file, PNG.sync.write(shot));
      written++;
      continue;
    }
    if (!existsSync(file)) {
      failed.push(`${id} (${theme}): no baseline (a new story: run with --update)`);
      continue;
    }
    const base = PNG.sync.read(readFileSync(file));
    if (base.width !== shot.width || base.height !== shot.height) {
      failed.push(`${id} (${theme}): size ${shot.width}×${shot.height}, baseline ${base.width}×${base.height}`);
      continue;
    }
    const diff = new PNG({ width: base.width, height: base.height });
    const n = pixelmatch(base.data, shot.data, diff.data, base.width, base.height, { threshold: 0.1 });
    if (n / (base.width * base.height) > MAX_DIFF) {
      mkdirSync(DIFF, { recursive: true });
      writeFileSync(join(DIFF, `${id}.${theme}.png`), PNG.sync.write(diff));
      writeFileSync(join(DIFF, `${id}.${theme}.actual.png`), PNG.sync.write(shot));
      failed.push(`${id} (${theme}): ${n} pixels differ`);
    }
  }
}

await browser.close();
server.close();
if (UPDATE) {
  // Baselines of stories that no longer exist go too.
  const keep = new Set(stories.flatMap((id) => THEMES.map((t) => `${id}.${t}.png`)));
  for (const f of readdirSync(BASE)) if (!keep.has(f)) rmSync(join(BASE, f));
}
console.log(`visual: ${stories.length} stories × ${THEMES.length} themes; ${written} baselines written; ${failed.length} failed`);
if (failed.length) {
  console.error(failed.join("\n"));
  console.error("Review visual-diff/; if the change is intended: node scripts/visual.mjs --update");
  process.exit(1);
}
