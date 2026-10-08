import { Layers, TriangleAlert } from "lucide-react";
import type { ReactNode } from "react";

import { cn } from "@/lib/cn";

export type EditCardTone = "done" | "ready" | "busy" | "warn" | "failed" | "idle";

export interface EditCardProps {
  name: string;
  /** "16:9 · 4K" */
  format: string;
  /** Vertical-aware cover: a non-landscape edit shows its frame in its own shape, centred. */
  shape: "landscape" | "9:16" | "4:5" | "1:1";
  coverUrl?: string;
  duration?: string | null;
  versions: number;
  status: { text: string; tone: EditCardTone };
  /** 0–100 while generating: a ring over the cover. */
  progress?: number | null;
  created: string;
  preliminary?: boolean;
  /** The card's link (a router Link or an anchor); it wraps the whole card. */
  renderLink: (children: ReactNode, className: string) => ReactNode;
}

const DOT: Record<EditCardTone, string> = {
  done: "bg-use",
  ready: "bg-info",
  busy: "bg-accent",
  warn: "bg-maybe",
  failed: "bg-reject",
  idle: "bg-text-faint",
};

const SHAPE: Record<EditCardProps["shape"], string> = {
  landscape: "w-full",
  "9:16": "aspect-[9/16]",
  "4:5": "aspect-[4/5]",
  "1:1": "aspect-square",
};

/** COMPONENTS.md EditCard (S13): cover, duration, format, versions, status, preliminary. */
export function EditCard(p: EditCardProps) {
  return p.renderLink(
    <>
      <div className="relative flex aspect-video items-center justify-center overflow-hidden rounded-[12px] bg-surface-2">
        {p.coverUrl && (
          <img
            src={p.coverUrl}
            alt=""
            loading="lazy"
            className={cn("h-full object-cover", SHAPE[p.shape])}
          />
        )}
        {p.duration && (
          <span data-theme="dark" className="mono absolute right-2.5 bottom-2 rounded-sm bg-media-chip px-1.5 py-0.5 text-timecode text-on-media">
            {p.duration}
          </span>
        )}
        {p.progress != null && (
          <div className="absolute inset-0 flex items-center justify-center bg-scrim">
            <Ring pct={p.progress} />
          </div>
        )}
      </div>
      <span className="text-subhead font-semibold tracking-[-0.01em] text-text">{p.name}</span>
      <span className="flex flex-wrap items-center gap-1.5">
        <Chip>{p.format}</Chip>
        <Chip>
          <Layers aria-hidden className="size-[13px]" />
          {p.versions === 1 ? "1 version" : `${p.versions} versions`}
        </Chip>
        <span className="ml-auto inline-flex items-center gap-1.5 text-caption font-normal whitespace-nowrap text-text">
          <span aria-hidden className={cn("size-2 shrink-0 rounded-full", DOT[p.status.tone])} />
          {p.status.text}
        </span>
      </span>
      <span className="text-caption font-normal text-text-faint">{p.created}</span>
      {p.preliminary && (
        <span className="flex items-start gap-1.5 text-caption font-normal text-text-muted">
          <TriangleAlert aria-hidden className="mt-px size-3.5 shrink-0 text-maybe" />
          Made before analysis finished — regenerate for better results.
        </span>
      )}
    </>,
    "flex flex-col gap-2.5 rounded-[16px] border border-border bg-surface-1 px-3 pt-3 pb-3.5 text-left transition-colors duration-150 hover:border-text-faint focus-visible:outline-2 focus-visible:outline-accent",
  );
}

function Chip({ children }: { children: ReactNode }) {
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full border border-border bg-surface-2 px-[9px] py-[3px] text-micro font-medium whitespace-nowrap text-text-muted">
      {children}
    </span>
  );
}

function Ring({ pct }: { pct: number }) {
  const r = 20.5;
  const c = 2 * Math.PI * r;
  return (
    <svg width="44" height="44" viewBox="0 0 44 44" role="img" aria-label={`${pct}%`} className="-rotate-90">
      <circle cx="22" cy="22" r={r} fill="none" strokeWidth="3" className="stroke-surface-3" />
      <circle
        cx="22"
        cy="22"
        r={r}
        fill="none"
        strokeWidth="3"
        strokeLinecap="round"
        strokeDasharray={c}
        strokeDashoffset={c * (1 - Math.min(100, Math.max(0, pct)) / 100)}
        className="stroke-accent"
      />
    </svg>
  );
}
