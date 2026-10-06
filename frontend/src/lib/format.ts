/** Display formats (VOICE.md: numbers, durations, dates). */

export function formatDuration(seconds: number): string {
  const s = Math.max(0, Math.round(seconds));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  if (h) return `${h} h ${String(m).padStart(2, "0")} m`;
  if (m) return `${m} m`;
  return `${s} s`;
}

const MONTH = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** "Jul 14–24, 2026", "Mar 2 – Apr 3, 2026", "Dec 30, 2025 – Jan 2, 2026" from ISO dates. */
export function formatDateRange(first: string | null, last: string | null): string | null {
  if (!first) return null;
  const [y1, m1, d1] = first.split("-").map(Number) as [number, number, number];
  const [y2, m2, d2] = (last ?? first).split("-").map(Number) as [number, number, number];
  const a = `${MONTH[m1 - 1]} ${d1}`;
  if (y1 !== y2) return `${a}, ${y1} – ${MONTH[m2 - 1]} ${d2}, ${y2}`;
  if (m1 !== m2) return `${a} – ${MONTH[m2 - 1]} ${d2}, ${y2}`;
  if (d1 !== d2) return `${a}–${d2}, ${y1}`;
  return `${a}, ${y1}`;
}

export function plural(n: number, one: string, many = `${one}s`): string {
  return `${n.toLocaleString("en-US")} ${n === 1 ? one : many}`;
}

/** "Today", "Yesterday", "Oct 2". */
export function formatOpened(iso: string, now: Date = new Date()): string {
  const d = new Date(iso);
  const day = (x: Date) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();
  const diff = Math.round((day(now) - day(d)) / 86_400_000);
  if (diff === 0) return "Today";
  if (diff === 1) return "Yesterday";
  return `${MONTH[d.getMonth()]} ${d.getDate()}`;
}

/** "Jul 14–24" (the year left out where the screen already places the trip). */
export function formatShortRange(first: string | null, last: string | null): string | null {
  return formatDateRange(first, last)?.replace(/, \d{4}$/, "").replace(/, \d{4} – /, " – ") ?? null;
}

/** "Jul 14" from an ISO date. */
export function formatDay(iso: string): string {
  const [, m, d] = iso.split("-").map(Number) as [number, number, number];
  return `${MONTH[m - 1]} ${d}`;
}

/** Whole days from ``first`` to ``date`` plus one: the trip's day number. */
export function tripDay(first: string, date: string): number {
  const utc = (iso: string) => {
    const [y, m, d] = iso.split("-").map(Number) as [number, number, number];
    return Date.UTC(y, m - 1, d);
  };
  return Math.round((utc(date) - utc(first)) / 86_400_000) + 1;
}

/** "48 GB", "820 MB" (decimal units, as the OS shows sizes). */
export function formatBytes(bytes: number): string {
  const units = ["B", "KB", "MB", "GB", "TB"];
  let v = bytes;
  let i = 0;
  while (v >= 1000 && i < units.length - 1) {
    v /= 1000;
    i++;
  }
  return `${v >= 10 || i === 0 ? Math.round(v) : v.toFixed(1)} ${units[i]}`;
}
