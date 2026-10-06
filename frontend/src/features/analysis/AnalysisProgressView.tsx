import { useState } from "react";

import { StageList, type Stage } from "@/components/system/StageList";
import { Banner } from "@/components/ui/Banner";
import { Button } from "@/components/ui/Button";
import { plural } from "@/lib/format";

import { timeLeft, type JobInfo, type Progress } from "./model";

const title = (mode: string | null) => (mode ? mode[0]!.toUpperCase() + mode.slice(1) : "");

const usd = (x: number) => `$${x.toFixed(2)}`;

export interface AnalysisProgressViewProps {
  progress: Progress;
  job: JobInfo;
  sheetUrl: (mosaicId: number) => string;
  busy?: boolean;
  onPause: () => void;
  onResume: () => void;
  onCancel: () => void;
  onRaiseLimit: () => void; // Keep paused only dismisses the notice
  onRetry: () => void;
  onRestart: () => void; // a cancelled run: start it again, reusing everything done
  onDetails: () => void;
  onOpenLibrary: () => void;
  onCreateEdit: () => void;
}

function Overall(p: AnalysisProgressViewProps) {
  const { progress: pr, job } = p;
  const pct = Math.round(job.progress?.pct ?? 0);
  const failed = pr.failures.count;
  const look = pr.steps.find((s) => s.key === "look")?.note;
  if (job.state === "done") {
    return (
      <section className="flex flex-col gap-3 rounded-lg border border-border bg-surface-1 p-[22px]">
        <h2 className="text-heading text-text">{failed ? `Done, with ${plural(failed, "clip")} skipped` : "Analysis complete"}</h2>
        <p className="text-small text-text-muted">
          {failed
            ? pr.failures.items
                .slice(0, 3)
                .map((f) => `${f.file ?? "A clip"} ${f.reason}`)
                .join(" · ")
            : [usd(job.cost_usd), look].filter(Boolean).join(" · ")}
        </p>
        <div className="flex gap-2">
          {failed > 0 && (
            <Button size="sm" disabled={p.busy} onClick={p.onRetry}>
              Retry failed
            </Button>
          )}
          <Button size="sm" variant="primary" onClick={p.onOpenLibrary}>
            Open library
          </Button>
        </div>
      </section>
    );
  }
  if (job.state === "cancelled" || job.state === "failed") {
    return (
      <section className="flex flex-col gap-3 rounded-lg border border-border bg-surface-1 p-[22px]">
        <h2 className="text-heading text-text">{job.state === "cancelled" ? "Analysis cancelled" : "Analysis stopped"}</h2>
        <p className="text-small text-text-muted">Everything finished so far is kept.</p>
        <div className="flex gap-2">
          {job.state === "failed" && failed > 0 ? (
            <Button size="sm" disabled={p.busy} onClick={p.onRetry}>
              Retry failed
            </Button>
          ) : (
            <Button size="sm" disabled={p.busy} onClick={p.onRestart}>
              Resume analysis
            </Button>
          )}
        </div>
      </section>
    );
  }
  const limit = job.cost_limit_usd;
  return (
    <section className="flex flex-col gap-3 rounded-lg border border-border bg-surface-1 p-[22px]">
      <div className="flex items-center gap-[18px]">
        <span className="mono text-display text-text">{pct}%</span>
        <div className="flex flex-col gap-0.5">
          <span className="text-small font-medium text-text">{pr.kind === "deepen" ? `Deepening · ${title(pr.mode)}` : `${title(pr.mode)} analysis`}</span>
          <span className="text-caption font-normal text-text-muted">
            {job.state === "paused"
              ? "Paused · you can keep browsing"
              : job.state === "paused_cost_limit"
                ? "Paused at your cost limit"
                : job.progress?.eta
                  ? timeLeft(job.progress.eta.ms)
                  : "Working out how long this takes…"}
          </span>
        </div>
        <div className="ml-auto flex flex-col items-end gap-0.5">
          <span className="text-caption font-normal text-text-muted">AI cost so far</span>
          <span className="flex items-baseline gap-1.5">
            <span className="mono text-subhead text-text">{usd(job.cost_usd)}</span>
            {limit !== null && <span className="mono text-timecode-sm text-text-muted">/ {usd(limit)} limit</span>}
          </span>
        </div>
      </div>
      <div
        role="progressbar"
        aria-label="Analysis"
        aria-valuenow={pct}
        aria-valuemin={0}
        aria-valuemax={100}
        className="h-2 overflow-hidden rounded-full bg-surface-3"
      >
        <div className="h-full rounded-full bg-accent" style={{ width: `${pct}%` }} />
      </div>
      <div className="flex items-center gap-2">
        <span className="text-caption font-normal text-text-muted">
          {pr.clips.done.toLocaleString("en-US")} of {plural(pr.clips.total, "clip")} fully analyzed
        </span>
        <span className="ml-auto flex gap-1">
          {job.state === "running" && (
            <Button size="sm" disabled={p.busy} onClick={p.onPause}>
              Pause
            </Button>
          )}
          {job.state === "paused" && (
            <Button size="sm" variant="primary" disabled={p.busy} onClick={p.onResume}>
              Resume
            </Button>
          )}
          <Button size="sm" variant="ghost" disabled={p.busy} onClick={p.onCancel}>
            {job.state === "running" ? "Cancel" : "Cancel analysis"}
          </Button>
        </span>
      </div>
    </section>
  );
}

/** S9 Analysis progress: a calm view of a long run (S9, S9b). Presentational. */
export function AnalysisProgressView(p: AnalysisProgressViewProps) {
  const { progress: pr, job } = p;
  const steps: Stage[] = pr.steps.map((s) => ({
    key: s.key,
    label: s.label,
    state: s.state,
    note: s.note ?? undefined,
    pct: s.state === "running" ? s.pct : undefined,
  }));
  const active = !["done", "failed", "cancelled"].includes(job.state);
  // "Keep paused" hides the notice for this pause only: a new limit reached shows it again.
  const pauseKey = `${job.state}:${job.cost_limit_usd ?? ""}`;
  const [kept, setKept] = useState<string | null>(null);
  const keepPaused = kept === pauseKey;
  return (
    <div className="flex flex-1 flex-col gap-5 overflow-y-auto px-8 py-7">
      {pr.ready_to_browse && active && (
        <div role="status" className="flex items-center gap-4 rounded-lg border border-accent bg-accent-soft px-[18px] py-4">
          <div className="flex flex-col gap-0.5">
            <p className="text-subhead font-semibold text-text">Your footage is ready to browse and edit</p>
            <p className="text-small text-text-muted">Deeper analysis continues in the background. Early edits are marked preliminary.</p>
          </div>
          <span className="ml-auto flex gap-2">
            <Button onClick={p.onOpenLibrary}>Open library</Button>
            <Button variant="primary" onClick={p.onCreateEdit}>
              Create edit
            </Button>
          </span>
        </div>
      )}
      {job.state === "paused_cost_limit" && !keepPaused && (
        <Banner
          kind="warning"
          action={
            <span className="flex gap-1">
              <Button size="sm" variant="primary" onClick={p.onRaiseLimit}>
                Raise limit
              </Button>
              <Button size="sm" variant="ghost" onClick={() => setKept(pauseKey)}>
                Keep paused
              </Button>
            </span>
          }
        >
          Analysis paused at your {job.cost_limit_usd !== null ? usd(job.cost_limit_usd) : ""} limit. Everything done so far is kept.
        </Banner>
      )}
      <div className="grid grid-cols-2 items-start gap-5">
        <div className="flex flex-col gap-5">
          <Overall {...p} />
          <section aria-label="Stages" className="rounded-lg border border-border bg-surface-1 p-4">
            <StageList stages={steps} />
          </section>
        </div>
        <div className="flex flex-col gap-5">
          <section aria-label="Now looking at" className="flex flex-col gap-3 rounded-lg border border-border bg-surface-1 p-[18px]">
            <header className="flex items-center gap-2">
              <h2 className="text-subhead font-semibold text-text">Understanding scenes</h2>
              <span className="inline-flex rounded-full border border-info px-2 py-0.5 text-micro font-medium text-info">AI</span>
            </header>
            {pr.live ? (
              <>
                <img
                  src={p.sheetUrl(pr.live.mosaic_id)}
                  alt={`Contact sheet of ${pr.live.tiles} frames, labelled T01 to T${String(pr.live.tiles).padStart(2, "0")}`}
                  className="w-full rounded-md bg-surface-3"
                />
                {pr.live.description && <p className="text-small text-text italic">“{pr.live.description}”</p>}
                <p className="mono text-timecode-sm text-text-muted">{[pr.live.file, pr.live.day ? `Day ${pr.live.day}` : null].filter(Boolean).join(" · ")}</p>
              </>
            ) : (
              <p className="text-small text-text-muted">Contact sheets appear here when the AI starts describing scenes.</p>
            )}
          </section>
          {pr.failures.count > 0 && active && (
            <Banner
              kind="danger"
              action={
                <span className="flex gap-1">
                  <Button size="sm" variant="ghost" onClick={p.onDetails}>
                    Details
                  </Button>
                  <Button size="sm" disabled={p.busy} onClick={p.onRetry}>
                    Retry
                  </Button>
                </span>
              }
            >
              {plural(pr.failures.count, "clip")} couldn't be processed.
            </Banner>
          )}
        </div>
      </div>
    </div>
  );
}
