import { Dialog } from "radix-ui";
import { Search } from "lucide-react";
import { useMemo, useState } from "react";

import { cn } from "@/lib/cn";

export interface Command {
  id: string;
  label: string;
  kind: "Library" | "Clip" | "Action" | "Project";
  run: () => void;
}

export interface CommandPaletteProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  commands: Command[];
  /** Offers "Search footage for …" with the typed text (S12). */
  onSearch?: (query: string) => void;
}

/** ⌘K palette (COMPONENTS.md CommandPalette): searches footage, clips and actions; keyboard-first. */
export function CommandPalette({ open, onOpenChange, commands, onSearch }: CommandPaletteProps) {
  const [q, setQ] = useState("");
  const [i, setI] = useState(0);
  const items = useMemo(() => {
    const t = q.trim().toLowerCase();
    const found = t ? commands.filter((c) => c.label.toLowerCase().includes(t)) : commands;
    const search: Command[] =
      t && onSearch ? [{ id: "search", label: `Search footage for “${q.trim()}”`, kind: "Library", run: () => onSearch(q.trim()) }] : [];
    return [...search, ...found].slice(0, 12);
  }, [q, commands, onSearch]);
  const choose = (c: Command | undefined) => {
    if (!c) return;
    onOpenChange(false);
    setQ("");
    setI(0);
    c.run();
  };
  return (
    <Dialog.Root
      open={open}
      onOpenChange={(o) => {
        if (!o) {
          setQ("");
          setI(0);
        }
        onOpenChange(o);
      }}
    >
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-scrim" />
        <Dialog.Content
          aria-describedby={undefined}
          className="fixed top-[18%] left-1/2 z-50 w-[560px] -translate-x-1/2 overflow-hidden rounded-lg border border-border bg-surface-1 shadow-[0_24px_64px_rgba(0,0,0,0.5)]"
        >
          <Dialog.Title className="sr-only">Search or jump to</Dialog.Title>
          <div className="flex items-center gap-2.5 border-b border-border px-4">
            <Search aria-hidden className="size-4 text-text-faint" />
            <input
              autoFocus
              value={q}
              onChange={(e) => {
                setQ(e.target.value);
                setI(0);
              }}
              onKeyDown={(e) => {
                if (e.key === "ArrowDown") {
                  e.preventDefault();
                  setI((v) => Math.min(items.length - 1, v + 1));
                } else if (e.key === "ArrowUp") {
                  e.preventDefault();
                  setI((v) => Math.max(0, v - 1));
                } else if (e.key === "Enter") {
                  e.preventDefault();
                  choose(items[i]);
                }
              }}
              placeholder="Search footage, clips and actions"
              aria-label="Search or jump to"
              role="combobox"
              aria-expanded
              aria-controls="palette-list"
              aria-activedescendant={items[i] ? `palette-${items[i].id}` : undefined}
              className="h-12 flex-1 bg-transparent text-body text-text outline-none placeholder:text-text-faint"
            />
            <kbd className="mono rounded-sm border border-border px-1.5 text-[11px] text-text-muted">esc</kbd>
          </div>
          <ul id="palette-list" role="listbox" className="max-h-80 overflow-y-auto p-1.5">
            {items.map((c, n) => (
              <li
                key={c.id}
                id={`palette-${c.id}`}
                role="option"
                aria-selected={n === i}
                onMouseEnter={() => setI(n)}
                onClick={() => choose(c)}
                className={cn(
                  "flex cursor-pointer items-center justify-between gap-3 rounded-md px-3 py-2 text-small text-text",
                  n === i && "bg-surface-2",
                )}
              >
                <span className="truncate">{c.label}</span>
                <span className="text-caption text-text-faint">{c.kind}</span>
              </li>
            ))}
            {!items.length && <li className="px-3 py-6 text-center text-small text-text-muted">Nothing matches.</li>}
          </ul>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
