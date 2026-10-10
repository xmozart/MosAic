import { Popover } from "radix-ui";
import type { ReactNode } from "react";

import { Button } from "@/components/ui/Button";
import type { JobSummary } from "@/lib/activity";

const KIND: Record<string, string> = {
  analysis: "Analysis",
  generate: "Creating edit",
  scan: "Looking through footage",
  deepen: "Deepening analysis",
  edit: "Creating edit",
  render: "Rendering",
  benchmark: "Measuring this computer",
  search: "Building search",
  models: "Downloading models",
  move: "Moving trip data",
  storage: "Clearing previews",
};

export interface ActivityPopoverProps {
  jobs: JobSummary[];
  projectNames: Record<string, string>;
  onPause: (jobId: number) => void;
  onResume: (jobId: number) => void;
  onCancel: (jobId: number) => void;
  /** Paused at the AI cost limit: resuming needs a higher limit (S0 dialog; ADR 0018). */
  onRaiseLimit?: (jobId: number) => void;
  children: ReactNode; // the trigger (the rail's ring)
  defaultOpen?: boolean;
}

/** Running jobs with progress and Pause/Cancel (COMPONENTS.md ActivityPopover). */
export function ActivityPopover({
  jobs,
  projectNames,
  onPause,
  onResume,
  onCancel,
  onRaiseLimit,
  children,
  defaultOpen,
}: ActivityPopoverProps) {
  return (
    <Popover.Root defaultOpen={defaultOpen}>
      <Popover.Trigger asChild>{children}</Popover.Trigger>
      <Popover.Portal>
        <Popover.Content
          side="right"
          align="end"
          sideOffset={10}
          className="z-50 w-80 rounded-lg border border-border bg-surface-2 p-3 shadow-[0_12px_32px_rgba(0,0,0,0.4)]"
        >
          <p className="mb-2 text-caption text-text-muted">Background activity</p>
          {jobs.length === 0 ? (
            <p className="py-3 text-small text-text-muted">Nothing running.</p>
          ) : (
            <ul className="flex flex-col gap-3">
              {jobs.map((j) => (
                <li key={j.jobId} className="flex flex-col gap-1.5">
                  <div className="flex items-baseline justify-between gap-2">
                    <span className="truncate text-small text-text">
                      {KIND[j.kind] ?? "Working"} · {projectNames[j.projectId] ?? "Project"}
                    </span>
                    <span className="mono text-timecode-sm text-text-muted">{j.pct}%</span>
                  </div>
                  <div className="h-1.5 overflow-hidden rounded-full bg-surface-3">
                    <div className="h-full bg-accent" style={{ width: `${j.pct}%` }} />
                  </div>
                  {j.item && <p className="mono truncate text-timecode-sm text-text-faint">{j.item}</p>}
                  <div className="flex gap-2">
                    {(j.state === "running" || j.state === "pending") && (
                      <Button size="sm" onClick={() => onPause(j.jobId)}>
                        Pause
                      </Button>
                    )}
                    {j.state === "paused" && (
                      <Button size="sm" onClick={() => onResume(j.jobId)}>
                        Resume
                      </Button>
                    )}
                    {j.state === "paused_cost_limit" && onRaiseLimit && (
                      <Button size="sm" onClick={() => onRaiseLimit(j.jobId)}>
                        Raise limit…
                      </Button>
                    )}
                    <Button size="sm" variant="ghost" onClick={() => onCancel(j.jobId)}>
                      Cancel
                    </Button>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}
