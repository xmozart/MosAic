import { ToggleGroup } from "radix-ui";

import { cn } from "@/lib/cn";

export interface SegmentedOption<T extends string> {
  value: T;
  label: string;
  hint?: string; // keyboard hint shown after the label (e.g. "U")
}

export interface SegmentedProps<T extends string> {
  value: T | undefined;
  options: readonly SegmentedOption<T>[];
  onChange: (value: T) => void;
  label: string;
  className?: string;
  disabled?: boolean;
}

/** DS-Components "Chronology": a single-choice segmented control. */
export function Segmented<T extends string>({ value, options, onChange, label, className, disabled }: SegmentedProps<T>) {
  return (
    <ToggleGroup.Root
      type="single"
      aria-label={label}
      disabled={disabled}
      value={value ?? ""}
      onValueChange={(v) => v && onChange(v as T)}
      className={cn("inline-flex gap-0.5 rounded-md border border-border bg-surface-3 p-[3px]", className)}
    >
      {options.map((o) => (
        <ToggleGroup.Item
          key={o.value}
          value={o.value}
          className="inline-flex items-center gap-2 rounded-md px-3.5 py-[7px] text-small font-medium text-text-muted transition-colors duration-150 enabled:hover:text-text focus-visible:outline-2 focus-visible:outline-accent disabled:cursor-not-allowed disabled:opacity-50 data-[state=on]:bg-surface-1 data-[state=on]:text-text data-[state=on]:shadow-[0_1px_2px_rgba(0,0,0,0.35)]"
        >
          {o.label}
          {o.hint && <kbd className="mono text-timecode-sm text-text-faint">{o.hint}</kbd>}
        </ToggleGroup.Item>
      ))}
    </ToggleGroup.Root>
  );
}
