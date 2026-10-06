import { Ban, Pin, Star, Tag, X } from "lucide-react";
import { DropdownMenu } from "radix-ui";
import { useState } from "react";

import { Button } from "@/components/ui/Button";
import { Kbd } from "@/components/ui/Kbd";
import { cn } from "@/lib/cn";
import { plural } from "@/lib/format";

import type { DecisionChange } from "./model";

/** COMPONENTS.md BulkBar: floats at the bottom centre when 2 or more clips are selected. */
export function BulkBar({ count, onDecide, onClear }: { count: number; onDecide: (c: DecisionChange) => void; onClear: () => void }) {
  const [tag, setTag] = useState("");
  return (
    <div
      role="toolbar"
      aria-label={`${plural(count, "clip")} selected`}
      className="absolute bottom-6 left-1/2 z-20 flex -translate-x-1/2 items-center gap-1.5 rounded-lg border border-border bg-surface-2 px-3 py-2 shadow-[0_12px_32px_rgba(0,0,0,0.4)]"
    >
      <span className="px-1 text-small font-semibold whitespace-nowrap text-text">{plural(count, "clip")}</span>
      <Button size="sm" onClick={() => onDecide({ disposition: "USE" })}>
        USE
      </Button>
      <Button size="sm" onClick={() => onDecide({ disposition: "MAYBE" })}>
        MAYBE
      </Button>
      <Button size="sm" onClick={() => onDecide({ disposition: "REJECT" })}>
        REJECT
      </Button>
      <DropdownMenu.Root>
        <DropdownMenu.Trigger asChild>
          <Button size="sm" variant="ghost">
            <Star /> Rate
          </Button>
        </DropdownMenu.Trigger>
        <DropdownMenu.Portal>
          <DropdownMenu.Content side="top" sideOffset={8} className="z-50 rounded-md border border-border bg-surface-2 p-1">
            {[5, 4, 3, 2, 1].map((n) => (
              <DropdownMenu.Item
                key={n}
                onSelect={() => onDecide({ stars: n })}
                className="cursor-pointer rounded-sm px-2.5 py-1.5 text-small text-accent outline-none data-[highlighted]:bg-surface-3"
              >
                {"★".repeat(n)}
              </DropdownMenu.Item>
            ))}
            <DropdownMenu.Item
              onSelect={() => onDecide({ stars: null })}
              className="cursor-pointer rounded-sm px-2.5 py-1.5 text-small text-text outline-none data-[highlighted]:bg-surface-3"
            >
              Clear rating
            </DropdownMenu.Item>
          </DropdownMenu.Content>
        </DropdownMenu.Portal>
      </DropdownMenu.Root>
      <DropdownMenu.Root>
        <DropdownMenu.Trigger asChild>
          <Button size="sm" variant="ghost">
            <Tag /> Tag
          </Button>
        </DropdownMenu.Trigger>
        <DropdownMenu.Portal>
          <DropdownMenu.Content side="top" sideOffset={8} className="z-50 rounded-md border border-border bg-surface-2 p-2">
            <form
              onSubmit={(e) => {
                e.preventDefault();
                if (tag.trim()) onDecide({ add_tags: [tag.trim()] });
                setTag("");
              }}
            >
              <input
                aria-label="Tag the selected clips"
                autoFocus
                maxLength={60}
                value={tag}
                onChange={(e) => setTag(e.target.value)}
                onKeyDown={(e) => e.stopPropagation()}
                placeholder="Tag name, then Enter"
                className="h-8 w-48 rounded-sm border border-border bg-surface-3 px-2 text-small text-text focus-visible:outline-2 focus-visible:outline-accent"
              />
            </form>
          </DropdownMenu.Content>
        </DropdownMenu.Portal>
      </DropdownMenu.Root>
      <Button size="sm" variant="ghost" onClick={() => onDecide({ include: "always" })}>
        <Pin /> Always
      </Button>
      <Button size="sm" variant="ghost" onClick={() => onDecide({ include: "never" })}>
        <Ban /> Never
      </Button>
      <Button size="sm" variant="ghost" onClick={() => onDecide({ disposition: null, include: null, stars: null })}>
        Clear
      </Button>
      <Button size="icon" variant="ghost" aria-label="Clear selection" className="size-8" onClick={onClear}>
        <X />
      </Button>
    </div>
  );
}

/** COMPONENTS.md DayScrubber: a right-edge D1…Dn jump list for long trips. */
export function DayScrubber({ days, current, onJump }: { days: { key: string; n: number }[]; current?: string; onJump: (key: string) => void }) {
  if (days.length < 2) return null;
  return (
    <nav aria-label="Jump to day" className="flex w-10 shrink-0 flex-col items-center gap-1 overflow-y-auto py-4">
      {days.map((d) => (
        <button
          key={d.key}
          type="button"
          aria-current={d.key === current || undefined}
          onClick={() => onJump(d.key)}
          className={cn(
            "mono w-9 rounded-sm py-0.5 text-timecode-sm focus-visible:outline-2 focus-visible:outline-accent",
            d.key === current ? "bg-accent-soft text-accent" : "text-text-faint hover:text-text",
          )}
        >
          D{d.n}
        </button>
      ))}
    </nav>
  );
}

/** The keyboard hint strip (S10, bottom-left). */
export function KeyHints() {
  const hint = (keys: string, label: string) => (
    <span className="inline-flex items-center gap-1">
      <Kbd>{keys}</Kbd>
      {label}
    </span>
  );
  return (
    <p className="flex flex-wrap items-center gap-3 px-6 py-2 text-micro font-normal text-text-faint">
      {hint("←↑↓→", "move")}
      {hint("U M R", "decide")}
      {hint("1–5 0", "rate")}
      {hint("L X", "always / never")}
      {hint("Space", "play")}
      {hint("Enter", "open")}
      {hint("⌘A", "select group")}
      {hint("Esc", "clear")}
      {hint("/", "search")}
    </p>
  );
}
