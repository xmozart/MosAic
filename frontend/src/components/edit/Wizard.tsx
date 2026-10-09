import { Check, Clapperboard, Film, Gauge, Plus, Sparkles, StickyNote, Timer, Wand2 } from "lucide-react";
import type { ReactNode } from "react";

import { Button } from "@/components/ui/Button";
import { cn } from "@/lib/cn";
import { RadioGroup } from "@/components/ui/RadioGroup";


// ------------------------------------------------------------------ step nav

export interface WizardStep {
  id: number;
  label: string;
  /** Steps built in a later milestone show, but can't be opened (ADR 0048). */
  later?: boolean;
}

/** COMPONENTS.md WizardStepNav: six steps; done steps show ✓ and are clickable. */
export function WizardStepNav({ steps, current, done, onStep }: { steps: WizardStep[]; current: number; done: Set<number>; onStep: (id: number) => void }) {
  return (
    <nav aria-label="Edit steps" className="flex w-[230px] shrink-0 flex-col gap-1 border-r border-border px-3.5 py-5">
      <span className="px-3 pb-2 text-caption font-semibold text-text-faint">New edit</span>
      {steps.map((s) => {
        const active = s.id === current;
        const finished = done.has(s.id) && !active;
        return (
          <button
            key={s.id}
            type="button"
            disabled={s.later}
            aria-current={active ? "step" : undefined}
            title={s.later ? "Coming in a later update" : undefined}
            onClick={() => onStep(s.id)}
            className={cn(
              "flex items-center gap-3 rounded-md px-3 py-2.5 text-left focus-visible:outline-2 focus-visible:outline-accent disabled:cursor-not-allowed",
              active ? "bg-surface-2 text-text" : "text-text-muted hover:text-text",
              s.later && "opacity-60 hover:text-text-muted",
            )}
          >
            <span
              className={cn(
                "inline-flex size-6 shrink-0 items-center justify-center rounded-full",
                active || finished ? "bg-accent text-accent-fg" : "bg-surface-3 text-text-muted",
              )}
            >
              {finished ? <Check aria-hidden className="size-3.5" /> : <span className="text-micro font-bold">{s.id}</span>}
            </span>
            <span className={cn("text-body", active ? "font-semibold" : "font-medium")}>{s.label}</span>
          </button>
        );
      })}
      {steps.some((s) => s.later) && (
        <p className="px-3 pt-3 text-caption font-normal text-text-faint">
          Steps {steps.filter((s) => s.later).map((s) => s.id).join(", ")} arrive in a later update.
        </p>
      )}
    </nav>
  );
}

// ------------------------------------------------------------------ choices

/** A selectable chip with the wizard's selected style (accent-soft + accent border). */
export function ChoiceChip({ selected, onClick, children, label }: { selected: boolean; onClick: () => void; children: ReactNode; label?: string }) {
  return (
    <button
      type="button"
      role="radio"
      aria-checked={selected}
      aria-label={label}
      onClick={onClick}
      className={cn(
        "rounded-md border-[1.5px] px-3.5 py-[9px] text-small font-semibold text-text focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent",
        selected ? "border-accent bg-accent-soft" : "border-border bg-surface-1 hover:border-text-faint",
      )}
    >
      {children}
    </button>
  );
}

/** COMPONENTS.md DurationChips: 15 s … 20 min, plus Custom. */
export function DurationChips({ options, value, custom, onChange, onCustom, format }: { options: readonly number[]; value: number; custom: boolean; onChange: (s: number) => void; onCustom: () => void; format: (s: number) => string }) {
  return (
    <RadioGroup label="Length" className="flex flex-wrap items-center gap-2">
      {options.map((s) => (
        <ChoiceChip key={s} selected={!custom && s === value} onClick={() => onChange(s)}>
          {format(s)}
        </ChoiceChip>
      ))}
      <ChoiceChip selected={custom} onClick={onCustom}>
        Custom
      </ChoiceChip>
    </RadioGroup>
  );
}

export interface AspectOption<T extends string> {
  value: T;
  label: string;
  w: number;
  h: number;
  disabled?: boolean;
}

/** COMPONENTS.md AspectPicker: each option draws its frame. */
export function AspectPicker<T extends string>({ options, value, onChange }: { options: AspectOption<T>[]; value: T; onChange: (v: T) => void }) {
  return (
    <RadioGroup label="Shape" className="flex flex-wrap items-center gap-2">
      {options.map((o) => {
        const on = o.value === value;
        return (
          <button
            key={o.value}
            type="button"
            role="radio"
            aria-checked={on}
            disabled={o.disabled}
            title={o.disabled ? "Coming in a later update" : undefined}
            onClick={() => onChange(o.value)}
            className={cn(
              "flex w-24 flex-col items-center gap-2 rounded-md border-[1.5px] p-3 text-text focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:cursor-not-allowed disabled:opacity-50",
              on ? "border-accent bg-accent-soft" : "border-border bg-surface-1 enabled:hover:border-text-faint",
            )}
          >
            <span className="flex h-[52px] items-center">
              <span
                aria-hidden
                style={{ width: o.w, height: o.h }}
                className={cn("block rounded-sm border-2", on ? "border-accent" : "border-text-muted")}
              />
            </span>
            <span className="text-caption font-semibold">{o.label}</span>
          </button>
        );
      })}
    </RadioGroup>
  );
}

/** COMPONENTS.md StoryPresetCard: a collage of the owner's own matching clips. Without
 * frames (``custom``, or none yet) a dashed frame stands in. */
export function StoryPresetCard({ label, frames, selected, custom, loading, onClick }: { label: string; frames: string[]; selected: boolean; custom?: boolean; loading?: boolean; onClick: () => void }) {
  return (
    <button
      type="button"
      role="radio"
      aria-checked={selected}
      onClick={onClick}
      className={cn(
        "flex flex-col gap-2 rounded-lg border-[1.5px] px-2 pt-2 pb-3 text-left text-text focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent",
        selected ? "border-accent bg-accent-soft" : "border-border bg-surface-1 hover:border-text-faint",
      )}
    >
      {custom || (!loading && frames.length === 0) ? (
        <span className="flex aspect-video items-center justify-center rounded-md border-[1.5px] border-dashed border-border text-text-muted">
          {custom ? <Plus aria-hidden className="size-5" /> : <Film aria-hidden className="size-5" />}
        </span>
      ) : (
        <span aria-hidden className={cn("grid aspect-video grid-cols-[2fr_1fr] grid-rows-2 gap-0.5 overflow-hidden rounded-md", loading && "animate-pulse bg-surface-2")}>
          {frames.slice(0, 3).map((src, i) => (
            <img key={src} src={src} alt="" loading="lazy" className={cn("size-full object-cover", i === 0 && "row-span-2")} />
          ))}
          {!loading && frames.length > 0 && frames.length < 3 && (
            <span className={cn("bg-surface-2", frames.length === 1 && "row-span-2")} />
          )}
        </span>
      )}
      <span className="flex items-center gap-1.5 px-1 text-small font-semibold">
        {selected && <Check aria-hidden className="size-3.5 text-accent" />}
        {label}
      </span>
    </button>
  );
}

// ------------------------------------------------------------------ summary

const ICONS = [Clapperboard, Film, Timer, Gauge, Wand2, StickyNote];

/** COMPONENTS.md EditSummaryPanel (340 px): plain-language lines from the request, warnings,
 * the estimate and the always-available primary "Create edit". */
export function EditSummaryPanel({ title, lines, warnings, estimate, estimatePending, creating, disabled, onCreate }: { title: string; lines: string[]; warnings?: ReactNode; estimate: string | null; estimatePending?: boolean; creating: boolean; disabled?: boolean; onCreate: () => void }) {
  return (
    <aside aria-label="Your edit" className="flex w-[340px] shrink-0 flex-col gap-4 border-l border-border bg-surface-1 p-[22px]">
      <span className="text-caption font-semibold text-text-faint">Your edit</span>
      <h2 className="text-heading tracking-[-0.01em] text-text">{title}</h2>
      <ul className="flex flex-col gap-2.5">
        {lines.map((l, i) => {
          const Icon = ICONS[Math.min(i, ICONS.length - 1)]!;
          return (
            <li key={l} className="flex items-start gap-2.5 text-body text-text">
              <Icon aria-hidden className="mt-0.5 size-4 shrink-0 text-text-muted" />
              <span>{l}</span>
            </li>
          );
        })}
      </ul>
      <span className="flex-1" />
      {warnings}
      <div className="flex flex-col gap-0.5 rounded-lg border border-border bg-surface-2 p-3.5">
        <span className="text-caption font-normal text-text-faint">Estimate</span>
        {estimate ? (
          <span aria-busy={estimatePending || undefined} className={cn("mono text-timecode text-text transition-opacity duration-150", estimatePending && "opacity-50")}>
            {estimate}
          </span>
        ) : (
          <span aria-label="Estimating" className="my-0.5 h-4 w-40 animate-pulse rounded-sm bg-surface-3" />
        )}
      </div>
      <Button variant="primary" size="lg" className="w-full" disabled={creating || disabled} onClick={onCreate}>
        <Sparkles /> {creating ? "Creating…" : "Create edit"}
      </Button>
    </aside>
  );
}
