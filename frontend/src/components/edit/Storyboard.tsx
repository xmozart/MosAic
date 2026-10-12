import { DropdownMenu, Popover } from "radix-ui";
import { GripVertical, Image as ImageIcon, Loader2, Lock, MoreHorizontal, Play, RefreshCw, Trash2, Unlock } from "lucide-react";
import type { ComponentPropsWithRef, DragEvent, ReactNode } from "react";

import { Button } from "@/components/ui/Button";
import { cn } from "@/lib/cn";
import { formatClock } from "@/lib/time";

// ------------------------------------------------------------------ DurationBar

export interface DurationBarBeat {
  id: string;
  title: string;
  seconds: number;
  /** Every shot locked: the owner's (`user`); else the AI's (accent). */
  locked: boolean;
  regenerating: boolean;
}

export interface DurationBarProps {
  beats: DurationBarBeat[];
  /** The edit's length now (titles included) and its target, in seconds. */
  seconds: number;
  target: number;
  tolerance: number;
}

/** COMPONENTS.md DurationBar: the beats in proportion, with the target marker and its
 * tolerance band. */
export function DurationBar({ beats, seconds, target, tolerance }: DurationBarProps) {
  const scale = Math.max(seconds, target + tolerance, 1);
  const pct = (s: number) => `${(s / scale) * 100}%`;
  const off = Math.abs(seconds - target) > tolerance;
  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center gap-2.5">
        <span className="text-caption font-semibold text-text-faint">Duration</span>
        <span className={cn("mono text-timecode-sm", off ? "text-maybe" : "text-text")}>
          {formatClock(seconds)} / {formatClock(target)} target ±{Math.round(tolerance)} s
        </span>
      </div>
      <div className="relative">
        <div aria-hidden className="absolute -top-1.5 -bottom-1.5 bg-accent/10" style={{ left: pct(Math.max(0, target - tolerance)), width: pct(2 * tolerance) }} />
        <div className="relative flex gap-[3px]" style={{ width: pct(seconds) }}>
          {beats.map((b) => (
            <div
              key={b.id}
              title={`${b.title} · ${formatClock(b.seconds)}`}
              className={cn(
                "flex h-[30px] min-w-0 items-center overflow-hidden rounded-sm border px-2 text-micro font-normal whitespace-nowrap",
                b.regenerating
                  ? "animate-pulse border-transparent bg-surface-3 text-text"
                  : b.locked
                    ? "border-transparent bg-user text-bg"
                    : "border-accent bg-accent-soft text-text",
              )}
              style={{ flex: `${Math.max(b.seconds, 0.5)} 1 0` }}
            >
              {b.title}
            </div>
          ))}
        </div>
        <div aria-label={`Target ${formatClock(target)}`} className="absolute -top-1.5 -bottom-1.5 w-0.5 bg-accent" style={{ left: pct(target) }} />
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ ShotChip

export interface ShotChipProps {
  frameUrl?: string;
  role: string;
  /** Its length in the edit now; undefined when the shot is not in the edit (dropped to
   * fit the length). */
  seconds?: number;
  locked: boolean;
  photo?: boolean;
  /** A drop lands before this chip. */
  dropBefore?: boolean;
  dragging?: boolean;
  label: string;
  onDragStart: (e: DragEvent) => void;
  onDragEnd: () => void;
  onDragOver: (e: DragEvent) => void;
  onDrop: (e: DragEvent) => void;
  onHover: (on: boolean) => void;
  onFocus: (on: boolean) => void;
}

/** COMPONENTS.md ShotChip: the shot's frame with its length, its role under it; locked
 * shots in the owner's colour. Opens its ShotPopover (it is the popover's trigger). */
export function ShotChip({ ref, ...p }: ShotChipProps & Omit<ComponentPropsWithRef<"button">, keyof ShotChipProps>) {
  const { frameUrl, role, seconds, locked, photo, dropBefore, dragging, label, onDragStart, onDragEnd, onDragOver, onDrop, onHover, onFocus, ...button } = p;
  return (
    <div className="relative flex w-[92px] shrink-0 flex-col gap-1">
      {dropBefore && <span aria-hidden className="absolute top-0 -left-[5px] h-[52px] w-0.5 rounded-full bg-accent" />}
      <button
        ref={ref}
        type="button"
        draggable
        data-shot
        aria-label={label}
        onDragStart={onDragStart}
        onDragEnd={onDragEnd}
        onDragOver={onDragOver}
        onDrop={onDrop}
        onMouseEnter={() => onHover(true)}
        onMouseLeave={() => onHover(false)}
        onFocus={() => onFocus(true)}
        onBlur={() => onFocus(false)}
        {...button}
        className={cn(
          "relative aspect-video cursor-grab overflow-hidden rounded-sm bg-surface-3 focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-accent",
          locked && "outline-2 outline-offset-1 outline-user",
          seconds === undefined && "opacity-50",
          dragging && "opacity-40",
        )}
      >
        {frameUrl && <img src={frameUrl} alt="" loading="lazy" draggable={false} className="size-full object-cover" />}
        {locked && (
          <span aria-hidden className="absolute top-1 right-1 flex rounded-sm bg-user p-0.5 text-bg">
            <Lock className="size-2.5" />
          </span>
        )}
        {photo && (
          <span aria-hidden className="absolute top-1 left-1 flex rounded-sm bg-media-chip p-0.5 text-on-media">
            <ImageIcon className="size-2.5" />
          </span>
        )}
        <span className="mono absolute right-1 bottom-0.5 text-timecode-sm text-on-media [text-shadow:0_1px_2px_rgba(0,0,0,0.6)]">
          {seconds === undefined ? "—" : formatClock(seconds)}
        </span>
      </button>
      <span className="truncate text-micro font-normal text-text-muted">{role}</span>
    </div>
  );
}

// ------------------------------------------------------------------ ShotPopover

export interface PopoverAlternative {
  segment_id: string;
  frameUrl?: string;
  file: string;
  note: string;
}

export interface ShotPopoverProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** The chip. */
  children: ReactNode;
  frameUrl?: string;
  file: string;
  facts: string;
  reason: string;
  locked: boolean;
  /** Undefined while they load. */
  alternatives: PopoverAlternative[] | undefined;
  /** Shown in place of the frame while playing. */
  player?: ReactNode;
  onReplace: (segmentId: string) => void;
  onLock: () => void;
  onRemove: () => void;
  onPlay: () => void;
}

/** COMPONENTS.md ShotPopover: why the AI chose the shot, what could replace it (with why
 * it wasn't chosen), and Lock, Remove and Play. */
export function ShotPopover(p: ShotPopoverProps) {
  return (
    <Popover.Root open={p.open} onOpenChange={p.onOpenChange}>
      <Popover.Trigger asChild>{p.children}</Popover.Trigger>
      <Popover.Portal>
        <Popover.Content
          side="bottom"
          align="start"
          sideOffset={8}
          collisionPadding={16}
          aria-label={`Shot ${p.file}`}
          className="z-50 flex w-[380px] flex-col gap-2.5 rounded-lg border border-border bg-surface-2 p-4 shadow-[0_20px_48px_rgba(0,0,0,0.55)]"
        >
          {p.player ?? (
            <div className="flex items-center gap-2.5">
              <div className="aspect-video w-24 shrink-0 overflow-hidden rounded-sm bg-surface-3">
                {p.frameUrl && <img src={p.frameUrl} alt="" className="size-full object-cover" />}
              </div>
              <div className="flex min-w-0 flex-col gap-[3px]">
                <span className="mono truncate text-timecode font-semibold text-text">{p.file}</span>
                <span className="text-caption font-normal text-text-muted">{p.facts}</span>
              </div>
            </div>
          )}
          {p.player && (
            <div className="flex min-w-0 flex-col gap-[3px]">
              <span className="mono truncate text-timecode font-semibold text-text">{p.file}</span>
              <span className="text-caption font-normal text-text-muted">{p.facts}</span>
            </div>
          )}
          <p className="text-small text-text">{p.reason}</p>
          {p.locked ? (
            <p className="text-caption font-normal text-text-faint">Locked: unlock it to replace or remove it.</p>
          ) : (
            <>
              <span className="text-caption font-semibold text-text-faint">Replace with…</span>
              {p.alternatives === undefined ? (
                [0, 1].map((i) => <div key={i} aria-hidden className="h-12 animate-pulse rounded-sm bg-surface-1" />)
              ) : p.alternatives.length === 0 ? (
                <p className="text-caption font-normal text-text-faint">Nothing else fits this beat.</p>
              ) : (
                <ul className="flex max-h-56 flex-col gap-1.5 overflow-y-auto">
                  {p.alternatives.map((a) => (
                    <li key={a.segment_id} className="flex items-center gap-2.5 rounded-sm bg-surface-1 p-1.5">
                      <div className="aspect-video w-16 shrink-0 overflow-hidden rounded-sm bg-surface-3">
                        {a.frameUrl && <img src={a.frameUrl} alt="" loading="lazy" className="size-full object-cover" />}
                      </div>
                      <div className="flex min-w-0 flex-col gap-0.5">
                        <span className="mono truncate text-timecode-sm text-text">{a.file}</span>
                        <span className="line-clamp-2 text-caption font-normal text-text-muted">{a.note}</span>
                      </div>
                      <Button size="sm" variant="ghost" className="ml-auto" aria-label={`Use ${a.file}`} onClick={() => p.onReplace(a.segment_id)}>
                        Use
                      </Button>
                    </li>
                  ))}
                </ul>
              )}
            </>
          )}
          <div className="flex items-center gap-1.5">
            <Button size="sm" onClick={p.onLock}>
              {p.locked ? <Unlock /> : <Lock />} {p.locked ? "Unlock shot" : "Lock shot"}
            </Button>
            <Button size="sm" variant="ghost" disabled={p.locked} onClick={p.onRemove}>
              <Trash2 /> Remove
            </Button>
            <Button size="sm" variant="ghost" onClick={p.onPlay}>
              <Play /> Play
            </Button>
          </div>
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}

// ------------------------------------------------------------------ BeatCard

export interface BeatCardProps {
  title: string;
  intent: string;
  seconds: number;
  locked: boolean;
  regenerating: boolean;
  /** An inline notice for this beat (a pace or regenerate that couldn't be done). */
  warning?: string | null;
  /** The shot chips (with their popovers). */
  children: ReactNode;
  /** A shot dragged over the card lands at its end. */
  dropAtEnd?: boolean;
  /** A beat dragged over it lands here. */
  beatDrop?: "before" | "after" | null;
  dragging?: boolean;
  canMoveEarlier: boolean;
  canMoveLater: boolean;
  onRegenerate: () => void;
  onPace: (faster: boolean) => void;
  onLockAll: (locked: boolean) => void;
  onMove: (later: boolean) => void;
  /** Drag handlers for the card (beat reordering, and shots dropped on its empty space). */
  onHandleDragStart: (e: DragEvent) => void;
  onDragEnd: () => void;
  onDragOver: (e: DragEvent) => void;
  onDrop: (e: DragEvent) => void;
}

const MENU_ITEM = "cursor-pointer rounded-sm px-2.5 py-1.5 text-small text-text outline-none data-[disabled]:cursor-default data-[disabled]:opacity-40 data-[highlighted]:bg-surface-3";

/** COMPONENTS.md BeatCard: title, intent and length, its shots, and Regenerate, Faster
 * and more; the owner's colour when every shot is locked, a shimmer while it regenerates. */
export function BeatCard(p: BeatCardProps) {
  return (
    <section
      aria-label={p.title}
      aria-busy={p.regenerating || undefined}
      onDragOver={p.onDragOver}
      onDrop={p.onDrop}
      className={cn(
        "relative flex flex-col gap-3 rounded-lg border bg-surface-1 p-4",
        p.locked ? "border-user" : p.dropAtEnd ? "border-accent" : "border-border",
        p.dragging && "opacity-50",
      )}
    >
      {p.beatDrop && <span aria-hidden className={cn("absolute top-0 bottom-0 w-0.5 rounded-full bg-accent", p.beatDrop === "before" ? "-left-[9px]" : "-right-[9px]")} />}
      <div className="flex items-start gap-2">
        <span
          draggable
          role="button"
          tabIndex={-1}
          aria-label={`Drag ${p.title}`}
          onDragStart={p.onHandleDragStart}
          onDragEnd={p.onDragEnd}
          className="cursor-grab pt-0.5 text-text-faint"
        >
          <GripVertical aria-hidden className="size-3.5" />
        </span>
        <div className="flex min-w-0 flex-1 flex-col gap-[3px]">
          <span className="text-subhead font-semibold text-text">{p.title}</span>
          <span className="text-caption font-normal text-text-muted">{p.intent}</span>
        </div>
        {p.locked && (
          <span className="inline-flex items-center gap-[5px] text-micro text-user">
            <Lock aria-hidden className="size-3" /> Locked
          </span>
        )}
        <span className="mono text-timecode-sm text-text">{formatClock(p.seconds)}</span>
      </div>
      {p.regenerating ? (
        <>
          <div className="flex items-center gap-2 text-info">
            <Loader2 aria-hidden className="size-3.5 animate-spin" />
            <span className="text-caption font-normal">Regenerating this beat…</span>
          </div>
          <div aria-hidden className="flex gap-2 overflow-hidden">
            {[0, 1, 2, 3].map((i) => (
              <div key={i} className="aspect-video w-[92px] shrink-0 animate-pulse rounded-sm bg-surface-3" />
            ))}
          </div>
        </>
      ) : (
        <div className="flex min-h-[70px] flex-wrap gap-2">{p.children}</div>
      )}
      {p.warning && <p className="text-caption font-normal text-maybe">{p.warning}</p>}
      <div className="flex gap-1.5">
        <Button size="sm" variant="ghost" disabled={p.regenerating} onClick={p.onRegenerate}>
          <RefreshCw /> Regenerate
        </Button>
        <Button size="sm" variant="ghost" disabled={p.regenerating} onClick={() => p.onPace(true)}>
          Faster
        </Button>
        <DropdownMenu.Root>
          <DropdownMenu.Trigger asChild>
            <Button size="sm" variant="ghost" aria-label="More beat actions" disabled={p.regenerating}>
              <MoreHorizontal />
            </Button>
          </DropdownMenu.Trigger>
          <DropdownMenu.Portal>
            <DropdownMenu.Content align="start" className="z-50 min-w-44 rounded-md border border-border bg-surface-2 p-1 shadow-[0_12px_32px_rgba(0,0,0,0.4)]">
              <DropdownMenu.Item className={MENU_ITEM} onSelect={() => p.onPace(false)}>
                Slower
              </DropdownMenu.Item>
              <DropdownMenu.Item className={MENU_ITEM} onSelect={() => p.onLockAll(!p.locked)}>
                {p.locked ? "Unlock every shot" : "Lock every shot"}
              </DropdownMenu.Item>
              <DropdownMenu.Item className={MENU_ITEM} disabled={!p.canMoveEarlier} onSelect={() => p.onMove(false)}>
                Move earlier
              </DropdownMenu.Item>
              <DropdownMenu.Item className={MENU_ITEM} disabled={!p.canMoveLater} onSelect={() => p.onMove(true)}>
                Move later
              </DropdownMenu.Item>
            </DropdownMenu.Content>
          </DropdownMenu.Portal>
        </DropdownMenu.Root>
      </div>
    </section>
  );
}
