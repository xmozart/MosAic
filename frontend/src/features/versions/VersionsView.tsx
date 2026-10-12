import { ChevronLeft, GitCompare, Undo2 } from "lucide-react";
import { useRef, useState, type ReactNode } from "react";

import { VersionList } from "@/components/edit/VersionList";
import { Player, type PlayerHandle } from "@/components/media/Player";
import { Banner } from "@/components/ui/Banner";
import { Button } from "@/components/ui/Button";
import { Segmented } from "@/components/ui/Segmented";
import { cn } from "@/lib/cn";
import { formatOpened } from "@/lib/format";
import { fps, formatClock } from "@/lib/time";

import { toSource } from "@/features/preview/model";

import { KIND_LABEL, changeText, defaultPair, type Change, type ChangeKind, type CompareData, type VersionRow } from "./model";

/** One compared version's preview: its file, or why there is none. */
export interface SidePreview {
  url?: string;
  /** "rendering 45 %", "queued"…; none when the file is ready or there is no render. */
  status?: string;
  onRender?: () => void;
}

export interface VersionsViewProps {
  title: string;
  /** Undefined while they load. */
  versions: VersionRow[] | undefined;
  error?: boolean;
  onRetry?: () => void;
  /** The two versions compared, older first. */
  pair: [number, number] | null;
  compare: CompareData | undefined;
  compareError?: boolean;
  previews: Record<number, SidePreview>;
  reverting?: boolean;
  onSelect: (version: number) => void;
  onLatestPair: () => void;
  onRevert: (version: number) => void;
  onBack: () => void;
  /** Clock for "Today 14:12" (stories and tests). */
  now?: Date;
}

const TAG: Record<ChangeKind, string> = {
  replaced: "border-accent text-accent",
  trimmed: "border-info text-info",
  moved: "border-text-muted text-text-muted",
  added: "border-use text-use",
  removed: "border-reject text-reject",
};

function when(iso: string, now?: Date): string {
  const d = new Date(iso);
  return `${formatOpened(iso, now)} ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

function reasonOf(v: VersionRow): string {
  if (v.reason) return v.reason;
  return v.version === 1 ? "First edit" : v.creator === "user" ? "Your changes" : "A new take";
}

/** S18 Versions: every version with who made it and why; two compared side by side, with
 * what changed between them, and Revert (a new version, never a destructive change).
 * Presentational. */
export function VersionsView(p: VersionsViewProps) {
  const vs = p.versions;
  const latest = vs?.length ? Math.max(...vs.map((v) => v.version)) : undefined;
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex items-center gap-3 border-b border-border px-6 py-3">
        <button type="button" onClick={p.onBack} className="inline-flex items-center gap-1 rounded-sm text-small text-text-muted hover:text-text focus-visible:outline-2 focus-visible:outline-accent">
          <ChevronLeft aria-hidden className="size-4" /> Preview
        </button>
        <span className="truncate text-small font-semibold text-text">{p.title}</span>
      </div>
      <div className="flex min-h-0 flex-1 gap-5 overflow-hidden px-6 py-[22px]">
        <div className="flex w-80 shrink-0 flex-col gap-2.5 overflow-y-auto">
          <h1 className="text-heading font-semibold tracking-[-0.01em] text-text">Versions</h1>
          {p.error ? (
            <Banner kind="danger" action={p.onRetry && <Button size="sm" onClick={p.onRetry}>Try again</Button>}>
              The versions couldn't be loaded.
            </Banner>
          ) : !vs ? (
            [0, 1, 2].map((i) => <div key={i} aria-hidden className="h-[92px] animate-pulse rounded-lg border border-border bg-surface-1" />)
          ) : (
            <>
              <VersionList
                items={[...vs]
                  .sort((x, y) => y.version - x.version)
                  .map((v) => ({
                    version: v.version,
                    byYou: v.creator === "user",
                    reason: reasonOf(v),
                    when: when(v.created_at, p.now),
                    duration: v.duration ? formatClock(v.duration.frames / fps(v.duration.rate)) : "—",
                  }))}
                selected={p.pair ?? (latest ? [latest] : [])}
                onSelect={p.onSelect}
              />
              {defaultPair(vs) && (
                <Button size="sm" className="self-start" onClick={p.onLatestPair}>
                  <GitCompare /> Compare v{defaultPair(vs)![0]} ↔ v{defaultPair(vs)![1]}
                </Button>
              )}
            </>
          )}
        </div>
        <div className="flex min-w-0 flex-1 flex-col gap-3.5 overflow-y-auto">
          {vs && vs.length < 2 ? (
            <div className="flex flex-1 items-center justify-center rounded-lg border border-border bg-surface-1 p-8 text-center text-body text-text-muted">
              This edit has one version so far. Change it in the storyboard or apply a fix, and you can compare the two here.
            </div>
          ) : p.pair ? (
            <Compare {...p} pair={p.pair} latest={latest} />
          ) : null}
        </div>
      </div>
    </div>
  );
}

function Compare(p: VersionsViewProps & { pair: [number, number]; latest: number | undefined }) {
  const [a, b] = p.pair;
  const [synced, setSynced] = useState<"synced" | "independent">("synced");
  const players = useRef<Record<number, PlayerHandle | null>>({});
  const c = p.compare;
  const rateOf = (v: number) => p.versions?.find((x) => x.version === v)?.duration?.rate ?? c?.duration_b.rate ?? "30000/1001";
  const rate = rateOf(b);
  // Synced: the other player follows. It never echoes back: play() on a playing video,
  // pause() on a paused one and a seek to where it already is fire nothing.
  const mirror = (from: number, act: (other: PlayerHandle) => void) => {
    if (synced !== "synced") return;
    const other = players.current[from === a ? b : a];
    if (other) act(other);
  };
  const seekBoth = (frame: number) => {
    const s = frame / fps(rate);
    for (const v of [a, b]) players.current[v]?.seekSeconds(s);
  };
  // Back to the older one, while the pair is the latest and something differs: after a
  // revert the two are the same, and another click would only add a copy.
  const canRevert = b === p.latest && c !== undefined && !c.same;
  return (
    <>
      <div className="flex items-center gap-3">
        <h2 className="text-heading font-semibold tracking-[-0.01em] text-text">
          Compare v{a} and v{b}
        </h2>
        <Segmented<"synced" | "independent">
          label="Playback"
          value={synced}
          onChange={setSynced}
          options={[
            { value: "synced", label: "Synced" },
            { value: "independent", label: "Independent" },
          ]}
        />
        {canRevert && (
          <Button size="sm" variant="ghost" className="ml-auto" disabled={p.reverting} onClick={() => p.onRevert(a)}>
            <Undo2 /> {p.reverting ? "Reverting…" : `Revert to v${a}`}
          </Button>
        )}
      </div>
      <div className="flex items-start gap-4">
        {[a, b].map((v) => {
          const pv = p.previews[v] ?? {};
          const dur = v === a ? c?.duration_a : c?.duration_b;
          return (
            <div key={v} className="flex min-w-0 flex-1 flex-col gap-2">
              <div className="flex items-center gap-1.5">
                <span className="inline-flex items-center rounded-full border border-border bg-surface-2 px-[9px] py-[3px] text-caption text-text-muted">v{v}</span>
                {dur && <span className="mono ml-auto text-timecode-sm text-text-muted">{formatClock(dur.frames / fps(dur.rate))}</span>}
              </div>
              <div className="rounded-lg border border-border bg-surface-1 p-2">
                <Player
                  ref={(h) => {
                    players.current[v] = h;
                  }}
                  src={pv.url}
                  rate={rateOf(v)}
                  length={dur ? toSource(dur) : undefined}
                  onPlayState={(on) => mirror(v, (o) => (on ? o.play() : o.pause()))}
                  onSeeked={(s) => mirror(v, (o) => o.seekSeconds(s))}
                  empty={<PreviewMissing pv={pv} />}
                />
              </div>
            </div>
          );
        })}
      </div>
      <section aria-label="What changed" className="flex flex-col gap-1 rounded-lg border border-border bg-surface-1 p-[18px]">
        <h3 className="text-body font-semibold tracking-[-0.01em] text-text">What changed</h3>
        {p.compareError ? (
          <p className="py-2 text-small text-text-muted">The changes couldn't be loaded.</p>
        ) : !c ? (
          [0, 1, 2].map((i) => <div key={i} aria-hidden className="my-1 h-7 animate-pulse rounded-sm bg-surface-2" />)
        ) : c.same ? (
          <p className="py-2 text-small text-text-muted">These two versions are the same.</p>
        ) : c.changes.length === 0 ? (
          <p className="py-2 text-small text-text-muted">The same shots; only timing and sound settings differ.</p>
        ) : (
          <ul className="flex flex-col">
            {c.changes.map((x) => (
              <ChangeRow key={`${x.kind}-${x.ref}`} change={x} rate={rate} onSeek={() => seekBoth(x.frame)} />
            ))}
          </ul>
        )}
      </section>
    </>
  );
}

function ChangeRow({ change, rate, onSeek }: { change: Change; rate: string; onSeek: () => void }) {
  return (
    <li className="flex items-center gap-2.5 border-b border-border py-2 last:border-b-0">
      <span className={cn("inline-flex shrink-0 items-center rounded-full border px-[9px] py-[3px] text-micro font-medium", TAG[change.kind])}>{KIND_LABEL[change.kind]}</span>
      <span className="min-w-0 truncate text-small text-text">{changeText(change, rate)}</span>
      <button type="button" onClick={onSeek} aria-label={`Go to ${formatClock(change.frame / fps(rate))} in v${change.in_version}`} className="mono ml-auto shrink-0 rounded-sm text-timecode-sm text-text-muted hover:text-text focus-visible:outline-2 focus-visible:outline-accent">
        {formatClock(change.frame / fps(rate))}
      </button>
    </li>
  );
}

function PreviewMissing({ pv }: { pv: SidePreview }): ReactNode {
  if (pv.status) return <span role="status">{pv.status}</span>;
  return (
    <span className="flex flex-col items-center gap-3 text-center">
      No preview yet.
      {pv.onRender && (
        <Button size="sm" onClick={pv.onRender}>
          Render preview
        </Button>
      )}
    </span>
  );
}
