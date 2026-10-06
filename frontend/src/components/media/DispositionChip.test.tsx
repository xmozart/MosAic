// M2 acceptance 8: AI-set and user-set disposition chips render as different variants —
// outlined with an "AI" tag vs. filled with the user badge (DESIGN_TOKENS.md §5).
import { render, screen } from "@testing-library/react";

import type { Disposition } from "@/lib/domain";

import { ClipTile } from "./ClipTile";
import { DispositionChip } from "./DispositionChip";

const VALUES: Disposition[] = ["USE", "MAYBE", "REJECT"];

describe("AI vs. you", () => {
  it.each(VALUES)("%s: the AI chip is outlined with an AI tag, no user badge", (v) => {
    render(<DispositionChip value={v} by="ai" />);
    const chip = screen.getByRole("img", { name: `${v}, suggested by AI` });
    expect(chip.dataset.variant).toBe("ai");
    expect(chip.className).toMatch(/\bborder-\[1\.5px\]/);
    expect(chip.className).toMatch(/\bbg-transparent\b/);
    expect(chip.className).not.toMatch(/\bbg-(use|maybe|reject)\b/);
    expect(chip).toHaveTextContent("AI");
    expect(chip.querySelector("[data-badge=user]")).toBeNull();
  });

  it.each(VALUES)("%s: the user chip is filled with the user badge, no AI tag", (v) => {
    render(<DispositionChip value={v} by="user" />);
    const chip = screen.getByRole("img", { name: `${v}, set by you` });
    expect(chip.dataset.variant).toBe("user");
    const fill = chip.firstElementChild as HTMLElement;
    expect(fill.className).toMatch(new RegExp(`\\bbg-${v.toLowerCase()}\\b`));
    expect(chip.querySelector("[data-badge=user]")?.className).toMatch(/\bbg-user\b/);
    expect(chip).not.toHaveTextContent(/\bAI\b/);
  });

  it("never by colour alone: icon and word on both variants", () => {
    for (const by of ["ai", "user"] as const) {
      const { container, unmount } = render(<DispositionChip value="MAYBE" by={by} />);
      expect(container.querySelector("svg")).not.toBeNull();
      expect(container).toHaveTextContent("MAYBE");
      unmount();
    }
  });

  it("tiles carry the same variants", () => {
    const asset = { name: "a.mp4", camera: { kind: "phone" as const, label: "iPhone" } };
    render(
      <>
        <ClipTile asset={asset} disposition="USE" decidedBy="ai" />
        <ClipTile asset={asset} disposition="USE" decidedBy="user" />
      </>,
    );
    expect(screen.getByRole("img", { name: "USE, suggested by AI" }).dataset.variant).toBe("ai");
    expect(screen.getByRole("img", { name: "USE, set by you" }).dataset.variant).toBe("user");
  });
});
