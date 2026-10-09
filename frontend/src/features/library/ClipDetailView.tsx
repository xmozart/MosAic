import { ChevronLeft, ChevronRight, Orbit } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { Filmstrip } from "@/components/media/Filmstrip";
import { Player, type PlayerHandle } from "@/components/media/Player";
import { Transcript, type TranscriptLine } from "@/components/media/Transcript";
import { Waveform } from "@/components/media/Waveform";
import { Banner } from "@/components/ui/Banner";
import { Button } from "@/components/ui/Button";
import { SwitchRow } from "@/components/ui/Switch";
import { cn } from "@/lib/cn";
import { seconds, type SourceTime } from "@/lib/time";

import { ClipFacts } from "./ClipFacts";
import { factsLine, usableRange, type ClipDetail, type DecisionChange } from "./model";

export interface ClipDetailViewProps {
  clip: ClipDetail;
  proxyUrl?: string;
  frameUrl: (sampleId: number) => string;
  filmstrip: string[];
  /** Each filmstrip frame's time (clip ticks), so the usable range is highlighted. */
  filmstripTicks?: number[];
  peaks: Uint8Array | null;
  transcript: TranscriptLine[];
  onDecide: (change: DecisionChange) => void;
  onBack: () => void;
  onPrev?: () => void;
  onNext?: () => void;
  onShowClip: (id: number) => void;
}

/** S11 Clip detail: everything about one clip and the AI's reasoning. Presentational; the
 * player, filmstrip, waveform and transcript on the left, the decisions on the right. */
export function ClipDetailView(p: ClipDetailViewProps) {
  const c = p.clip;
  const player = useRef<PlayerHandle>(null);
  const [now, setNow] = useState(0);
  const total = c.duration ? seconds(c.duration) : 0;
  const usable = usableRange(c);
  const poster = c.moments.find((m) => m.sample_id)?.sample_id;
  const isVideo = c.kind === "video";
  // Seeking from the transcript or a moment leaves the keys with the player (L plays).
  const seekTo = (t: SourceTime) => {
    player.current?.seekTo(t);
    player.current?.focus();
  };
  const pos = c.position;
  // A video opens with the player focused: J/K/L, Space and the arrows are the player's.
  useEffect(() => {
    if (isVideo) player.current?.focus();
  }, [c.asset_id, isVideo]);
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex items-center gap-3 border-b border-border px-6 py-3">
        <button type="button" onClick={p.onBack} className="inline-flex items-center gap-1 rounded-sm text-small text-text-muted hover:text-text focus-visible:outline-2 focus-visible:outline-accent">
          <ChevronLeft aria-hidden className="size-4" /> Library
        </button>
        {pos && (
          <span className="text-small text-text-muted">
            {pos.day ? `Day ${pos.day} · ` : ""}
            {pos.index} of {pos.count}
          </span>
        )}
        <span className="ml-auto flex gap-1">
          <Button size="icon" aria-label="Previous clip" className="size-8" disabled={!p.onPrev} onClick={p.onPrev}>
            <ChevronLeft />
          </Button>
          <Button size="icon" aria-label="Next clip" className="size-8" disabled={!p.onNext} onClick={p.onNext}>
            <ChevronRight />
          </Button>
        </span>
      </div>
      <div className="grid min-h-0 flex-1 grid-cols-[minmax(0,1fr)_380px] overflow-hidden">
        <div className="flex min-w-0 flex-col gap-4 overflow-y-auto p-6">
          {c.status === "unsupported" ? (
            <div className="flex aspect-video flex-col items-center justify-center gap-2 rounded-lg border border-border bg-surface-2 p-8 text-center">
              <p className="text-body text-text">{c.reason}</p>
              {c.fix && <p className="max-w-[520px] text-small text-text-muted">{c.fix}</p>}
            </div>
          ) : isVideo && c.rate ? (
            <>
              {c.analysis_only && (
                <Banner kind="info">Analyzed from a forward view. Editing 360° video is coming later — export a flat version from Insta360 Studio to use it now.</Banner>
              )}
              <Player
                ref={player}
                src={p.proxyUrl}
                poster={poster ? p.frameUrl(poster) : undefined}
                rate={c.proxy_rate ?? c.rate}
                usableRange={usable}
                markers={c.moments.filter((m) => m.description).map((m) => ({ at: m.usable_start, label: m.description!, kind: "moment" as const }))}
                onTime={setNow}
              />
              {p.filmstrip.length > 0 && <Filmstrip frames={p.filmstrip} selection={stripSelection(p.filmstripTicks, usable)} />}
              {p.peaks && (
                <Waveform
                  peaks={p.peaks}
                  position={total ? now / total : undefined}
                  selection={usable && total ? [seconds(usable.start) / total, seconds(usable.end) / total] : undefined}
                />
              )}
              {p.transcript.length > 0 && <Transcript lines={p.transcript} now={now} language={c.transcript.language} onSeek={seekTo} />}
            </>
          ) : (
            <PhotoVariant clip={c} frameUrl={p.frameUrl} onDecide={p.onDecide} onShowClip={p.onShowClip} />
          )}
        </div>
        <aside aria-label="Decisions" className="flex flex-col gap-4 overflow-y-auto border-l border-border bg-surface-1 px-5 py-5">
          {c.analysis_only && (
            <span className="inline-flex items-center gap-1.5 self-start rounded-full border border-border bg-surface-2 px-2.5 py-0.5 text-caption text-text-muted">
              <Orbit aria-hidden className="size-3.5" /> 360 · forward view
            </span>
          )}
          <ClipFacts clip={c} frameUrl={p.frameUrl} onDecide={p.onDecide} onShowClip={p.onShowClip} onMoment={isVideo ? seekTo : undefined} />
        </aside>
      </div>
    </div>
  );
}

function PhotoVariant({ clip: c, frameUrl, onDecide, onShowClip }: { clip: ClipDetail; frameUrl: (s: number) => string; onDecide: (c: DecisionChange) => void; onShowClip: (id: number) => void }) {
  const poster = c.moments.find((m) => m.sample_id)?.sample_id;
  return (
    <div className="flex flex-col gap-4">
      <div data-theme="dark" className="relative aspect-video overflow-hidden rounded-lg bg-bg">
        {poster && <img src={frameUrl(poster)} alt="" className="size-full object-contain" />}
        {c.kind === "live_photo" && (
          <span data-theme="dark" className="absolute top-3 left-3 rounded-sm bg-media-chip px-1.5 py-0.5 text-tag font-bold tracking-[0.06em] text-on-media">
            LIVE
          </span>
        )}
      </div>
      {c.kind === "live_photo" && (
        <SwitchRow label="Use 2 s of Live Photo motion" checked={Boolean(c.decision.live_motion)} onChange={(on) => onDecide({ live_motion: on })} />
      )}
      <p className="text-caption font-normal text-text-muted">{factsLine(c)}</p>
      {c.burst && (
        <section aria-label="Burst" className="flex flex-col gap-2">
          <h2 className="text-caption text-text-muted">Burst · {c.burst.items.length} photos · best picked</h2>
          <div className="grid grid-cols-6 gap-1.5">
            {c.burst.items.map((b) => (
              <button
                key={b.asset_id}
                type="button"
                aria-label={b.best ? "Best of the burst" : `Burst photo ${b.asset_id}`}
                aria-current={b.asset_id === c.asset_id || undefined}
                onClick={() => onShowClip(b.asset_id)}
                className={cn(
                  "aspect-[4/3] overflow-hidden rounded-md bg-surface-3 focus-visible:outline-2 focus-visible:outline-accent",
                  b.best && "outline-2 outline-offset-2 outline-accent",
                  b.asset_id === c.asset_id && !b.best && "ring-2 ring-text-muted",
                )}
              >
                {b.sample_id && <img src={frameUrl(b.sample_id)} alt="" className="size-full object-cover" />}
              </button>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}

/** The filmstrip frames inside the usable range, as an index range [from, to). */
function stripSelection(ticks: number[] | undefined, usable: { start: SourceTime; end: SourceTime } | undefined): [number, number] | undefined {
  if (!ticks?.length || !usable) return undefined;
  const from = ticks.findIndex((t) => t >= usable.start.ticks);
  const lastIn = ticks.findLastIndex((t) => t < usable.end.ticks);
  return from < 0 || lastIn < from ? undefined : [from, lastIn + 1];
}
