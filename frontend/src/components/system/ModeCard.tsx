import { cn } from "@/lib/cn";

export interface ModeCardProps {
  title: string;
  description: string;
  estimate: string; // mono: "About 1 h 40 m · $2–4 · 18 GB"
  loading?: boolean; // the estimate is still being computed: a skeleton line
  recommended?: boolean;
  selected?: boolean;
  onSelect?: () => void;
}

/** An analysis mode with its estimate line (COMPONENTS.md ModeCard; S8). */
export function ModeCard({ title, description, estimate, loading, recommended, selected, onSelect }: ModeCardProps) {
  return (
    <button
      type="button"
      role="radio"
      aria-checked={selected}
      onClick={onSelect}
      className={cn(
        "flex flex-col gap-2 rounded-lg border bg-surface-1 p-4 text-left transition-colors duration-150 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent",
        selected ? "border-accent bg-accent-soft" : "border-border hover:bg-surface-2",
      )}
    >
      <span className="flex items-center gap-2">
        <span className="text-subhead text-text">{title}</span>
        {recommended && (
          <span className="rounded-full border border-accent bg-accent-soft px-2 py-px text-micro text-accent">Recommended</span>
        )}
      </span>
      <span className="text-small text-text-muted">{description}</span>
      {loading ? (
        <span role="status" className="block h-[18px] w-3/4 animate-pulse rounded-sm bg-surface-3">
          <span className="sr-only">Estimating</span>
        </span>
      ) : (
        <span className="mono text-timecode text-text">{estimate}</span>
      )}
    </button>
  );
}
