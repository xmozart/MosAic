import type { ReactNode } from "react";

import { cn } from "@/lib/cn";

export interface ChoiceCardProps {
  selected: boolean;
  title: string;
  text: string;
  onClick: () => void;
  icon?: ReactNode;
  badge?: string; // "Recommended"
}

/** COMPONENTS.md ChoiceCard: one option of a card radio group (S1 AI mode, S22 privacy
 * mode). Put it in a `RadioGroup`, which makes the group one Tab stop. */
export function ChoiceCard({ selected, title, text, onClick, icon, badge }: ChoiceCardProps) {
  return (
    <button
      type="button"
      role="radio"
      aria-checked={selected}
      onClick={onClick}
      className={cn(
        "flex flex-col gap-2 rounded-lg border-[1.5px] p-[18px] text-left text-text focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent",
        selected ? "border-accent bg-accent-soft" : "border-border bg-surface-1 hover:border-text-faint",
      )}
    >
      <span className="flex items-center gap-2.5">
        <span className={cn("flex size-[18px] items-center justify-center rounded-full border-[1.5px]", selected ? "border-accent" : "border-border")}>
          {selected && <span className="size-[9px] rounded-full bg-accent" />}
        </span>
        <span className="text-subhead font-semibold">{title}</span>
        {badge && <span className="ml-auto rounded-full border border-accent px-2 py-0.5 text-micro font-medium text-accent">{badge}</span>}
        {icon && <span className="ml-auto text-text-muted">{icon}</span>}
      </span>
      <span className="text-small text-text-muted">{text}</span>
    </button>
  );
}
