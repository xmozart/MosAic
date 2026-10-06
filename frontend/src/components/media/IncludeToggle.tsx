import { Ban, Pin } from "lucide-react";

import { cn } from "@/lib/cn";

export type Include = "always" | "never" | "none";

export interface IncludeToggleProps {
  value: Include;
  onChange: (value: Include) => void;
}

/** Always / Never include. These are user decisions, so they always use `user` blue. */
export function IncludeToggle({ value, onChange }: IncludeToggleProps) {
  const item = (v: Exclude<Include, "none">, label: string, Icon: typeof Pin, key: string) => {
    const on = value === v;
    return (
      <button
        type="button"
        aria-pressed={on}
        onClick={() => onChange(on ? "none" : v)}
        className={cn(
          "inline-flex items-center gap-1.5 rounded-sm border px-2.5 py-1 text-caption transition-colors duration-150 focus-visible:outline-2 focus-visible:outline-accent",
          on ? "border-user bg-user/15 text-user" : "border-border text-text-muted hover:text-text",
        )}
      >
        <Icon aria-hidden className="size-3.5" />
        {label}
        <kbd className="mono text-timecode-sm opacity-70">{key}</kbd>
      </button>
    );
  };
  return (
    <span className="inline-flex gap-2">
      {item("always", "Always include", Pin, "L")}
      {item("never", "Never include", Ban, "X")}
    </span>
  );
}
