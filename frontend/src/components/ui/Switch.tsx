import { Switch as Radix } from "radix-ui";
import { useId } from "react";

export interface SwitchRowProps {
  label: string;
  description?: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
  disabled?: boolean;
}

/** DS-Components "Controls": a labelled switch row. */
export function SwitchRow({ label, description, checked, onChange, disabled }: SwitchRowProps) {
  const id = useId();
  return (
    <div className="flex items-center justify-between gap-4">
      <label htmlFor={id} className="flex cursor-pointer flex-col gap-0.5">
        <span className="text-body text-text">{label}</span>
        {description && <span className="text-caption font-normal text-text-faint">{description}</span>}
      </label>
      <Radix.Root
        id={id}
        checked={checked}
        onCheckedChange={onChange}
        disabled={disabled}
        className="relative h-[22px] w-[38px] shrink-0 rounded-full border border-border bg-surface-3 transition-colors duration-150 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:opacity-50 data-[state=checked]:border-accent data-[state=checked]:bg-accent"
      >
        <Radix.Thumb className="block size-4 translate-x-[2px] rounded-full bg-text transition-transform duration-150 data-[state=checked]:translate-x-[18px] data-[state=checked]:bg-accent-fg" />
      </Radix.Root>
    </div>
  );
}
