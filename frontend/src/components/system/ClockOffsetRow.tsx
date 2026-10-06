import { Minus, Plus } from "lucide-react";

import { Button } from "@/components/ui/Button";

export interface ClockEvidence {
  reference: string; // "iPhone · Jul 15 10:42"
  device: string; // "GoPro · Jul 15 15:43"
  frames?: [string, string]; // the two matched frames
  moment: string; // "the waterfall trail on Day 2."
}

export interface ClockOffsetRowProps {
  device: string; // "GoPro HERO12 Black"
  summary: string; // "Appears 5 h 00 m ahead"
  offset: string; // mono, signed: "−5 h 00 m"
  evidence: ClockEvidence;
  onStep: (direction: -1 | 1) => void;
  onAccept: () => void;
  onAdjust: () => void;
  onLeave: () => void;
}

/** Evidence pair, stepper, Accept / Adjust / Leave (COMPONENTS.md ClockOffsetRow; S6). */
export function ClockOffsetRow(p: ClockOffsetRowProps) {
  return (
    <section className="flex flex-col gap-4 rounded-lg border border-border bg-surface-1 p-5">
      <header className="flex items-baseline justify-between gap-4">
        <h3 className="text-subhead text-text">{p.device}</h3>
        <span className="text-small text-maybe">{p.summary}</span>
      </header>
      <div className="grid grid-cols-2 gap-3">
        {[p.evidence.reference, p.evidence.device].map((label, i) => (
          <figure key={label} className="flex flex-col gap-1.5">
            <div className="aspect-video overflow-hidden rounded-md bg-surface-3">
              {p.evidence.frames?.[i] && <img src={p.evidence.frames[i]} alt="" className="size-full object-cover" />}
            </div>
            <figcaption className="mono text-timecode-sm text-text-muted">{label}</figcaption>
          </figure>
        ))}
      </div>
      <p className="text-small text-text-muted">
        These look like the same moment: <span className="text-text">{p.evidence.moment}</span>
      </p>
      <div className="flex flex-wrap items-center gap-3">
        <span className="inline-flex items-center rounded-md border border-border bg-surface-3">
          <Button variant="ghost" size="icon" aria-label="Earlier" onClick={() => p.onStep(-1)}>
            <Minus />
          </Button>
          <span aria-live="polite" className="mono min-w-24 text-center text-timecode text-text">
            {p.offset}
          </span>
          <Button variant="ghost" size="icon" aria-label="Later" onClick={() => p.onStep(1)}>
            <Plus />
          </Button>
        </span>
        <Button variant="primary" onClick={p.onAccept}>
          Accept suggestion
        </Button>
        <Button onClick={p.onAdjust}>Adjust</Button>
        <Button variant="ghost" onClick={p.onLeave}>
          Leave as is
        </Button>
      </div>
    </section>
  );
}
