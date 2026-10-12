import { Check } from "lucide-react";
import { Checkbox as Radix } from "radix-ui";
import { useId } from "react";

export interface CheckboxRowProps {
  label: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
  disabled?: boolean;
}

/** DS-Components "Controls": a labelled checkbox (S14's editing rules). */
export function CheckboxRow({ label, checked, onChange, disabled }: CheckboxRowProps) {
  const id = useId();
  return (
    <div className="flex items-start gap-2.5">
      <Radix.Root
        id={id}
        checked={checked}
        onCheckedChange={(v) => onChange(v === true)}
        disabled={disabled}
        className="mt-px inline-flex size-[18px] shrink-0 items-center justify-center rounded-sm border-[1.5px] border-border bg-surface-3 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:opacity-50 data-[state=checked]:border-accent data-[state=checked]:bg-accent"
      >
        <Radix.Indicator>
          <Check aria-hidden strokeWidth={2.6} className="size-3 text-accent-fg" />
        </Radix.Indicator>
      </Radix.Root>
      <label htmlFor={id} className="cursor-pointer text-body text-text">
        {label}
      </label>
    </div>
  );
}
