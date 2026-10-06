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
  progress?: ReactNode; // inline progress while its fix runs (cloud download)
}

/** One "needs attention" item: what happened, then the fix (VOICE.md; S5). */
export function UnsupportedRow({ kind, title, reason, actions, progress }: UnsupportedRowProps) {
  const Icon = ICON[kind];
  return (
    <div className="flex items-start gap-3.5 border-b border-border py-3.5 last:border-b-0">
      <Icon aria-hidden className="mt-0.5 size-4 shrink-0 text-maybe" />
      <div className="flex min-w-0 flex-1 flex-col gap-0.5">
        <p className="text-body font-medium text-text">{title}</p>
        <p className="text-caption font-normal text-text-muted">{reason}</p>
        {progress}
      </div>
      {actions && <div className="flex shrink-0 gap-2">{actions}</div>}
    </div>
  );
}
