import { User } from "lucide-react";

import { cn } from "@/lib/cn";

export interface VersionListItem {
  version: number;
  /** The owner's (`user`) or the AI's (or the app's own, shown as the AI's). */
  byYou: boolean;
  reason: string;
  when: string;
  duration: string;
}

export interface VersionListProps {
  items: VersionListItem[];
  /** The versions being compared (highlighted). */
  selected: number[];
  onSelect: (version: number) => void;
}

/** COMPONENTS.md VersionList: each version with who made it (AI or You), why, when and how
 * long; newest first. */
export function VersionList({ items, selected, onSelect }: VersionListProps) {
  return (
    <ul aria-label="Versions" className="flex flex-col gap-2.5">
      {items.map((v) => {
        const on = selected.includes(v.version);
        return (
          <li key={v.version}>
            <button
              type="button"
              aria-pressed={on}
              onClick={() => onSelect(v.version)}
              className={cn(
                "flex w-full flex-col gap-1.5 rounded-lg border px-3.5 py-3 text-left focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent",
                on ? "border-accent bg-surface-2" : "border-border hover:bg-surface-1",
              )}
            >
              <span className="flex items-center gap-2">
                <span className="mono text-timecode font-semibold text-text">v{v.version}</span>
                <span
                  className={cn(
                    "inline-flex items-center gap-1 rounded-full border border-border bg-surface-2 px-[9px] py-[3px] text-micro font-medium",
                    v.byYou ? "text-user" : "text-text-muted",
                  )}
                >
                  {v.byYou && <User aria-hidden className="size-3" />}
                  {v.byYou ? "You" : "AI"}
                </span>
                <span className="mono ml-auto text-timecode-sm text-text-muted">{v.duration}</span>
              </span>
              <span className="text-small text-text">{v.reason}</span>
              <span className="text-caption font-normal text-text-faint">{v.when}</span>
            </button>
          </li>
        );
      })}
    </ul>
  );
}
