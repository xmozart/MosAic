// Class-name guards for the token rules (DESIGN_TOKENS.md, ADR 0032).
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";

const SRC = join(__dirname, "..");

function files(dir: string): string[] {
  return readdirSync(dir).flatMap((f) => {
    const p = join(dir, f);
    if (statSync(p).isDirectory()) return f === "api" || f === "assets" ? [] : files(p);
    return /\.(ts|tsx)$/.test(f) ? [p] : [];
  });
}

describe("token classes", () => {
  it("never use `text-muted`: that is the shadcn surface alias, not the text colour", () => {
    // The muted text colour is `text-text-muted`; `text-muted` would paint text in surface-2.
    const offenders = files(SRC).filter(
      (f) => !f.endsWith("classes.test.ts") && /(?<![\w-])text-muted(?![\w-])/.test(readFileSync(f, "utf8")),
    );
    expect(offenders).toEqual([]);
  });

  it("round corners only with the radius tokens (sm, md, lg, full)", () => {
    // Mockup radii (8, 12, 16 px, …) map to the nearest token by use (ADR 0056).
    const offenders = files(SRC).filter(
      (f) => !f.endsWith("classes.test.ts") && /rounded(-[a-z]+)?-\[/.test(readFileSync(f, "utf8")),
    );
    expect(offenders).toEqual([]);
  });
});
