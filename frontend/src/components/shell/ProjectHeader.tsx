import { Search } from "lucide-react";
import { useState, type ReactNode } from "react";

import { PlacementBadge, type Placement } from "@/components/system/PlacementBadge";
import { cn } from "@/lib/cn";

export type ProjectStatus =
  | { state: "analyzed"; mode?: string | null }
  | { state: "analyzing"; pct: number }
  | { state: "scanning"; pct: number }
  | { state: "preliminary" }
  | { state: "scanned" }
  | { state: "not_analyzed" };

const DOT: Record<ProjectStatus["state"], string> = {
  analyzed: "bg-use",
  analyzing: "bg-accent",
  scanning: "bg-accent",
  preliminary: "bg-info",
  scanned: "bg-text-faint",
  not_analyzed: "bg-text-faint",
};

function label(s: ProjectStatus): string {
  switch (s.state) {
    case "analyzed":
      return s.mode ? `Analyzed · ${s.mode[0]!.toUpperCase()}${s.mode.slice(1)}` : "Analyzed";
    case "analyzing":
      return `Analyzing ${s.pct}%`;
    case "scanning":
      return `Looking through footage ${s.pct}%`;
    case "preliminary":
      return "Preliminary";
    case "scanned":
      return "Scanned";
    default:
      return "Not analyzed";
  }
}

export interface ProjectHeaderProps {
  name: string;
  placement: Placement;
  status: ProjectStatus;
  aiCost?: string; // display: "AI $1.34"
  crumb?: ReactNode;
  readOnly?: boolean;
  onRename?: (name: string) => void;
  onSearch: () => void; // opens the command palette (⌘K)
}

/** 56 px project header (COMPONENTS.md ProjectHeader). The name is editable inline. */
export function ProjectHeader(p: ProjectHeaderProps) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(p.name);
  const commit = () => {
    setEditing(false);
    const v = draft.trim();
    if (v && v !== p.name) p.onRename?.(v);
    else setDraft(p.name);
  };
  return (
    <header className="flex h-14 shrink-0 items-center gap-3 border-b border-border bg-bg px-6">
      {editing ? (
        <input
          aria-label="Project name"
          autoFocus
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onBlur={commit}
          onKeyDown={(e) => {
            if (e.key === "Enter") commit();
            if (e.key === "Escape") {
              setDraft(p.name);
              setEditing(false);
            }
          }}
          className="rounded-sm border border-border bg-surface-3 px-1.5 text-subhead font-semibold text-text"
        />
      ) : (
        <button
          type="button"
          disabled={p.readOnly || !p.onRename}
          onClick={() => {
            setDraft(p.name);
            setEditing(true);
          }}
          title={p.readOnly ? "Read-only: open for editing to rename" : "Rename"}
          className="rounded-sm text-subhead font-semibold text-text focus-visible:outline-2 focus-visible:outline-accent disabled:cursor-default"
        >
          {p.name}
        </button>
      )}
      <PlacementBadge placement={p.placement} />
      {p.crumb}
      <div className="flex-1" />
      <span className="inline-flex items-center gap-[7px] rounded-full border border-border bg-surface-2 px-2.5 py-1 text-caption text-text">
        <span aria-hidden className={cn("size-2 rounded-full", DOT[p.status.state])} />
        {label(p.status)}
      </span>
      {p.aiCost && <span className="mono text-caption text-text-muted">{p.aiCost}</span>}
      <button
        type="button"
        onClick={p.onSearch}
        className="inline-flex items-center gap-2 rounded-md border border-border px-2.5 py-[5px] text-caption text-text-faint hover:text-text-muted focus-visible:outline-2 focus-visible:outline-accent"
      >
        <Search aria-hidden className="size-3.5" />
        Search or jump to…
        <kbd className="mono inline-flex h-[18px] min-w-[18px] items-center justify-center rounded-sm border border-border bg-surface-2 px-[5px] text-[11px] text-text-muted">
          ⌘K
        </kbd>
      </button>
    </header>
  );
}
