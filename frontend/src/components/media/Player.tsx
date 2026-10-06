import { Pause, Play } from "lucide-react";
import { forwardRef, useCallback, useEffect, useImperativeHandle, useRef, useState, type KeyboardEvent, type PointerEvent } from "react";

import { cn } from "@/lib/cn";
import { fps, formatClock, frameIndex, seconds, type SourceTime } from "@/lib/time";

export interface PlayerRange {
  start: SourceTime;
  end: SourceTime;
}

export interface PlayerMarker {
  at: SourceTime;
  label: string;
  kind: "moment" | "finding";
}

export interface PlayerProps {
  src?: string;
  poster?: string;
  rate: string; // frame rate of the proxy, e.g. "30000/1001" (one-frame steps)
  usableRange?: PlayerRange;
  markers?: PlayerMarker[];
  /** Play only this range: start there, stop at its end. */
  range?: PlayerRange;
  className?: string;
  /** Called as playback moves (display seconds; e.g. to follow along in a transcript). */
  onTime?: (seconds: number) => void;
}

export interface PlayerHandle {
  /** Shows the frame that contains ``t`` (S11: a transcript click lands within a frame). */
  seekTo: (t: SourceTime) => void;
  toggle: () => void;
  /** Gives the player keyboard focus (J/K/L, Space, arrows). */
  focus: () => void;
}

const L_RATES = [1, 1.5, 2, 4];

/**
 * Proxy playback (COMPONENTS.md Player). HTTP range requests come from the browser's
 * video element. Keys: Space play/pause · J back 5 s · K pause · L play (again: faster)
 * · ←/→ one frame · Shift+←/→ one second.
 */
export const Player = forwardRef<PlayerHandle, PlayerProps>(function Player(
  { src, poster, rate, usableRange, markers = [], range, className, onTime },
  ref,
) {
  const video = useRef<HTMLVideoElement>(null);
  const root = useRef<HTMLDivElement>(null);
  const [time, setTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [playing, setPlaying] = useState(false);
  const frame = 1 / fps(rate);
  const lo = range ? seconds(range.start) : 0;
  const hi = range ? seconds(range.end) : duration;

  const seek = useCallback(
    (t: number) => {
      const v = video.current;
      if (!v) return;
      const clamped = Math.min(Math.max(t, lo), hi || v.duration || t);
      v.currentTime = clamped;
      setTime(clamped);
    },
    [lo, hi],
  );

  // Seek to the range only when its values change: callers pass a new object each render.
  const rangeKey = range ? `${range.start.ticks}/${range.start.tb}-${range.end.ticks}/${range.end.tb}` : "";
  useEffect(() => {
    if (rangeKey && video.current) seek(lo);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- keyed on the range's values
  }, [rangeKey]);

  const toggle = () => {
    const v = video.current;
    if (!v) return;
    if (v.paused) {
      if (range && v.currentTime >= hi - 1e-3) seek(lo); // replaying a finished range
      void v.play();
    } else v.pause();
  };

  useImperativeHandle(ref, () => ({
    seekTo: (t) => {
      // A quarter into the frame that contains t, so the decoder shows exactly that frame;
      // never past the clip's last frame.
      const v = video.current;
      const end = v && Number.isFinite(v.duration) ? v.duration : Infinity;
      const last = Number.isFinite(end) ? Math.max(0, Math.ceil(end / frame) - 1) : Infinity;
      seek((Math.min(frameIndex(t, rate), last) + 0.25) * frame);
    },
    toggle,
    focus: () => root.current?.focus({ preventScroll: true }),
  }));

  const onKey = (e: KeyboardEvent) => {
    const v = video.current;
    if (!v) return;
    const step = e.shiftKey ? 1 : frame;
    switch (e.key) {
      case " ":
        toggle();
        break;
      case "k":
      case "K":
        v.pause();
        break;
      case "l":
      case "L": {
        if (v.paused) {
          v.playbackRate = 1;
          void v.play();
        } else {
          const i = L_RATES.indexOf(v.playbackRate);
          v.playbackRate = L_RATES[Math.min(L_RATES.length - 1, i + 1)] ?? 1;
        }
        break;
      }
      case "j":
      case "J":
        seek(v.currentTime - 5);
        break;
      case "ArrowLeft":
        v.pause();
        seek(v.currentTime - step);
        break;
      case "ArrowRight":
        v.pause();
        seek(v.currentTime + step);
        break;
      default:
        return;
    }
    e.preventDefault();
  };

  const onBar = (e: PointerEvent<HTMLDivElement>) => {
    const r = e.currentTarget.getBoundingClientRect();
    if (!duration) return;
    seek(((e.clientX - r.left) / r.width) * duration);
  };

  const pct = (t: number) => (duration ? `${(Math.min(Math.max(t, 0), duration) / duration) * 100}%` : "0%");

  return (
    <div
      ref={root}
      tabIndex={0}
      onKeyDown={onKey}
      aria-label="Player"
      className={cn(
        "flex flex-col gap-2 rounded-lg focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent",
        className,
      )}
    >
      <div className="relative aspect-video overflow-hidden rounded-md bg-black">
        {src ? (
          <video
            ref={video}
            src={src}
            poster={poster}
            preload="metadata"
            playsInline
            className="size-full object-contain"
            onClick={toggle}
            onPlay={() => setPlaying(true)}
            onPause={() => setPlaying(false)}
            onLoadedMetadata={(e) => setDuration(e.currentTarget.duration)}
            onTimeUpdate={(e) => {
              const t = e.currentTarget.currentTime;
              setTime(t);
              onTime?.(t);
              if (range && t >= hi) e.currentTarget.pause();
            }}
          />
        ) : (
          <div className="flex size-full items-center justify-center text-small text-on-media/70">
            No preview yet
          </div>
        )}
      </div>
      <div className="flex items-center gap-3">
        <button
          type="button"
          aria-label={playing ? "Pause" : "Play"}
          onClick={toggle}
          onKeyDown={(e) => e.key === " " && e.stopPropagation()} // the button's own click toggles
          disabled={!src}
          className="rounded-sm p-1 text-text hover:bg-surface-2 focus-visible:outline-2 focus-visible:outline-accent disabled:opacity-50"
        >
          {playing ? <Pause className="size-4" /> : <Play className="size-4" />}
        </button>
        <div
          role="slider"
          tabIndex={0}
          aria-label="Position"
          aria-valuemin={0}
          aria-valuemax={Math.round(duration)}
          aria-valuenow={Math.round(time)}
          aria-valuetext={formatClock(time)}
          onPointerDown={onBar}
          className="relative h-2 flex-1 cursor-pointer rounded-full bg-surface-3"
        >
          {usableRange && (
            <div
              data-testid="usable-range"
              className="absolute inset-y-0 rounded-full bg-use/35"
              style={{ left: pct(seconds(usableRange.start)), right: `calc(100% - ${pct(seconds(usableRange.end))})` }}
            />
          )}
          <div className="absolute inset-y-0 left-0 rounded-full bg-accent/40" style={{ width: pct(time) }} />
          {markers.map((m) => (
            <span
              key={`${m.kind}-${m.at.ticks}`}
              title={m.label}
              className={cn(
                "absolute top-1/2 size-2 -translate-x-1/2 -translate-y-1/2 rounded-full",
                m.kind === "finding" ? "bg-maybe" : "bg-info",
              )}
              style={{ left: pct(seconds(m.at)) }}
            />
          ))}
          <span
            aria-hidden
            className="absolute top-1/2 h-3.5 w-0.5 -translate-x-1/2 -translate-y-1/2 rounded-full bg-accent"
            style={{ left: pct(time) }}
          />
        </div>
        <span className="mono text-timecode-sm text-text-muted">
          {formatClock(time)} / {formatClock(duration)}
        </span>
      </div>
    </div>
  );
});
