import type { ReactNode } from "react";

export function Kbd({ children }: { children: ReactNode }) {
  return (
    <kbd className="mono inline-flex min-w-5 items-center justify-center rounded-sm border border-border bg-surface-2 px-1.5 text-timecode-sm text-text-muted">
      {children}
    </kbd>
  );
}
