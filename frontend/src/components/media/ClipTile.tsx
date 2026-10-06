import { Mic, Orbit, TriangleAlert, Unplug } from "lucide-react";
import { useState, type MouseEvent } from "react";

import { cn } from "@/lib/cn";
import type { CameraKind, DecidedBy, Density, Disposition } from "@/lib/domain";

import { CameraBadge } from "./CameraBadge";
import { DispositionChip } from "./DispositionChip";

export interface TileAsset {
  name: string; // filename (mono)
  duration?: string; // display only, e.g. "0:48"
  camera: { kind: CameraKind; label: string };
  thumbnail?: string; // first sample frame URL
  frames?: string[]; // sample frame URLs for hover-scrub (never video decode)
  livePhoto?: boolean;
  analysisOnly?: boolean; // raw 360: analyzed but not editable yet
  offline?: boolean; // source unreachable; the proxy still plays
  unsupported?: { reason: string; fix?: string };
}

export interface ClipTileProps {
  asset: TileAsset;
  disposition?: Disposition;
  decidedBy?: DecidedBy;
  stars?: number;
  hasSpeech?: boolean;
  similarCount?: number;
  selected?: boolean;
  density?: Density;
  caption?: string;
  /** Analysis still running for this clip: shimmer, no disposition yet. */
  preliminary?: boolean;
  onSelect?: (e: MouseEvent) => void;
  onOpen?: () => void;
  /** Pins the hover-scrub position (stories and tests); normally driven by the pointer. */
  scrubIndex?: number;
  /** A grid's roving tabindex: only its focused tile is in the tab order (S10). */
  tabIndex?: number;
  onFocus?: () => void;
}

/** Library tile (COMPONENTS.md ClipTile; DS-Components "Thumbnail tile"). */
export function ClipTile({
  asset,
  disposition,
  decidedBy = "ai",
  stars = 0,
  hasSpeech,
  similarCount = 0,
  selected,
  density = "comfortable",
  caption,
  preliminary,
  onSelect,
  onOpen,
  scrubIndex,
  tabIndex = 0,
  onFocus,
}: ClipTileProps) {
  const [pointer, setScrub] = useState<number | null>(null);
  const scrub = scrubIndex ?? pointer;
  const hovering = scrub !== null;
  const frames = asset.frames ?? [];
  const src = scrub !== null && frames.length ? frames[scrub] : asset.thumbnail;
  const dimmed = disposition === "REJECT";
  const blocked = Boolean(asset.unsupported);

  const onMove = (e: MouseEvent<HTMLDivElement>) => {
    if (!frames.length) return;
    const r = e.currentTarget.getBoundingClientRect();
    const i = Math.min(frames.length - 1, Math.max(0, Math.floor(((e.clientX - r.left) / r.width) * frames.length)));
    setScrub(i); // instant (DESIGN_TOKENS.md §4: hover-scrub is not animated)
  };

  return (
    <div className={cn("relative flex min-w-0 flex-col gap-1.5", dimmed && "opacity-55")} data-testid="clip-tile">
      {similarCount > 0 && (
        <div aria-hidden className="absolute -top-[5px] right-1.5 left-1.5 h-3 rounded-[8px] bg-surface-3" />
      )}
      <div
        role="button"
        tabIndex={tabIndex}
        onFocus={onFocus}
        aria-pressed={selected}
        aria-label={asset.name}
        onClick={onSelect}
        onDoubleClick={onOpen}
        onKeyDown={(e) => e.key === "Enter" && onOpen?.()}
        onMouseMove={onMove}
        onMouseLeave={() => setScrub(null)}
        className={cn(
          "group relative aspect-video w-full overflow-hidden rounded-md bg-surface-3 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent",
          selected && "outline-2 outline-offset-2 outline-accent",
        )}
      >
        {src && !blocked && <img src={src} alt="" draggable={false} className="absolute inset-0 size-full object-cover" />}
        {/* Everything drawn over footage uses the dark token values in both themes:
            footage is not themed (ADR 0033). The selection outline stays in the page theme. */}
        <div data-theme="dark" className="contents">
          {frames.length > 0 && scrub !== null && (
            <div aria-hidden className="absolute right-0 bottom-0 left-0 h-0.5 bg-scrim">
              <div className="h-full bg-accent" style={{ width: `${((scrub + 1) / frames.length) * 100}%` }} />
            </div>
          )}

          <div className="absolute top-2 right-2 left-2 flex items-start justify-between gap-1.5">
            <span className="inline-flex gap-1">
              <CameraBadge kind={asset.camera.kind} label={asset.camera.label} />
              {asset.livePhoto && (
                <span className="rounded-sm bg-media-chip px-1.5 py-0.5 text-tag font-bold tracking-[0.06em] text-on-media">
                  LIVE
                </span>
              )}
            </span>
            {preliminary ? (
              <span
                role="img"
                aria-label="Analysis in progress"
                className="motion-shimmer h-[18px] w-12 animate-pulse rounded-sm bg-on-media/20"
              />
            ) : (
              disposition && <DispositionChip value={disposition} by={decidedBy} size="sm" onMedia />
            )}
          </div>

          {asset.analysisOnly && (
            <div className="absolute inset-x-0 top-1/2 flex -translate-y-1/2 justify-center">
              <span className="inline-flex items-center gap-1.5 rounded-sm bg-media-overlay px-2 py-1 text-caption text-on-media">
                <Orbit aria-hidden className="size-3.5" /> 360 · analysis only
              </span>
            </div>
          )}
          {asset.offline && (
            <div className="absolute inset-x-0 top-1/2 flex -translate-y-1/2 justify-center">
              <span className="inline-flex items-center gap-1.5 rounded-sm bg-media-overlay px-2 py-1 text-caption text-on-media">
                <Unplug aria-hidden className="size-3.5" /> Source offline
              </span>
            </div>
          )}

          {!blocked && (
            <div className="absolute inset-x-0 bottom-0 flex items-end justify-between gap-1.5 bg-gradient-to-b from-transparent to-scrim px-2 pt-5 pb-[7px] text-on-media">
              <span className="flex min-w-0 flex-col gap-[3px]">
                {/* Rated clips always show their stars; on hover an unrated clip shows empty
                    ones, ready for the 1–5 keys (COMPONENTS.md: "hover (scrub + stars)"). */}
                {(stars > 0 || hovering) && (
                  <span
                    role="img"
                    aria-label={stars > 0 ? `${stars} of 5 stars` : "Not rated"}
                    className="text-micro leading-none tracking-[1px]"
                  >
                    {[1, 2, 3, 4, 5].map((n) => (
                      <span key={n} className={n <= stars ? "text-accent" : "text-on-media/35"}>
                        ★
                      </span>
                    ))}
                  </span>
                )}
                {density === "comfortable" && <span className="mono truncate text-micro">{asset.name}</span>}
              </span>
              <span className="inline-flex items-center gap-1.5">
                {hasSpeech && <Mic aria-label="Has speech" className="size-3" />}
                {similarCount > 0 && (
                  <span className="rounded-[5px] bg-media-chip px-[5px] py-px text-tag font-semibold">
                    +{similarCount}
                  </span>
                )}
                {asset.duration && <span className="mono text-micro">{asset.duration}</span>}
              </span>
            </div>
          )}
        </div>
        {/* Not footage: a card in the page theme. */}
        {asset.unsupported && (
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-1 bg-surface-2 p-3 text-center">
            <TriangleAlert aria-hidden className="size-4 text-maybe" />
            <p className="text-caption text-text">{asset.unsupported.reason}</p>
        {asset.unsupported.fix && <p className="text-caption font-normal text-text-muted">{asset.unsupported.fix}</p>}
          </div>
        )}
      </div>
      {caption && <div className="truncate px-0.5 text-caption font-normal text-text-muted">{caption}</div>}
    </div>
  );
}
