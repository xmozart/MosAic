import { Download, RotateCw, SkipForward } from "lucide-react";
import type { ReactNode } from "react";

import { Banner } from "@/components/ui/Banner";
import { Button } from "@/components/ui/Button";
import { Segmented } from "@/components/ui/Segmented";
import { cn } from "@/lib/cn";

import { FILTERS, STATUS_TONE, STATUS_WORDS, clockTime, cost, duration, tokens, type TaskDetail, type TaskRow, type TaskStatus } from "./model";

export interface DiagnosticsViewProps {
  filter: "all" | TaskStatus;
  onFilter: (f: "all" | TaskStatus) => void;
  projects: { id: string; name: string }[];
  project: string | null;
  onProject: (id: string | null) => void;
  rows: TaskRow[] | undefined;
  error?: boolean;
  onRetryLoad?: () => void;
  hasMore?: boolean;
  onMore?: () => void;
  loadingMore?: boolean;
  selected: number | null;
  onSelect: (id: number) => void;
  detail: TaskDetail | undefined;
  detailError?: boolean;
  onRetryTask: (id: number) => void;
  onSkipTask: (id: number) => void;
  acting?: boolean;
  onExport: () => void;
  exporting?: boolean;
}

/** S23 Diagnostics: the task table beside one task's detail. Presentational. */
export function DiagnosticsView(p: DiagnosticsViewProps) {
  return (
    <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto px-7 py-6">
      <div className="flex items-center gap-3">
        <div className="flex flex-col gap-[3px]">
          <h1 className="text-title tracking-[-0.01em] text-text">Diagnostics</h1>
          <p className="text-small text-text-muted">For troubleshooting. API keys are never shown or exported.</p>
        </div>
        <Button className="ml-auto" disabled={p.exporting} onClick={p.onExport}>
          <Download /> {p.exporting ? "Preparing…" : "Export diagnostic bundle (redacted)"}
        </Button>
      </div>
      <div className="flex flex-wrap items-center gap-3">
        <Segmented label="Status" value={p.filter} onChange={p.onFilter} options={FILTERS} />
        <label className="flex items-center gap-2 text-caption text-text-muted">
          Trip
          <select
            value={p.project ?? ""}
            onChange={(e) => p.onProject(e.target.value || null)}
            className="h-9 rounded-md border border-border bg-surface-3 px-2.5 text-small text-text focus-visible:outline-2 focus-visible:outline-accent"
          >
            <option value="">All trips</option>
            {p.projects.map((x) => (
              <option key={x.id} value={x.id}>
                {x.name}
              </option>
            ))}
          </select>
        </label>
      </div>
      <div className="grid grid-cols-[1.4fr_1fr] items-start gap-5">
        <div className="flex flex-col gap-2 rounded-lg border border-border bg-surface-1 p-2">
          {p.error ? (
            <Banner
              kind="danger"
              action={
                <Button size="sm" onClick={p.onRetryLoad}>
                  Try again
                </Button>
              }
            >
              We couldn't load the tasks.
            </Banner>
          ) : !p.rows ? (
            <div aria-label="Loading tasks" className="h-64 animate-pulse rounded-md bg-surface-2" />
          ) : p.rows.length === 0 ? (
            <p className="p-6 text-center text-body text-text-muted">No tasks {p.filter === "all" ? "yet" : `are ${FILTERS.find((f) => f.value === p.filter)?.label.toLowerCase()}`}.</p>
          ) : (
            <table className="w-full border-collapse">
              <thead>
                <tr className="text-left text-micro text-text-faint">
                  {["Task", "Input", "Status", "Tool / model", "Time", "Tokens", "Cost"].map((h) => (
                    <th key={h} scope="col" className="border-b border-border px-3 py-2 font-semibold">
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {p.rows.map((r) => (
                  <tr
                    key={r.task_id}
                    data-selected={r.task_id === p.selected || undefined}
                    onClick={() => p.onSelect(r.task_id)}
                    className={cn("mono cursor-pointer text-timecode-sm text-text", r.task_id === p.selected ? "bg-surface-2" : "hover:bg-surface-2/60")}
                  >
                    <td className="border-b border-border px-3 py-2">
                      <button
                        type="button"
                        aria-current={r.task_id === p.selected ? "true" : undefined}
                        className="rounded-sm text-left focus-visible:outline-2 focus-visible:outline-accent"
                        onClick={(e) => {
                          e.stopPropagation(); // the row's own click would select it again
                          p.onSelect(r.task_id);
                        }}
                      >
                        {r.kind}
                      </button>
                    </td>
                    <td className="max-w-[200px] truncate border-b border-border px-3 py-2" title={r.input ?? undefined}>
                      {r.input ?? "—"}
                    </td>
                    <td className={cn("border-b border-border px-3 py-2", STATUS_TONE[r.status])}>{STATUS_WORDS[r.status]}</td>
                    <td className="border-b border-border px-3 py-2">{r.tool ?? "—"}</td>
                    <td className="border-b border-border px-3 py-2 whitespace-nowrap">{duration(r.duration_ms)}</td>
                    <td className="border-b border-border px-3 py-2 whitespace-nowrap">{tokens(r)}</td>
                    <td className="border-b border-border px-3 py-2 whitespace-nowrap">{cost(r.cost_usd)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {p.hasMore && (
            <Button variant="ghost" size="sm" className="self-center" disabled={p.loadingMore} onClick={p.onMore}>
              {p.loadingMore ? "Loading…" : "Show more"}
            </Button>
          )}
        </div>
        <Detail {...p} />
      </div>
    </div>
  );
}

function Detail(p: DiagnosticsViewProps) {
  const d = p.detail;
  if (p.selected === null) {
    return <div className="rounded-lg border border-dashed border-border p-6 text-center text-body text-text-muted">Pick a task to see what it did.</div>;
  }
  if (!d && p.detailError) return <Banner kind="danger">We couldn't load this task. It may belong to a trip that was removed.</Banner>;
  if (!d) return <div aria-label="Loading the task" className="h-64 animate-pulse rounded-lg bg-surface-1" />;
  return (
    <section aria-label="Task detail" className="flex flex-col gap-3 rounded-lg border border-border bg-surface-1 p-[18px]">
      <div className="flex items-center gap-2">
        <h2 className="mono min-w-0 truncate text-timecode text-text">
          {d.kind}
          {d.input ? ` · ${d.input}` : ""}
        </h2>
        <span className={cn("rounded-full border px-[9px] py-[3px] text-micro font-medium", d.status === "failed" ? "border-reject text-reject" : "border-border text-text-muted")}>
          {STATUS_WORDS[d.status]}
        </span>
      </div>
      {d.error && (
        <Block label="Error output">
          <pre className="mono max-h-56 overflow-auto text-timecode-sm whitespace-pre-wrap text-reject">{d.error}</pre>
        </Block>
      )}
      <dl className="grid grid-cols-4 gap-3">
        <Fact label="Started">{clockTime(d.started_at)}</Fact>
        <Fact label="Duration">{duration(d.duration_ms)}</Fact>
        <Fact label="Attempts">
          {d.attempts} of {d.max_attempts}
        </Fact>
        <Fact label="Worker">{d.worker ?? "—"}</Fact>
      </dl>
      {(d.tool || d.tokens_in != null) && (
        <dl className="grid grid-cols-4 gap-3">
          <Fact label="Tool / model">{d.tool ?? "—"}</Fact>
          <Fact label="Tokens">{tokens(d)}</Fact>
          <Fact label="Cost">{cost(d.cost_usd)}</Fact>
          <Fact label="Job">#{d.job_id}</Fact>
        </dl>
      )}
      {Object.keys(d.params).length > 0 && (
        <details className="text-caption text-text-muted">
          <summary className="cursor-pointer">Parameters</summary>
          <pre className="mono mt-2 max-h-48 overflow-auto rounded-md bg-bg p-2.5 text-timecode-sm text-text">{JSON.stringify(d.params, null, 2)}</pre>
        </details>
      )}
      <div className="flex items-center gap-2">
        <Button size="sm" disabled={!d.can_retry || p.acting} onClick={() => p.onRetryTask(d.task_id)}>
          <RotateCw /> Retry
        </Button>
        <Button size="sm" variant="ghost" disabled={!d.can_skip || p.acting} onClick={() => p.onSkipTask(d.task_id)}>
          <SkipForward /> Skip
        </Button>
        {!d.can_retry && !d.can_skip && <span className="text-caption font-normal text-text-faint">Retry and Skip are for failed tasks.</span>}
        {d.can_retry && !d.can_skip && <span className="text-caption font-normal text-text-faint">Skip is for failed tasks.</span>}
      </div>
    </section>
  );
}

function Block({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex flex-col gap-1.5">
      <span className="text-caption font-semibold text-text-faint">{label}</span>
      <div className="rounded-md bg-bg px-3 py-2.5">{children}</div>
    </div>
  );
}

function Fact({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex flex-col gap-0.5">
      <dt className="text-micro font-normal text-text-faint">{label}</dt>
      <dd className="mono text-timecode text-text">{children}</dd>
    </div>
  );
}
