import { Play, Redo2, RefreshCw, SlidersHorizontal, Undo2 } from "lucide-react";
import { useEffect, useRef, useState, type ReactNode } from "react";

import { BeatCard, DurationBar, ShotChip, ShotPopover } from "@/components/edit/Storyboard";
import { Banner } from "@/components/ui/Banner";
import { Button } from "@/components/ui/Button";
import { formatClock } from "@/lib/time";

import { beatFrames, beatLocked, frameSeconds, moveBeatOp, moveShotOp, shotCount, shotFrames, type Alternative, type BoardShot, type DraftOp, type DraftState } from "./model";

export interface StoryboardViewProps {
  /** Undefined while it loads. */
  draft: DraftState | undefined;
  error?: boolean;
  onRetry?: () => void;
  frame: (sampleId: number) => string;
  /** The open shot's alternatives; undefined while they load. */
  alternatives: (ref: string) => Alternative[] | undefined;
  /** The open shot's player, while it plays. */
  player: (ref: string) => ReactNode;
  /** Inline notices on beats (by beat id). */
  warnings: Record<string, string>;
  saving?: boolean;
  onOp: (op: DraftOp) => void;
  onUndo: () => void;
  onRedo: () => void;
  onSave: () => void;
  onRegenerateBeat: (beatId: string) => void;
  onRegenerateStory: () => void;
  onPreview: () => void;
  onChangeSettings: () => void;
  /** The shot whose popover is open (to load its alternatives). */
  onOpenShot?: (ref: string | null) => void;
  /** A shot whose popover starts open (stories). */
  defaultOpen?: string;
}

const SHOT = "application/x-mosaic-shot";
const BEAT = "application/x-mosaic-beat";

type Drag = { kind: "shot"; ref: string } | { kind: "beat"; id: string };
type Over = { beat: string; index: number | null; side?: "before" | "after" };

/** S16 Storyboard: the story as beats of shots, to shape by dragging, locking, replacing
 * and regenerating. Every change is a draft op: undoable, timed by the server.
 * Presentational. */
export function StoryboardView(p: StoryboardViewProps) {
  const d = p.draft;
  const [open, setOpen] = useState<string | null>(p.defaultOpen ?? null);
  const [playing, setPlaying] = useState(false);
  const [drag, setDrag] = useState<Drag | null>(null);
  const [over, setOver] = useState<Over | null>(null);
  const hovered = useRef<string | null>(null);
  const focused = useRef<string | null>(null);

  const latest = useRef(p);
  latest.current = p;
  const openShot = (ref: string | null, play = false) => {
    setOpen(ref);
    setPlaying(play);
    latest.current.onOpenShot?.(ref);
  };

  // A shot that left the board (removed, replaced, regenerated away) closes its popover.
  const shots = new Map<string, BoardShot>(d?.board.beats.flatMap((b) => b.shots.map((s) => [s.ref, s] as const)) ?? []);
  const openGone = open !== null && d !== undefined && !shots.has(open);
  useEffect(() => {
    if (openGone) setOpen(null);
  }, [openGone]);

  const shotsRef = useRef(shots);
  shotsRef.current = shots;
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.target instanceof Element && e.target.closest("input, textarea, select, [contenteditable=true]")) return;
      const q = latest.current;
      const mod = e.metaKey || e.ctrlKey;
      if (mod && e.key.toLowerCase() === "z") {
        e.preventDefault();
        if (e.shiftKey) {
          if (q.draft?.can_redo) q.onRedo();
        } else if (q.draft?.can_undo) q.onUndo();
        return;
      }
      if (mod || e.altKey) return;
      const ref = focused.current;
      const shot = ref ? shotsRef.current.get(ref) : undefined;
      // Space plays the hovered shot unless another control has focus (it presses that).
      const free = !(e.target instanceof Element) || e.target === document.body || e.target.closest("[data-shot]") !== null;
      if (e.key === " " && free && hovered.current && shotsRef.current.has(hovered.current)) {
        e.preventDefault();
        openShot(hovered.current, true);
      } else if (e.key.toLowerCase() === "l" && shot) {
        e.preventDefault();
        q.onOp({ kind: "lock_shot", ref: shot.ref, locked: !shot.locked });
      } else if ((e.key === "Delete" || e.key === "Backspace") && shot && !shot.locked) {
        e.preventDefault();
        q.onOp({ kind: "remove_shot", ref: shot.ref });
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
    // openShot only sets state and calls through ``latest``.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (!d) {
    return (
      <div className="flex flex-1 flex-col">
        <Header />
        {p.error ? (
          <div className="p-7">
            <Banner kind="danger" action={p.onRetry && <Button size="sm" onClick={p.onRetry}>Try again</Button>}>
              The storyboard couldn't be loaded.
            </Banner>
          </div>
        ) : (
          <div className="grid grid-cols-3 gap-4 px-7 py-5">
            {[0, 1, 2, 3, 4, 5].map((i) => (
              <div key={i} aria-hidden className="h-[190px] animate-pulse rounded-lg border border-border bg-surface-1" />
            ))}
          </div>
        )}
      </div>
    );
  }

  const rate = d.duration.rate;
  const perShot = shotFrames(d);
  const perBeat = beatFrames(d);
  const regenerating = new Set(d.regenerating);
  const whole = d.regenerating_scope !== null;
  const beats = d.board.beats;
  const target = frameSeconds(d.target.frames ?? d.duration.frames, rate);
  const over_ = d.metrics.locks?.over_frames ?? 0;

  const dropOn = (beatId: string, index: number) => {
    if (drag?.kind !== "shot") return;
    const op = moveShotOp(beats, drag.ref, beatId, index);
    if (op) p.onOp(op);
  };
  const end = () => {
    setDrag(null);
    setOver(null);
  };

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex flex-col gap-4 border-b border-border px-7 py-[18px]">
        <div className="flex items-center gap-3">
          <Header subtitle={`${beats.length} beats · ${shotCount(d)} shots · drag shots between beats, lock what you love`} />
          <span className="ml-auto flex items-center gap-2">
            <Button size="icon" variant="ghost" aria-label="Undo" title="Undo (⌘Z)" disabled={!d.can_undo} onClick={p.onUndo}>
              <Undo2 />
            </Button>
            <Button size="icon" variant="ghost" aria-label="Redo" title="Redo (⇧⌘Z)" disabled={!d.can_redo} onClick={p.onRedo}>
              <Redo2 />
            </Button>
            {d.dirty && (
              <span className="flex items-center gap-2">
                <span className="text-caption font-normal text-text-muted">Unsaved changes ·</span>
                <Button size="sm" disabled={p.saving} onClick={p.onSave}>
                  Save version
                </Button>
              </span>
            )}
            <Button variant="ghost" onClick={p.onChangeSettings}>
              <SlidersHorizontal /> Change settings
            </Button>
            <Button disabled={whole} onClick={p.onRegenerateStory}>
              <RefreshCw /> Regenerate story
            </Button>
            <Button variant="primary" disabled={p.saving} onClick={p.onPreview}>
              <Play /> Preview
            </Button>
          </span>
        </div>
        <DurationBar
          seconds={frameSeconds(d.duration.frames, rate)}
          target={target}
          tolerance={frameSeconds(d.tolerance.frames, d.tolerance.rate)}
          beats={beats.map((b) => ({
            id: b.beat_id,
            title: b.title,
            seconds: frameSeconds(perBeat.get(b.beat_id) ?? 0, rate),
            locked: beatLocked(b),
            regenerating: whole || regenerating.has(b.beat_id),
          }))}
        />
        {over_ > 0 && (
          <Banner kind="warning">
            Your locked shots run {formatClock(frameSeconds(over_, rate))} past the longest this edit can be. Unlock some shots, or make the edit longer.
          </Banner>
        )}
        {whole && <Banner kind="info">Regenerating the {d.regenerating_scope === "story" ? "story" : "edit"}. Your locked shots stay where they are.</Banner>}
      </div>
      <div className="grid min-h-0 flex-1 grid-cols-3 content-start gap-4 overflow-y-auto px-7 py-5">
        {beats.map((b, bi) => {
          const busy = whole || regenerating.has(b.beat_id);
          const visible = b.shots.filter((s) => !s.absorbed_by);
          return (
            <BeatCard
              key={b.beat_id}
              title={b.title}
              intent={b.intent}
              seconds={frameSeconds(perBeat.get(b.beat_id) ?? 0, rate)}
              locked={beatLocked(b)}
              regenerating={busy}
              warning={p.warnings[b.beat_id]}
              dragging={drag?.kind === "beat" && drag.id === b.beat_id}
              dropAtEnd={drag?.kind === "shot" && over?.beat === b.beat_id && over.index === null}
              beatDrop={drag?.kind === "beat" && over?.beat === b.beat_id && drag.id !== b.beat_id ? over.side : null}
              canMoveEarlier={bi > 0}
              canMoveLater={bi < beats.length - 1}
              onRegenerate={() => p.onRegenerateBeat(b.beat_id)}
              onPace={(faster) => p.onOp({ kind: "pace_beat", beat_id: b.beat_id, faster })}
              onLockAll={(locked) => {
                for (const s of visible) if (s.locked !== locked) p.onOp({ kind: "lock_shot", ref: s.ref, locked });
              }}
              onMove={(later) => p.onOp({ kind: "move_beat", beat_id: b.beat_id, index: later ? bi + 1 : bi - 1 })}
              onHandleDragStart={(e) => {
                e.dataTransfer.setData(BEAT, b.beat_id);
                e.dataTransfer.effectAllowed = "move";
                const card = (e.currentTarget as HTMLElement).closest("section");
                if (card) e.dataTransfer.setDragImage(card, 24, 24);
                setDrag({ kind: "beat", id: b.beat_id });
              }}
              onDragEnd={end}
              onDragOver={(e) => {
                if (!drag || busy) return;
                e.preventDefault();
                if (drag.kind === "beat") {
                  const box = e.currentTarget.getBoundingClientRect();
                  const side = e.clientX < box.left + box.width / 2 ? "before" : "after";
                  if (over?.beat !== b.beat_id || over.side !== side) setOver({ beat: b.beat_id, index: null, side });
                } else if (over?.beat !== b.beat_id || (over.index !== null && e.target === e.currentTarget)) {
                  setOver({ beat: b.beat_id, index: null });
                }
              }}
              onDrop={(e) => {
                e.preventDefault();
                if (drag?.kind === "beat") {
                  const op = moveBeatOp(beats, drag.id, over?.side === "after" ? bi + 1 : bi);
                  if (op) p.onOp(op);
                } else if (over?.beat === b.beat_id && over.index !== null) dropOn(b.beat_id, over.index);
                else dropOn(b.beat_id, b.shots.length);
                end();
              }}
            >
              {visible.map((s) => {
                const m = d.media[s.segment_id];
                const frames = perShot.get(s.ref);
                const seconds = frames === undefined ? undefined : frameSeconds(frames, rate);
                const at = b.shots.indexOf(s);
                const alts = open === s.ref ? p.alternatives(s.ref) : undefined;
                const facts = [`Role: ${s.role}`, seconds === undefined ? "not in the edit" : formatClock(seconds), m?.day ? `Day ${m.day}` : null].filter(Boolean).join(" · ");
                return (
                  <ShotPopover
                    key={s.ref}
                    open={open === s.ref}
                    onOpenChange={(o) => openShot(o ? s.ref : null)}
                    frameUrl={m?.sample_id != null ? p.frame(m.sample_id) : undefined}
                    file={m?.file ?? s.segment_id}
                    facts={facts}
                    reason={s.reason}
                    locked={s.locked}
                    alternatives={alts?.map((a) => ({
                      segment_id: a.segment_id,
                      frameUrl: a.sample_id != null ? p.frame(a.sample_id) : undefined,
                      file: a.file ?? a.segment_id,
                      note: a.why_not ?? a.line,
                    }))}
                    player={open === s.ref && playing ? p.player(s.ref) : undefined}
                    onReplace={(seg) => {
                      p.onOp({ kind: "replace_shot", ref: s.ref, segment_id: seg });
                      openShot(null);
                    }}
                    onLock={() => p.onOp({ kind: "lock_shot", ref: s.ref, locked: !s.locked })}
                    onRemove={() => {
                      p.onOp({ kind: "remove_shot", ref: s.ref });
                      openShot(null);
                    }}
                    onPlay={() => setPlaying(true)}
                  >
                    <ShotChip
                      label={`${s.role}${seconds === undefined ? "" : `, ${formatClock(seconds)}`}${s.locked ? ", locked" : ""}`}
                      frameUrl={m?.sample_id != null ? p.frame(m.sample_id) : undefined}
                      role={s.role}
                      seconds={seconds}
                      locked={s.locked}
                      photo={m?.photo}
                      dragging={drag?.kind === "shot" && drag.ref === s.ref}
                      dropBefore={drag?.kind === "shot" && drag.ref !== s.ref && over?.beat === b.beat_id && over.index === at}
                      onDragStart={(e) => {
                        e.stopPropagation();
                        e.dataTransfer.setData(SHOT, s.ref);
                        e.dataTransfer.effectAllowed = "move";
                        openShot(null);
                        setDrag({ kind: "shot", ref: s.ref });
                      }}
                      onDragEnd={end}
                      onDragOver={(e) => {
                        if (drag?.kind !== "shot" || busy) return;
                        e.preventDefault();
                        e.stopPropagation();
                        const box = e.currentTarget.getBoundingClientRect();
                        const index = e.clientX < box.left + box.width / 2 ? at : at + 1;
                        const next = index >= b.shots.length ? null : index;
                        if (over?.beat !== b.beat_id || over.index !== next) setOver({ beat: b.beat_id, index: next });
                      }}
                      onDrop={(e) => {
                        if (drag?.kind !== "shot") return; // a beat: the card takes it
                        e.preventDefault();
                        e.stopPropagation();
                        dropOn(b.beat_id, over?.beat === b.beat_id && over.index !== null ? over.index : b.shots.length);
                        end();
                      }}
                      onHover={(on) => {
                        if (on) hovered.current = s.ref;
                        else if (hovered.current === s.ref) hovered.current = null;
                      }}
                      onFocus={(on) => {
                        if (on) focused.current = s.ref;
                        else if (focused.current === s.ref) focused.current = null;
                      }}
                    />
                  </ShotPopover>
                );
              })}
            </BeatCard>
          );
        })}
      </div>
    </div>
  );
}

function Header({ subtitle }: { subtitle?: string }) {
  return (
    <div className="flex flex-col gap-[3px]">
      <h1 className="text-title tracking-[-0.01em] text-text">Storyboard</h1>
      {subtitle && <p className="text-small text-text-muted">{subtitle}</p>}
    </div>
  );
}
