import { CloudOff, FileWarning, Orbit, TriangleAlert } from "lucide-react";
import type { ReactNode } from "react";

export type UnsupportedKind = "unreadable" | "limited" | "cloud" | "damaged";

const ICON: Record<UnsupportedKind, typeof FileWarning> = {
  unreadable: FileWarning,
  limited: Orbit,
  cloud: CloudOff,
  damaged: TriangleAlert,
};

export interface UnsupportedRowProps {
  kind: UnsupportedKind;
  title: string; // "3 Nikon N-RAW clips can't be read"
  reason: string; // "Export them as MP4 from NX Studio, then rescan."
  actions?: ReactNode; // one primary fix, then secondary
}

/** One "needs attention" item: what happened, then the fix (VOICE.md; S5). */
export function UnsupportedRow({ kind, title, reason, actions }: UnsupportedRowProps) {
  const Icon = ICON[kind];
  return (
    <div className="flex items-start gap-3 rounded-md border border-border bg-surface-1 p-3.5">
      <Icon aria-hidden className="mt-0.5 size-4 shrink-0 text-maybe" />
      <div className="flex min-w-0 flex-1 flex-col gap-0.5">
        <p className="text-body text-text">{title}</p>
        <p className="text-small text-text-muted">{reason}</p>
      </div>
      {actions && <div className="flex shrink-0 gap-2">{actions}</div>}
    </div>
  );
}
