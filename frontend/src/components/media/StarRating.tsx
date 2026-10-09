import { Star } from "lucide-react";

import { cn } from "@/lib/cn";
import { RadioGroup } from "@/components/ui/RadioGroup";

export interface StarRatingProps {
  value: number; // 0–5
  onChange?: (value: number) => void;
  size?: "sm" | "md";
}

/** 1–5 stars; clicking the current value clears it. The accent colour is only for filled
 * stars (COMPONENTS.md). Read-only when there is no `onChange`. The 1–5 and 0 keys belong
 * to the library grid and inspector (S10, S11), which call `onChange`. */
export function StarRating({ value, onChange, size = "md" }: StarRatingProps) {
  const px = size === "sm" ? "size-3" : "size-4";
  if (!onChange) {
    return (
      <span aria-label={`${value} of 5 stars`} className="inline-flex gap-px">
        {[1, 2, 3, 4, 5].map((n) => (
          <Star
            key={n}
            aria-hidden
            className={cn(px, n <= value ? "fill-accent text-accent" : "text-text-faint")}
          />
        ))}
      </span>
    );
  }
  return (
    <RadioGroup label="Rating" as="span" className="inline-flex gap-0.5">
      {[1, 2, 3, 4, 5].map((n) => (
        <button
          key={n}
          type="button"
          role="radio"
          aria-checked={n === value}
          aria-label={`${n} star${n > 1 ? "s" : ""}`}
          onClick={() => onChange(n === value ? 0 : n)}
          className="rounded-sm p-0.5 focus-visible:outline-2 focus-visible:outline-accent"
        >
          <Star className={cn(px, n <= value ? "fill-accent text-accent" : "text-text-faint hover:text-text-muted")} />
        </button>
      ))}
    </RadioGroup>
  );
}
