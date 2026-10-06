import type { Meta, StoryObj } from "@storybook/react-vite";

import tokens from "../../../../docs/ui/tokens.json";

// From tokens.json itself, so every token is shown and no class names are spelled here.
const COLORS = tokens.color.tokens.map((t) => t.name);
// Literal class names so Tailwind generates them.
const TYPE = [
  ["display", "text-display"],
  ["title", "text-title"],
  ["heading", "text-heading"],
  ["subhead", "text-subhead"],
  ["body", "text-body"],
  ["small", "text-small"],
  ["caption", "text-caption"],
] as const;

function Foundations() {
  return (
    <div className="space-y-8">
      <section className="grid grid-cols-4 gap-4">
        {COLORS.map((c) => (
          <div key={c} className="rounded-md border border-border bg-surface-1 p-3">
            <div className="h-10 rounded-sm border border-border" style={{ background: `var(--${c})` }} />
            <p className="mono mt-2 text-caption text-text-muted">{c}</p>
          </div>
        ))}
      </section>
      <section className="space-y-2">
        {TYPE.map(([name, cls]) => (
          <p key={name} className={cls}>
            {name} — Your trip, told well.
          </p>
        ))}
        <p className="mono text-timecode">00:01:24:12 · 1 h 40 m · $2–4 · 18 GB</p>
      </section>
    </div>
  );
}

const meta: Meta<typeof Foundations> = { title: "Design system/Foundations", component: Foundations };
export default meta;
export const Default: StoryObj<typeof Foundations> = {};
