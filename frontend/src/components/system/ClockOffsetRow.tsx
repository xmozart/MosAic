import { ArrowLeftRight, Minus, Plus } from "lucide-react";
import type { KeyboardEvent } from "react";

import { Segmented } from "@/components/ui/Segmented";

export type ClockChoice = "accept" | "adjust" | "leave";

export interface ClockEvidence {
  reference: string; // "iPhone · Jul 15 10:42"
  device: string; // "GoPro · Jul 15 15:43"
  frames?: [string | null, string | null]; // the two matched frames
  moment?: string; // "the waterfall trail on Day 2." when known
}

export interface ClockOffsetRowProps {
  device: string; // "GoPro HERO12 Black"
  summary: string; // "Appears 5 h 00 m ahead", or why there is no suggestion
  offset: string; // mono, signed: "−5 h 00 m"
  evidence?: ClockEvidence; // none: manual stepper only
  choice: ClockChoice;
  onChoice: (c: ClockChoice) => void;
  /** ±1 h, or ±1 min when ``fine`` (Shift with + / −). */
  onStep: (direction: -1 | 1, fine: boolean) => void;
}

const CHOICES = [
  { value: "accept", label: "Accept suggestion" },
  { value: "adjust", label: "Adjust" },
  { value: "leave", label: "Leave as is" },
] as const;

/** One suspect camera: evidence pair, offset stepper, Accept / Adjust / Leave
 * (COMPONENTS.md ClockOffsetRow; S6). + and − adjust the focused stepper. */
export function ClockOffsetRow(p: ClockOffsetRowProps) {
  const onKey = (e: KeyboardEvent) => {
    const dir = e.key === "+" || e.key === "=" ? 1 : e.key === "-" || e.key === "_" ? -1 : 0;
    if (!dir) return;
    e.preventDefault();
    p.onStep(dir, e.shiftKey);
  };
  return (
    <section aria-label={p.device} className="flex flex-col gap-3 rounded-lg border border-border bg-surface-1 p-5">
      <header className="flex flex-col gap-0.5">
        <h3 className="text-subhead font-semibold text-text">{p.device}</h3>
        <p className="text-small text-text-muted">{p.summary}</p>
      </header>
      <div className="flex gap-5">
        {p.evidence && (
          <div className="flex shrink-0 items-center gap-2.5">
            {[p.evidence.reference, p.evidence.device].map((label, i) => (
              <span key={label} className="contents">
                {i === 1 && <ArrowLeftRight aria-hidden className="size-4 text-text-faint" />}
                <figure className="flex w-[150px] flex-col gap-1">
                  <div className="aspect-video overflow-hidden rounded-md bg-surface-3">
                    {p.evidence?.frames?.[i] && <img src={p.evidence.frames[i] ?? undefined} alt="" className="size-full object-cover" />}
                  </div>
                  <figcaption className="mono text-timecode-sm text-text-muted">{label}</figcaption>
                </figure>
              </span>
            ))}
          </div>
        )}
        <div className="flex min-w-0 flex-col items-start gap-2.5">
          {p.evidence && (
            <div className="flex flex-col">
              <p className="text-caption font-normal text-text-muted">These look like the same moment{p.evidence.moment ? ":" : "."}</p>
              {p.evidence.moment && <p className="text-small text-text">{p.evidence.moment}</p>}
            </div>
          )}
          <span
            role="group"
            aria-label={`Clock correction for ${p.device}`}
            onKeyDown={onKey}
            className="inline-flex items-center overflow-hidden rounded-md border border-border"
          >
            <button
              type="button"
              aria-label="Decrease"
              onClick={(e) => p.onStep(-1, e.shiftKey)}
              className="flex h-9 w-[34px] items-center justify-center bg-surface-2 text-text hover:bg-surface-3 focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-accent"
            >
              <Minus aria-hidden className="size-4" />
            </button>
            <span aria-live="polite" className="mono min-w-28 px-3.5 text-center text-timecode text-text">
              {p.offset}
            </span>
            <button
              type="button"
              aria-label="Increase"
              onClick={(e) => p.onStep(1, e.shiftKey)}
              className="flex h-9 w-[34px] items-center justify-center bg-surface-2 text-text hover:bg-surface-3 focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-accent"
            >
              <Plus aria-hidden className="size-4" />
            </button>
          </span>
          <Segmented
            label={`What to do with ${p.device}`}
            value={p.choice}
            onChange={p.onChoice}
            options={p.evidence ? CHOICES : CHOICES.filter((c) => c.value !== "accept")}
          />
        </div>
      </div>
    </section>
  );
}
