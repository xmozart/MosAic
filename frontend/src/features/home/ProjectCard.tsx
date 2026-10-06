import { FolderOpen, MoreHorizontal } from "lucide-react";
import { DropdownMenu } from "radix-ui";

import { Button } from "@/components/ui/Button";
import { PlacementBadge, type Placement } from "@/components/system/PlacementBadge";
import { cn } from "@/lib/cn";
import { formatDateRange, formatDuration, plural } from "@/lib/format";

export interface ProjectCardData {
  name: string;
  placement: Placement;
  cover: string[]; // up to 3 frame URLs: one large, two small
  firstDate: string | null;
  lastDate: string | null;
  footageSeconds: number;
  clips: number;
  photos: number;
  status: { state: string; pct?: number; mode?: string | null };
  latestEdit: string | null;
  opened: string; // display: "Today"
  missing: boolean | null; // null: still checking
}

export interface ProjectCardProps {
  data: ProjectCardData;
  onOpen: () => void;
  onReconnect?: () => void;
  onRemove: () => void;
}

const STATUS_DOT: Record<string, string> = {
  analyzed: "bg-use",
  analyzing: "bg-accent",
  scanning: "bg-accent",
  scanned: "bg-text-faint",
  not_analyzed: "bg-text-faint",
};

function statusLabel(s: ProjectCardData["status"]): string {
  if (s.state === "analyzing") return `Analyzing ${s.pct ?? 0}%`;
  if (s.state === "scanning") return `Looking through footage ${s.pct ?? 0}%`;
  if (s.state === "analyzed") return s.mode ? `Analyzed · ${s.mode[0]!.toUpperCase()}${s.mode.slice(1)}` : "Analyzed";
  if (s.state === "scanned") return "Scanned";
  return "Not analyzed";
}

function ProgressRing({ pct }: { pct: number }) {
  const r = 22;
  const c = 2 * Math.PI * r;
  return (
    <div className="absolute inset-0 flex items-center justify-center bg-scrim">
      <svg viewBox="0 0 52 52" className="size-14 -rotate-90" aria-hidden>
        <circle cx="26" cy="26" r={r} fill="none" strokeWidth="4" className="stroke-on-media/25" />
        <circle cx="26" cy="26" r={r} fill="none" strokeWidth="4" strokeLinecap="round" className="stroke-accent" strokeDasharray={c} strokeDashoffset={c * (1 - pct / 100)} />
      </svg>
      <span className="mono absolute text-timecode text-on-media">{pct}%</span>
    </div>
  );
}

/** A Home card (S3): collage cover, name and placement, facts, status, latest edit. */
export function ProjectCard({ data: d, onOpen, onReconnect, onRemove }: ProjectCardProps) {
  const facts = [
    formatDateRange(d.firstDate, d.lastDate),
    d.footageSeconds ? formatDuration(d.footageSeconds) : null,
    d.clips ? plural(d.clips, "clip") : null,
    d.photos ? plural(d.photos, "photo") : null,
  ].filter(Boolean);
  const running = d.status.state === "analyzing" || d.status.state === "scanning";
  return (
    <article
      className={cn(
        "group flex flex-col overflow-hidden rounded-lg border border-border bg-surface-1 transition-colors duration-150 hover:bg-surface-2",
        d.missing && "opacity-60",
      )}
    >
      <button
        type="button"
        onClick={d.missing ? undefined : onOpen}
        aria-disabled={d.missing ? true : undefined}
        aria-label={d.missing ? `${d.name}: folder not found` : `Open ${d.name}`}
        className="relative grid aspect-[16/9] grid-cols-3 grid-rows-2 gap-0.5 bg-surface-3 focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-accent"
      >
        {[0, 1, 2].map((i) => (
          <div key={i} className={cn("overflow-hidden bg-surface-3", i === 0 ? "col-span-2 row-span-2" : "")}>
            {d.cover[i] && <img src={d.cover[i]} alt="" className="size-full object-cover" />}
          </div>
        ))}
        {running && <ProgressRing pct={d.status.pct ?? 0} />}
        {d.missing && (
          <div className="absolute inset-0 flex items-center justify-center bg-scrim">
            <span className="rounded-sm bg-media-overlay px-2 py-1 text-caption text-on-media">Folder not found</span>
          </div>
        )}
      </button>
      <div className="flex flex-col gap-2 p-4">
        <div className="flex items-center gap-2">
          <h3 className="min-w-0 flex-1 truncate text-subhead text-text">{d.name}</h3>
          <PlacementBadge placement={d.placement} />
          <DropdownMenu.Root>
            <DropdownMenu.Trigger asChild>
              <button
                type="button"
                aria-label={`More for ${d.name}`}
                className="rounded-sm p-1 text-text-muted opacity-0 group-hover:opacity-100 hover:text-text focus-visible:opacity-100 focus-visible:outline-2 focus-visible:outline-accent"
              >
                <MoreHorizontal className="size-4" />
              </button>
            </DropdownMenu.Trigger>
            <DropdownMenu.Portal>
              <DropdownMenu.Content
                align="end"
                className="z-50 min-w-44 rounded-md border border-border bg-surface-2 p-1 shadow-[0_12px_32px_rgba(0,0,0,0.4)]"
              >
                {!d.missing && (
                  <DropdownMenu.Item onSelect={onOpen} className="cursor-pointer rounded-sm px-2.5 py-1.5 text-small text-text outline-none data-[highlighted]:bg-surface-3">
                    Open
                  </DropdownMenu.Item>
                )}
                <DropdownMenu.Item onSelect={onRemove} className="cursor-pointer rounded-sm px-2.5 py-1.5 text-small text-text outline-none data-[highlighted]:bg-surface-3">
                  Remove from recents
                </DropdownMenu.Item>
              </DropdownMenu.Content>
            </DropdownMenu.Portal>
          </DropdownMenu.Root>
        </div>
        {facts.length > 0 && <p className="mono truncate text-timecode-sm text-text-muted">{facts.join(" · ")}</p>}
        {d.missing ? (
          <div className="flex gap-2 pt-1">
            {onReconnect && (
              <Button size="sm" onClick={onReconnect}>
                <FolderOpen /> Reconnect
              </Button>
            )}
            <Button size="sm" variant="ghost" onClick={onRemove}>
              Remove from list
            </Button>
          </div>
        ) : (
          <div className="flex items-center justify-between gap-2 text-caption text-text-muted">
            <span className="inline-flex items-center gap-1.5 text-text">
              <span aria-hidden className={cn("size-2 rounded-full", STATUS_DOT[d.status.state] ?? "bg-text-faint")} />
              {statusLabel(d.status)}
            </span>
            <span className="truncate font-normal">
              Latest: {d.latestEdit ?? "—"} · Opened {d.opened}
            </span>
          </div>
        )}
      </div>
    </article>
  );
}
