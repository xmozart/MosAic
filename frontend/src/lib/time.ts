/**
 * Exact media times from the API (CLAUDE.md invariant 3): integer ticks in a time base,
 * e.g. `{ticks: 4026240, tb: "1/90000"}`. Seconds are for display and for the video
 * element only, computed here and never sent back as authoritative values.
 */
export interface SourceTime {
  ticks: number;
  tb: string;
}

export function parseRational(r: string): [number, number] {
  const [n, d] = r.split("/");
  const num = Number(n);
  const den = d === undefined ? 1 : Number(d);
  if (!Number.isFinite(num) || !Number.isFinite(den) || den === 0) throw new Error(`bad rational ${r}`);
  return [num, den];
}

/** Display seconds of an exact time. */
export function seconds(t: SourceTime): number {
  const [n, d] = parseRational(t.tb);
  return (t.ticks * n) / d;
}

/** Frames per second of a rate like "30000/1001". */
export function fps(rate: string): number {
  const [n, d] = parseRational(rate);
  return n / d;
}

/** "0:48", "4:02", "1:02:03" — durations and timecodes are mono in the UI. */
export function formatClock(s: number): string {
  const total = Math.max(0, Math.floor(s + 1e-6));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const sec = total % 60;
  const ss = String(sec).padStart(2, "0");
  return h > 0 ? `${h}:${String(m).padStart(2, "0")}:${ss}` : `${m}:${ss}`;
}
