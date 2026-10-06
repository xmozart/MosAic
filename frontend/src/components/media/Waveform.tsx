import { cn } from "@/lib/cn";

export interface WaveformProps {
  peaks: Uint8Array; // 0–255, one per bucket (GET /media/.../waveform)
  /** Highlighted part (selection), as fractions 0–1 of the clip. */
  selection?: [number, number];
  /** Playhead as a fraction 0–1. */
  position?: number;
  height?: number;
  className?: string;
}

const BARS = 160;

/** Waveform of a clip's sound (COMPONENTS.md Waveform): bars reduced to the width. */
export function Waveform({ peaks, selection, position, height = 40, className }: WaveformProps) {
  const n = Math.min(BARS, peaks.length);
  const bars = Array.from({ length: n }, (_, i) => {
    const a = Math.floor((i * peaks.length) / n);
    const b = Math.max(a + 1, Math.floor(((i + 1) * peaks.length) / n));
    let m = 0;
    for (let j = a; j < b; j++) m = Math.max(m, peaks[j] ?? 0);
    return m / 255;
  });
  if (!peaks.length) {
    return <div className={cn("text-caption font-normal text-text-faint", className)}>No sound</div>;
  }
  return (
    <svg
      role="img"
      aria-label="Sound waveform"
      viewBox={`0 0 ${n} 100`}
      preserveAspectRatio="none"
      className={cn("w-full", className)}
      style={{ height }}
    >
      {selection && (
        <rect x={selection[0] * n} width={(selection[1] - selection[0]) * n} y={0} height={100} className="fill-accent-soft" />
      )}
      {bars.map((v, i) => {
        const h = Math.max(2, v * 100);
        const inSel = selection ? i / n >= selection[0] && i / n < selection[1] : true;
        return (
          <rect
            key={i}
            x={i + 0.15}
            width={0.7}
            y={50 - h / 2}
            height={h}
            className={inSel ? "fill-text-muted" : "fill-text-faint"}
          />
        );
      })}
      {position !== undefined && <rect x={position * n - 0.15} width={0.3} y={0} height={100} className="fill-accent" />}
    </svg>
  );
}
