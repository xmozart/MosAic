import { Check, Contrast, User, X } from "lucide-react";

import { cn } from "@/lib/cn";
import type { DecidedBy, Disposition } from "@/lib/domain";

const STYLE: Record<Disposition, { icon: typeof Check; outline: string; fill: string }> = {
  USE: { icon: Check, outline: "border-use text-use", fill: "bg-use" },
  MAYBE: { icon: Contrast, outline: "border-maybe text-maybe", fill: "bg-maybe" },
  REJECT: { icon: X, outline: "border-reject text-reject", fill: "bg-reject" },
};

export interface DispositionChipProps {
  value: Disposition;
  by: DecidedBy;
  size?: "sm" | "md";
  /** On a thumbnail: the outlined AI chip gets a dark backing for legibility. */
  onMedia?: boolean;
  className?: string;
}

/**
 * The AI-vs-you rule (DESIGN_TOKENS.md §5, M2 acceptance 8): an AI suggestion is an
 * outlined chip with an "AI" tag; the user's decision is a filled chip with a `user`-blue
 * person badge. Never colour alone: icon + word every time.
 */
export function DispositionChip({ value, by, size = "md", onMedia, className }: DispositionChipProps) {
  const s = STYLE[value];
  const Icon = s.icon;
  const text = size === "sm" ? "text-micro" : "text-caption";
  if (by === "ai") {
    return (
      <span
        data-variant="ai"
        role="img"
        aria-label={`${value}, suggested by AI`}
        className={cn(
          "inline-flex items-center gap-1 rounded-sm border-[1.5px] px-1.5 py-px font-bold tracking-[0.02em]",
          s.outline,
          text,
          onMedia ? "bg-media-chip" : "bg-transparent",
          className,
        )}
      >
        <Icon aria-hidden className="size-3" strokeWidth={2.2} />
        {value}
        <span className="ml-0.5 rounded-[3px] border border-current px-[3px] text-tag font-semibold opacity-85">
          AI
        </span>
      </span>
    );
  }
  return (
    <span
      data-variant="user"
      role="img"
      aria-label={`${value}, set by you`}
      className={cn("inline-flex items-center gap-1", className)}
    >
      <span
        className={cn(
          "inline-flex items-center gap-1 rounded-sm py-0.5 pr-[7px] pl-1.5 font-bold tracking-[0.02em] text-bg",
          s.fill,
          text,
        )}
      >
        <Icon aria-hidden className="size-3" strokeWidth={2.2} />
        {value}
      </span>
      <span
        title="Set by you"
        data-badge="user"
        className={cn(
          "inline-flex items-center justify-center rounded-full bg-user text-bg",
          size === "sm" ? "size-[18px]" : "size-[19px]",
        )}
      >
        <User aria-hidden className="size-2.5" strokeWidth={2.4} />
      </span>
    </span>
  );
}
