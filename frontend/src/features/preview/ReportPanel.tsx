import { useState, type ReactNode } from "react";

import { DispositionChip } from "@/components/media/DispositionChip";
import { Button } from "@/components/ui/Button";
import { Segmented } from "@/components/ui/Segmented";

import { fileName, roleLabel, timecode, type Beat, type ReportData, type TimelineTime } from "./model";

type Tab = "shots" | "not_used" | "rejected";

export interface ReportPanelProps {
  report: ReportData | undefined;
  error?: boolean;
  onRetry?: () => void;
  beats: Beat[];
  onSeek: (t: TimelineTime) => void;
  /** Loaded rejected items beyond the first page (S17's "Show more"). */
  onMoreRejected?: () => void;
  loadingMore?: boolean;
  /** The tab shown first (stories). */
  initialTab?: "shots" | "not_used" | "rejected";
}

/** S17 (M2): the selection/rejection report in place of the findings list (ADR 0049).
 * Why each shot is in the edit, what was considered and not used, and what was rejected
 * — the owner's rejections marked as theirs (the AI-vs-you rule). */
export function ReportPanel(p: ReportPanelProps) {
  const [tab, setTab] = useState<Tab>(p.initialTab ?? "shots");
  const r = p.report;
  const beatTitle = (id: string | null | undefined) => p.beats.find((b) => b.beat_id === id)?.title;
  return (
    <aside aria-label="Selection report" className="flex w-[400px] shrink-0 flex-col gap-2.5">
      <div className="flex items-center gap-2">
        <h2 className="text-subhead font-semibold tracking-[-0.01em] text-text">Why these shots</h2>
      </div>
      <Segmented<Tab>
        label="Report"
        value={tab}
        onChange={setTab}
        className="self-start"
        options={[
          { value: "shots", label: r ? `Shots ${r.events.length}` : "Shots" },
          { value: "not_used", label: r ? `Not used ${r.not_used.length}` : "Not used" },
          { value: "rejected", label: r ? `Rejected ${r.rejected.total}` : "Rejected" },
        ]}
      />
      {p.error ? (
        <div role="alert" className="flex items-center gap-3 rounded-[12px] border border-border bg-surface-1 p-3.5 text-small text-text">
          We couldn't load the report.
          <Button size="sm" onClick={p.onRetry}>
            Try again
          </Button>
        </div>
      ) : !r ? (
        <div aria-label="Loading the report" className="flex flex-col gap-2">
          {[0, 1, 2, 3].map((i) => (
            <div key={i} className="h-20 animate-pulse rounded-[12px] bg-surface-1" />
          ))}
        </div>
      ) : (
        <ul className="flex min-h-0 flex-col gap-2 overflow-y-auto pb-2">
          {tab === "shots" &&
            r.events.map((e) => (
              <li key={e.event_id} className="flex flex-col gap-1.5 rounded-[12px] border border-border bg-surface-1 p-3.5">
                <span className="flex items-center gap-2">
                  <button
                    type="button"
                    aria-label={`Go to ${timecode(e.timeline_in)}`}
                    onClick={() => p.onSeek(e.timeline_in)}
                    className="mono rounded-sm text-timecode text-accent hover:underline focus-visible:outline-2 focus-visible:outline-accent"
                  >
                    {timecode(e.timeline_in)}
                  </button>
                  <Tag>{roleLabel(e.role)}</Tag>
                  {beatTitle(e.beat_id) && <span className="truncate text-caption font-normal text-text-muted">{beatTitle(e.beat_id)}</span>}
                </span>
                {e.reason && <p className="text-small text-text">{e.reason}</p>}
                <p className="text-caption font-normal text-text-faint">
                  {[fileName(e.source_file), e.description].filter(Boolean).join(" · ")}
                </p>
              </li>
            ))}
          {tab === "not_used" &&
            (r.not_used.length === 0 ? (
              <Empty>Every shot the editor picked is in the edit.</Empty>
            ) : (
              r.not_used.map((n) => (
                <li key={n.selection_ref} className="flex flex-col gap-1 rounded-[12px] border border-border bg-surface-1 p-3.5">
                  <span className="flex items-center gap-2 text-caption text-text-muted">
                    <span className="mono">{n.segment_id}</span>
                    {beatTitle(n.beat_id) && <span>{beatTitle(n.beat_id)}</span>}
                  </span>
                  {n.reason && <p className="text-small text-text">{n.reason}</p>}
                </li>
              ))
            ))}
          {tab === "rejected" &&
            (r.rejected.items.length === 0 ? (
              <Empty>Nothing was rejected.</Empty>
            ) : (
              <>
                {r.rejected.items.map((x) => (
                  <li key={x.segment_id} className="flex flex-col gap-1.5 rounded-[12px] border border-border bg-surface-1 p-3.5">
                    <span className="flex items-center gap-2">
                      <DispositionChip value="REJECT" by={x.source} size="sm" />
                      {x.whole_clip && <Tag user>Whole clip</Tag>}
                      <span className="truncate text-caption font-normal text-text-muted">{fileName(x.source_file) ?? x.asset_id}</span>
                    </span>
                    {x.words.length > 0 && <p className="text-small text-text">{x.words.join(" · ")}</p>}
                    {x.camera && <p className="text-caption font-normal text-text-faint">{x.camera}</p>}
                  </li>
                ))}
                {r.rejected.total > r.rejected.items.length && (
                  <li className="flex justify-center pt-1">
                    <Button size="sm" variant="ghost" disabled={p.loadingMore} onClick={p.onMoreRejected}>
                      Show more ({r.rejected.total - r.rejected.items.length} left)
                    </Button>
                  </li>
                )}
              </>
            ))}
        </ul>
      )}
    </aside>
  );
}

function Tag({ children, user }: { children: ReactNode; user?: boolean }) {
  return (
    <span
      className={
        user
          ? "inline-flex items-center rounded-full border border-user bg-user/12 px-[9px] py-[3px] text-micro font-medium text-user"
          : "inline-flex items-center rounded-full border border-border bg-surface-2 px-[9px] py-[3px] text-micro font-medium text-text-muted"
      }
    >
      {children}
    </span>
  );
}

function Empty({ children }: { children: ReactNode }) {
  return <li className="rounded-[12px] border border-dashed border-border p-4 text-small text-text-muted">{children}</li>;
}
