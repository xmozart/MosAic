import { StageList } from "@/components/system/StageList";
import { Banner } from "@/components/ui/Banner";
import { Button } from "@/components/ui/Button";
import { cn } from "@/lib/cn";

import { beatInProgress, creatingStages, type CreatingStatus } from "./creating";

export interface CreatingViewProps extends CreatingStatus {
  title: string;
  /** Frame URL of a sample. */
  frame: (sampleId: number) => string;
  onBackground: () => void;
  onCancel: () => void;
  onRetry: () => void;
  onView: () => void;
}

/** S15 Creating edit: the steps on the left, the beats as they are planned on the right.
 * Presentational. */
export function CreatingView(p: CreatingViewProps) {
  const job = p.generation;
  const c = job?.result?.creating;
  const stages = creatingStages(p);
  const working = beatInProgress(c);
  const failed = job?.state === "failed";
  const cancelled = job?.state === "cancelled";
  const made = job?.state === "done";
  return (
    <div className="flex flex-1 items-center justify-center overflow-y-auto p-8">
      <div className="grid w-[980px] grid-cols-[360px_1fr] gap-7">
        <section aria-label="Progress" className="flex flex-col gap-4">
          <h1 className="text-title tracking-[-0.01em] text-text">
            {cancelled ? "Edit cancelled" : failed ? "The edit couldn't be made" : made ? "Your edit is ready" : "Creating your edit"}
          </h1>
          <p className="text-body text-text-muted">{p.title}</p>
          <div className="rounded-lg border border-border bg-surface-1 p-[18px]">
            <StageList stages={stages} />
          </div>
          {failed && (
            <Banner kind="danger" action={<Button size="sm" onClick={p.onRetry}>Try again</Button>}>
              {job?.error ? plainError(job.error) : "Something went wrong."}
            </Banner>
          )}
          {made && p.preview?.state === "failed" && (
            <Banner kind="warning">The edit is ready, but its preview couldn't be rendered. You can render it again from Exports.</Banner>
          )}
          {cancelled && (
            <Banner kind="info" action={<Button size="sm" onClick={p.onRetry}>Start again</Button>}>
              Nothing was saved. The analysis is kept, so starting again is quick.
            </Banner>
          )}
          <div className="flex items-center gap-2">
            {!made &&
              !failed &&
              !cancelled && (
                <>
                  <Button onClick={p.onBackground}>Run in background</Button>
                  <Button variant="ghost" onClick={p.onCancel}>
                    Cancel
                  </Button>
                </>
              )}
          </div>
        </section>
        <section aria-label="Story taking shape" className="flex flex-col gap-2">
          <span className="text-caption font-semibold text-text-faint">Story taking shape</span>
          {!c?.beats?.length
            ? failed || cancelled
              ? <p className="text-caption font-normal text-text-faint">The story wasn't planned yet.</p>
              : [0, 1, 2, 3].map((i) => <div key={i} aria-hidden className="h-[66px] animate-pulse rounded-lg border border-border bg-surface-1" />)
            : c.beats.map((b, i) => (
                <div
                  key={b.beat_id}
                  aria-current={i === working ? "step" : undefined}
                  className={cn(
                    "flex items-center gap-3.5 rounded-lg border bg-surface-1 px-3.5 py-3",
                    i === working ? "border-accent" : "border-border",
                    working !== null && i > working && "opacity-50",
                  )}
                >
                  <div className="flex min-w-0 flex-1 flex-col gap-0.5">
                    <span className="text-body font-semibold text-text">{b.title}</span>
                    <span className="truncate text-caption font-normal text-text-muted">{b.intent}</span>
                  </div>
                  <div className="flex gap-1">
                    {[0, 1, 2].map((k) => {
                      const sid = b.sample_ids?.[k];
                      return sid === undefined ? (
                        <span key={k} aria-hidden className="aspect-video w-16 rounded-sm bg-surface-2" />
                      ) : (
                        <img key={k} src={p.frame(sid)} alt="" loading="lazy" className="aspect-video w-16 rounded-sm object-cover" />
                      );
                    })}
                  </div>
                </div>
              ))}
          {made && (
            <div className="flex justify-end pt-2">
              <Button variant="primary" onClick={p.onView}>
                View storyboard
              </Button>
            </div>
          )}
        </section>
      </div>
    </div>
  );
}

/** A job error in plain words: its first line, without a Python exception's name. */
function plainError(error: string): string {
  const first = error.split("\n")[0]!.replace(/^[A-Za-z]+Error:\s*/, "");
  return first.length > 160 ? `${first.slice(0, 159)}…` : first;
}
