import { Check, Wrench } from "lucide-react";
import type { Ref } from "react";

import { Button } from "@/components/ui/Button";
import { cn } from "@/lib/cn";

export interface FindingCardProps {
  /** Issue (blocking or warning) or Suggestion (info). */
  issue: boolean;
  timecode: string;
  text: string;
  /** The suggested fix in words; none when there is nothing to apply. */
  fix: string | null;
  canApply: boolean;
  status: "open" | "applied" | "ignored";
  appliedIn: number | null;
  /** Apply and Ignore wait (another change is on its way, or an older version). */
  disabled?: boolean;
  /** From the AI critic rather than the checks. */
  ai?: boolean;
  ref?: Ref<HTMLElement>;
  onSeek: () => void;
  onApply: () => void;
  onIgnore: () => void;
  onFocus?: () => void;
}

/** COMPONENTS.md FindingCard: severity, a timecode that seeks, what is wrong, the
 * suggested fix, and Apply / Ignore; "Applied in vN" once applied. */
export function FindingCard({ ref, ...p }: FindingCardProps) {
  const done = p.status !== "open";
  return (
    <article
      ref={ref}
      tabIndex={-1}
      onFocus={p.onFocus}
      aria-label={`${p.issue ? "Issue" : "Suggestion"} at ${p.timecode}`}
      className={cn(
        "flex flex-col gap-2 rounded-lg border border-border bg-surface-1 p-3.5 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent",
        done && "opacity-60",
      )}
    >
      <div className="flex items-center gap-2">
        <span
          className={cn(
            "inline-flex items-center rounded-full border px-[9px] py-[3px] text-micro font-medium",
            p.issue ? "border-reject bg-reject/12 text-reject" : "border-info bg-info/12 text-info",
          )}
        >
          {p.issue ? "Issue" : "Suggestion"}
        </span>
        <button type="button" onClick={p.onSeek} aria-label={`Go to ${p.timecode}`} className="mono rounded-sm text-timecode-sm text-accent hover:underline focus-visible:outline-2 focus-visible:outline-accent">
          {p.timecode}
        </button>
        {p.ai && <span className="ml-auto text-micro font-normal text-text-faint">AI review</span>}
      </div>
      <p className="text-body text-text">{p.text}</p>
      {p.fix && (
        <div className="flex items-center gap-1.5 text-text-muted">
          <Wrench aria-hidden className="size-3.5 shrink-0" />
          <span className="text-small">{p.fix}</span>
        </div>
      )}
      {p.status === "applied" ? (
        <div className="flex items-center gap-1.5 text-use">
          <Check aria-hidden className="size-3.5" />
          <span className="text-caption font-normal">Applied in v{p.appliedIn}</span>
        </div>
      ) : p.status === "ignored" ? (
        <span className="text-caption font-normal text-text-faint">Ignored</span>
      ) : (
        <div className="flex items-center gap-1.5">
          {p.canApply && (
            <Button size="sm" variant="primary" disabled={p.disabled} onClick={p.onApply}>
              Apply
            </Button>
          )}
          <Button size="sm" variant="ghost" disabled={p.disabled} onClick={p.onIgnore}>
            Ignore
          </Button>
        </div>
      )}
    </article>
  );
}
