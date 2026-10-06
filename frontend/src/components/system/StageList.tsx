import { Check, CirclePause, X } from "lucide-react";

import { cn } from "@/lib/cn";

export type StageState = "pending" | "running" | "done" | "failed" | "paused";

export interface Stage {
  key: string;
  label: string; // plain words: "Making previews", "Finding shots" (VOICE.md)
  state: StageState;
  note?: string; // mono detail: "412 of 412", "2,380 shots"
  pct?: number; // running: 0–100 for the ring
}

function Ring({ pct }: { pct?: number }) {
  const r = 7;
  const c = 2 * Math.PI * r;
  return (
    <svg viewBox="0 0 18 18" className="size-[18px] -rotate-90" aria-hidden>
      <circle cx="9" cy="9" r={r} fill="none" strokeWidth="2" className="stroke-surface-3" />
      <circle
        cx="9"
        cy="9"
        r={r}
        fill="none"
        strokeWidth="2"
        strokeLinecap="round"
        className="stroke-accent"
        strokeDasharray={c}
        strokeDashoffset={c * (1 - (pct ?? 25) / 100)}
      />
    </svg>
  );
}

const ICON: Record<StageState, (s: Stage) => React.ReactNode> = {
  pending: () => <span className="block size-[18px] rounded-full border-2 border-surface-3" />,
  running: (s) => <Ring pct={s.pct} />,
  done: () => (
    <span className="flex size-[18px] items-center justify-center rounded-full bg-use text-bg">
      <Check className="size-3" strokeWidth={3} />
    </span>
  ),
  failed: () => (
    <span className="flex size-[18px] items-center justify-center rounded-full bg-reject text-bg">
      <X className="size-3" strokeWidth={3} />
    </span>
  ),
  paused: () => <CirclePause className="size-[18px] text-maybe" />,
};

function spoken(s: Stage): string {
  if (s.state === "running") return s.pct !== undefined ? `Running, ${Math.round(s.pct)} %` : "Running";
  return { pending: "Not started", done: "Done", failed: "Failed", paused: "Paused" }[s.state];
}

/** Analysis stages with state and a mono note (COMPONENTS.md StageList; S9). */
export function StageList({ stages }: { stages: Stage[] }) {
  return (
    <ol className="flex flex-col gap-2.5">
      {stages.map((s) => (
        <li key={s.key} className="flex items-center gap-3" data-state={s.state}>
          <span role="img" aria-label={spoken(s)}>
            {ICON[s.state](s)}
          </span>
          <span className={cn("text-body", s.state === "pending" ? "text-text-faint" : "text-text")}>{s.label}</span>
          {s.note && <span className="mono ml-auto truncate text-timecode-sm text-text-muted">{s.note}</span>}
        </li>
      ))}
    </ol>
  );
}
