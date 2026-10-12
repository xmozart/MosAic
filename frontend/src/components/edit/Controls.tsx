import { ArrowDown, ArrowUp, GripVertical, Music, Plus, X } from "lucide-react";
import { useState, type KeyboardEvent } from "react";

import { Button } from "@/components/ui/Button";
import { cn } from "@/lib/cn";

// ------------------------------------------------------------------ sliders

/** Arrow keys step a stepped slider; Home/End jump to its ends. */
function stepKeys<T>(e: KeyboardEvent, values: readonly T[], value: T, onChange: (v: T) => void) {
  const i = values.indexOf(value);
  const next =
    e.key === "ArrowRight" || e.key === "ArrowUp"
      ? Math.min(values.length - 1, i + 1)
      : e.key === "ArrowLeft" || e.key === "ArrowDown"
        ? Math.max(0, i - 1)
        : e.key === "Home"
          ? 0
          : e.key === "End"
            ? values.length - 1
            : null;
  if (next === null) return;
  e.preventDefault();
  if (next !== i) onChange(values[next]!);
}

export interface WeightSliderProps<T extends string> {
  label: string;
  value: T;
  /** The five steps in order: Avoid · Less · Neutral · More · Strongly prefer. */
  steps: { value: T; label: string }[];
  onChange: (v: T) => void;
}

/** COMPONENTS.md WeightSlider: five segments filled up to the value, ←/→ to adjust. */
export function WeightSlider<T extends string>({ label, value, steps, onChange }: WeightSliderProps<T>) {
  const i = steps.findIndex((s) => s.value === value);
  const neutral = Math.floor(steps.length / 2);
  return (
    <div className="flex flex-col gap-2 rounded-lg border border-border bg-surface-1 px-4 py-3.5">
      <div className="flex items-center justify-between">
        <span className="text-body font-medium text-text">{label}</span>
        <span className={cn("text-caption font-semibold", i > neutral ? "text-accent" : "text-text-muted")}>{steps[i]?.label}</span>
      </div>
      <div
        role="slider"
        tabIndex={0}
        aria-label={`${label} weight`}
        aria-valuemin={0}
        aria-valuemax={steps.length - 1}
        aria-valuenow={i}
        aria-valuetext={steps[i]?.label}
        onKeyDown={(e) => stepKeys(e, steps.map((s) => s.value), value, onChange)}
        className="flex gap-1 rounded-full focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-accent"
      >
        {steps.map((s, k) => (
          <button
            key={s.value}
            type="button"
            tabIndex={-1}
            aria-label={s.label}
            onClick={() => onChange(s.value)}
            className={cn("h-1.5 flex-1 cursor-pointer rounded-full", k <= i ? "bg-accent" : "bg-surface-3")}
          />
        ))}
      </div>
    </div>
  );
}

export interface PaceSliderProps<T extends string> {
  value: T;
  stops: { value: T; label: string }[];
  readout: string;
  onChange: (v: T) => void;
}

/** COMPONENTS.md PaceSlider: six stops with a live "about n s per shot" readout. */
export function PaceSlider<T extends string>({ value, stops, readout, onChange }: PaceSliderProps<T>) {
  const i = stops.findIndex((s) => s.value === value);
  const pct = (i / (stops.length - 1)) * 100;
  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center gap-1.5">
        <span className="text-small font-medium text-text">Pace</span>
        <span className="mono ml-auto text-timecode-sm text-accent">{readout}</span>
      </div>
      <div
        role="slider"
        tabIndex={0}
        aria-label="Pace"
        aria-valuemin={0}
        aria-valuemax={stops.length - 1}
        aria-valuenow={i}
        aria-valuetext={`${stops[i]?.label}, ${readout}`}
        onKeyDown={(e) => stepKeys(e, stops.map((s) => s.value), value, onChange)}
        className="relative h-1.5 rounded-full bg-surface-3 focus-visible:outline-2 focus-visible:outline-offset-8 focus-visible:outline-accent"
      >
        <div className="h-full rounded-full bg-accent" style={{ width: `${pct}%` }} />
        <div aria-hidden className="absolute top-[-6px] -ml-[9px] size-[18px] rounded-full bg-text" style={{ left: `${pct}%` }} />
      </div>
      <div className="flex justify-between">
        {stops.map((s) => (
          <button
            key={s.value}
            type="button"
            tabIndex={-1}
            onClick={() => onChange(s.value)}
            className={cn("text-micro", s.value === value ? "text-text" : "text-text-faint hover:text-text-muted")}
          >
            {s.label}
          </button>
        ))}
      </div>
    </div>
  );
}

export interface LevelSliderProps {
  label: string;
  /** Whole dB, from ``min`` (quietest) to 0. */
  value: number;
  min: number;
  readout: string;
  onChange: (db: number) => void;
}

/** S14's music level: a dB slider (←/→ one dB, Shift: six). */
export function LevelSlider({ label, value, min, readout, onChange }: LevelSliderProps) {
  const pct = ((value - min) / -min) * 100;
  const set = (db: number) => onChange(Math.max(min, Math.min(0, Math.round(db))));
  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center gap-1.5">
        <span className="text-small text-text">{label}</span>
        <span className="mono ml-auto text-timecode-sm text-text-muted">{readout}</span>
      </div>
      <div
        role="slider"
        tabIndex={0}
        aria-label={label}
        aria-valuemin={min}
        aria-valuemax={0}
        aria-valuenow={value}
        aria-valuetext={readout}
        onKeyDown={(e) => {
          const step = e.shiftKey ? 6 : 1;
          if (e.key === "ArrowRight" || e.key === "ArrowUp") set(value + step);
          else if (e.key === "ArrowLeft" || e.key === "ArrowDown") set(value - step);
          else return;
          e.preventDefault();
        }}
        onClick={(e) => {
          const box = e.currentTarget.getBoundingClientRect();
          set(min + ((e.clientX - box.left) / box.width) * -min);
        }}
        className="h-1.5 cursor-pointer overflow-hidden rounded-full bg-surface-3 focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-accent"
      >
        <div className="h-full rounded-full bg-accent" style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ beats

export interface BeatsEditorProps {
  beats: string[];
  min: number;
  max: number;
  maxChars: number;
  onChange: (beats: string[]) => void;
}

/** S14 step 2's custom beats: the owner's own sections, in order (drag, or the arrows). */
export function BeatsEditor({ beats, min, max, maxChars, onChange }: BeatsEditorProps) {
  const [dragging, setDragging] = useState<number | null>(null);
  const move = (from: number, to: number) => {
    if (to < 0 || to >= beats.length || from === to) return;
    const next = [...beats];
    const [b] = next.splice(from, 1);
    next.splice(to, 0, b!);
    onChange(next);
  };
  return (
    <div className="flex flex-col gap-1.5">
      <span className="text-caption font-medium text-text-muted">Beats (drag to reorder)</span>
      <ol className="grid grid-cols-2 gap-1">
        {beats.map((b, i) => (
          <li
            key={i}
            draggable
            onDragStart={() => setDragging(i)}
            onDragOver={(e) => e.preventDefault()}
            onDrop={() => {
              if (dragging !== null) move(dragging, i);
              setDragging(null);
            }}
            className={cn("flex items-center gap-2.5 rounded-md bg-surface-2 py-1 pr-1 pl-2.5", dragging === i && "opacity-50")}
          >
            <GripVertical aria-hidden className="size-3.5 shrink-0 cursor-grab text-text-faint" />
            <span className="mono text-timecode-sm text-text-muted">{i + 1}</span>
            <input
              aria-label={`Beat ${i + 1}`}
              value={b}
              maxLength={maxChars}
              placeholder="Name this part"
              onChange={(e) => onChange(beats.map((x, k) => (k === i ? e.target.value : x)))}
              className="min-w-0 flex-1 rounded-sm bg-transparent px-1 py-1 text-small text-text placeholder:text-text-faint focus-visible:outline-2 focus-visible:outline-accent"
            />
            <span className="flex">
              <IconButton label={`Move beat ${i + 1} up`} disabled={i === 0} onClick={() => move(i, i - 1)}>
                <ArrowUp />
              </IconButton>
              <IconButton label={`Move beat ${i + 1} down`} disabled={i === beats.length - 1} onClick={() => move(i, i + 1)}>
                <ArrowDown />
              </IconButton>
              <IconButton label={`Remove beat ${i + 1}`} disabled={beats.length <= min} onClick={() => onChange(beats.filter((_, k) => k !== i))}>
                <X />
              </IconButton>
            </span>
          </li>
        ))}
      </ol>
      {beats.length < max && (
        <Button size="sm" variant="ghost" className="self-start" onClick={() => onChange([...beats, ""])}>
          <Plus /> Add a beat
        </Button>
      )}
    </div>
  );
}

function IconButton({ label, disabled, onClick, children }: { label: string; disabled?: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      type="button"
      aria-label={label}
      disabled={disabled}
      onClick={onClick}
      className="inline-flex size-6 items-center justify-center rounded-sm text-text-faint hover:text-text focus-visible:outline-2 focus-visible:outline-accent disabled:opacity-30 [&_svg]:size-3.5"
    >
      {children}
    </button>
  );
}

// ------------------------------------------------------------------ music

export interface TrackInfo {
  name: string;
  duration_ms: number;
  sample_rate: number;
  peaks: number[];
}

export interface MusicTrackCardProps {
  /** Null while the track is being read. */
  track: TrackInfo | null;
  error?: string | null;
  onChange: () => void;
}

/** S14 step 5's track card: name, length and sample rate, a waveform, and Change. */
export function MusicTrackCard({ track, error, onChange }: MusicTrackCardProps) {
  const minutes = track ? `${Math.floor(track.duration_ms / 60000)}:${String(Math.floor((track.duration_ms % 60000) / 1000)).padStart(2, "0")}` : null;
  return (
    <div className="flex flex-col gap-3 rounded-lg border border-border bg-surface-2 p-3.5">
      <div className="flex items-center gap-3">
        <Music aria-hidden className="size-5 shrink-0 text-accent" />
        <div className="flex min-w-0 flex-col gap-0.5">
          {track ? (
            <>
              <span className="truncate text-body font-medium text-text">{track.name}</span>
              <span className="mono text-timecode-sm text-text-muted">
                {minutes} · {(track.sample_rate / 1000).toFixed(1).replace(/\.0$/, "")} kHz
              </span>
            </>
          ) : error ? (
            <span className="text-small text-reject">{error}</span>
          ) : (
            <span aria-label="Reading the track" className="h-4 w-40 animate-pulse rounded-sm bg-surface-3" />
          )}
        </div>
        <Button size="sm" variant="ghost" className="ml-auto" onClick={onChange}>
          Change
        </Button>
      </div>
      <div aria-hidden className="flex h-7 items-center gap-0.5">
        {(track?.peaks ?? Array.from({ length: 48 }, () => 8)).map((p, i) => (
          <span key={i} className={cn("flex-1 rounded-sm", track ? "bg-accent" : "bg-surface-3")} style={{ height: `${Math.max(8, p)}%` }} />
        ))}
      </div>
    </div>
  );
}
