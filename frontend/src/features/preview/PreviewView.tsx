import { ChevronLeft, Download, LayoutPanelTop, RotateCw } from "lucide-react";
import { useRef, useState, type ReactNode } from "react";

import { EditFacts } from "@/components/edit/EditFacts";
import { Player, type PlayerHandle } from "@/components/media/Player";
import { Banner } from "@/components/ui/Banner";
import { Button } from "@/components/ui/Button";
import { Segmented } from "@/components/ui/Segmented";
import { renderStatusText, type RenderRow } from "@/lib/renders";

import { beatAt, beatSegments, factsRows, toSource, type EditVersionData, type ReportData, type VersionItem } from "./model";
import { ReportPanel } from "./ReportPanel";

export type PreviewState =
  | { kind: "loading" }
  | { kind: "generating"; pct: number }
  | { kind: "failed"; error: string | null }
  /** No version and no job: the edit was never made (its job was cancelled first). */
  | { kind: "new" }
  | { kind: "missing" }
  /** The edit could not be loaded (not a 404). */
  | { kind: "error" }
  | { kind: "ready"; edit: EditVersionData };

export interface PreviewViewProps {
  title: string;
  state: PreviewState;
  versions: VersionItem[];
  onVersion: (v: number) => void;
  /** The version's newest preview and final renders (ADR 0049). */
  preview?: RenderRow;
  final?: RenderRow;
  previewUrl?: string;
  finalDownloadUrl?: string;
  onRenderPreview: () => void;
  onRenderFinal: () => void;
  onRetryGenerate: () => void;
  onRetryLoad?: () => void;
  onBack: () => void;
  onExports: () => void;
  report: ReportData | undefined;
  reportError?: boolean;
  onRetryReport?: () => void;
  onMoreRejected?: () => void;
  loadingMore?: boolean;
  /** Something is being started (a render or a regenerate): its buttons wait. */
  busy?: boolean;
}

/** S17 Preview (M2: player and selection/rejection report; findings are M4). */
export function PreviewView(p: PreviewViewProps) {
  const st = p.state;
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex items-center gap-3 border-b border-border px-6 py-3">
        <button type="button" onClick={p.onBack} className="inline-flex items-center gap-1 rounded-sm text-small text-text-muted hover:text-text focus-visible:outline-2 focus-visible:outline-accent">
          <ChevronLeft aria-hidden className="size-4" /> Edits
        </button>
        <h1 className="truncate text-small font-semibold text-text">{p.title}</h1>
      </div>
      {st.kind !== "ready" ? (
        <div className="flex flex-1 flex-col gap-4 px-6 py-[22px]">
          {st.kind === "loading" && <div aria-label="Loading the edit" className="aspect-video max-w-[960px] animate-pulse rounded-lg bg-surface-1" />}
          {st.kind === "generating" && (
            <Banner kind="info">This edit is still being made ({st.pct}%). It plays here as soon as it's ready.</Banner>
          )}
          {st.kind === "failed" && (
            <Banner
              kind="danger"
              action={
                <Button size="sm" disabled={p.busy} onClick={p.onRetryGenerate}>
                  <RotateCw /> Try again
                </Button>
              }
            >
              We couldn't create this edit.{st.error ? ` ${st.error}` : ""}
            </Banner>
          )}
          {st.kind === "new" && (
            <Banner
              kind="info"
              action={
                <Button size="sm" disabled={p.busy} onClick={p.onRetryGenerate}>
                  Make it now
                </Button>
              }
            >
              This edit hasn't been made yet.
            </Banner>
          )}
          {st.kind === "missing" && <Banner kind="warning">We can't find this edit. It may have been removed.</Banner>}
          {st.kind === "error" && (
            <Banner
              kind="danger"
              action={
                <Button size="sm" onClick={p.onRetryLoad}>
                  <RotateCw /> Try again
                </Button>
              }
            >
              We couldn't load this edit.
            </Banner>
          )}
        </div>
      ) : (
        <Ready {...p} edit={st.edit} />
      )}
    </div>
  );
}

function Ready(p: PreviewViewProps & { edit: EditVersionData }) {
  const player = useRef<PlayerHandle>(null);
  const [now, setNow] = useState(0);
  const e = p.edit;
  const events = e.timeline.tracks[0]?.events ?? [];
  const beat = beatAt(events, e.beats, now);
  const pv = p.preview;
  const final = p.final;
  const finalBusy = final && (final.status === "queued" || final.status === "rendering" || final.status === "paused");
  const finalDone = final?.status === "done";
  let empty: ReactNode;
  if (!pv || pv.status === "failed" || pv.status === "missing") {
    empty = (
      <span className="flex flex-col items-center gap-3 text-center">
        {pv?.status === "failed" ? "The preview couldn't be rendered." : pv?.status === "missing" ? "The preview file is gone." : "No preview yet."}
        <Button size="sm" disabled={p.busy} onClick={p.onRenderPreview}>
          {pv ? "Render again" : "Render preview"}
        </Button>
      </span>
    );
  } else if (pv.status !== "done") {
    empty = (
      <span role="status" className="flex w-64 flex-col items-center gap-2 text-center">
        {pv.status === "queued" ? "Preview queued…" : `Rendering preview… ${pv.pct ?? 0}%`}
        <span className="h-1 w-full overflow-hidden rounded-full bg-on-media/20">
          <span className="block h-full bg-accent transition-[width] duration-300" style={{ width: `${pv.pct ?? 0}%` }} />
        </span>
      </span>
    );
  }
  return (
    <div className="flex min-h-0 flex-1 gap-5 overflow-hidden px-6 py-[22px]">
      <div className="flex min-w-0 flex-1 flex-col gap-4 overflow-y-auto">
        <div className="rounded-lg border border-border bg-surface-1 p-3">
          <Player
            ref={player}
            src={pv?.status === "done" ? p.previewUrl : undefined}
            rate={e.rate}
            length={toSource(e.timeline.duration)}
            segments={beatSegments(events, e.beats)}
            onTime={setNow}
            empty={empty}
            overlay={
              <>
                <Overlay className="top-3.5 left-3.5">
                  v{e.version} · {pv?.status === "done" ? pv.label.replace(/^Preview · /, "preview ") : "no preview yet"}
                </Overlay>
                {beat && <Overlay className="top-3.5 right-3.5">Beat: {beat}</Overlay>}
              </>
            }
            controlsEnd={
              p.versions.length > 1 ? (
                <Segmented
                  label="Version"
                  value={String(e.version)}
                  onChange={(v) => p.onVersion(Number(v))}
                  options={p.versions.map((x) => ({ value: String(x.version), label: `v${x.version}` }))}
                />
              ) : undefined
            }
          />
        </div>
        <EditFacts rows={factsRows(e.facts)} />
        <div className="flex items-center gap-2">
          <Button variant="ghost" disabled title="The storyboard comes in a later update">
            <LayoutPanelTop /> Open storyboard
          </Button>
          <span className="flex-1" />
          {final && final.status !== "done" && <span className="text-caption font-normal text-text-muted">Final: {renderStatusText(final)}</span>}
          <Button onClick={p.onExports}>Exports</Button>
          {finalDone && p.finalDownloadUrl ? (
            <Button variant="primary" asChild>
              <a href={p.finalDownloadUrl} download>
                <Download /> Download final
              </a>
            </Button>
          ) : (
            <Button variant="primary" disabled={p.busy || Boolean(finalBusy)} onClick={p.onRenderFinal}>
              {finalBusy ? "Rendering final…" : "Render final"}
            </Button>
          )}
        </div>
      </div>
      <ReportPanel
        report={p.report}
        error={p.reportError}
        onRetry={p.onRetryReport}
        beats={e.beats}
        onSeek={(t) => {
          player.current?.seekTo(toSource(t));
          player.current?.focus();
        }}
        onMoreRejected={p.onMoreRejected}
        loadingMore={p.loadingMore}
      />
    </div>
  );
}

function Overlay({ children, className }: { children: ReactNode; className: string }) {
  return (
    <span data-theme="dark" className={`absolute ${className} rounded-full bg-media-chip px-[9px] py-[3px] text-micro font-medium text-on-media`}>
      {children}
    </span>
  );
}
