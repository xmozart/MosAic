import { useId, type InputHTMLAttributes, type ReactNode } from "react";

import { cn } from "@/lib/cn";

export interface TextFieldProps extends InputHTMLAttributes<HTMLInputElement> {
  label?: string;
  icon?: ReactNode;
  /** Costs, sizes, timecodes and filenames are mono (DESIGN_TOKENS.md §3). */
  mono?: boolean;
  hint?: string;
  error?: string;
}

export function TextField({ label, icon, mono, hint, error, className, id, ...props }: TextFieldProps) {
  const auto = useId();
  const inputId = id ?? auto;
  const described = error || hint ? `${inputId}-note` : undefined;
  return (
    <div className={cn("flex flex-col gap-1.5", className)}>
      {label && (
        <label htmlFor={inputId} className="text-caption text-text-muted">
          {label}
        </label>
      )}
      <div className="relative">
        {icon && (
          <span className="pointer-events-none absolute top-1/2 left-[11px] flex -translate-y-1/2 text-text-faint [&_svg]:size-4">
            {icon}
          </span>
        )}
        <input
          id={inputId}
          aria-invalid={error ? true : undefined}
          aria-describedby={described}
          className={cn(
            "h-10 w-full rounded-md border border-border bg-surface-3 px-3 text-body text-text placeholder:text-text-faint focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent",
            icon && "pl-9",
            mono && "mono",
            error && "border-reject",
          )}
          {...props}
        />
      </div>
      {(error || hint) && (
        <p id={described} className={cn("text-caption", error ? "text-reject" : "text-text-faint")}>
          {error ?? hint}
        </p>
      )}
    </div>
  );
}
