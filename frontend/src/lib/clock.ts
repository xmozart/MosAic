/** Clock offsets as S5 and S6 show them (ADR 0027). An offset is the correction added to a
 * camera's clock: negative means the camera was ahead. Integer milliseconds throughout. */
export const HOUR_MS = 3_600_000;
export const MINUTE_MS = 60_000;
const DAY_MS = 24 * HOUR_MS;

const pad = (n: number) => String(n).padStart(2, "0");

/** The stepper's value: "−5 h 00 m", "+1 d 00 h", "0 h 00 m". */
export function formatOffset(ms: number): string {
  const sign = ms < 0 ? "−" : ms > 0 ? "+" : "";
  const mins = Math.round(Math.abs(ms) / MINUTE_MS); // whole minutes first: never "60 m"
  const d = Math.floor(mins / 1440);
  const h = Math.floor((mins % 1440) / 60);
  const m = mins % 60;
  if (d) return `${sign}${d} d ${pad(h)} h${m ? ` ${pad(m)} m` : ""}`;
  return `${sign}${h} h ${pad(m)} m`;
}

/** The camera card's short question: "5 h ahead", "1 day behind", "12 min ahead". */
export function shortVerdict(ms: number): string {
  const word = ms < 0 ? "ahead" : "behind"; // the fix moves the clock the other way
  const abs = Math.abs(ms);
  const days = Math.round(abs / DAY_MS);
  if (abs >= DAY_MS - HOUR_MS && Math.abs(abs - days * DAY_MS) < HOUR_MS) {
    return `${days} day${days === 1 ? "" : "s"} ${word}`;
  }
  if (abs >= HOUR_MS) return `${Math.round(abs / HOUR_MS)} h ${word}`;
  return `${Math.max(1, Math.round(abs / MINUTE_MS))} min ${word}`;
}

/** "Jul 15 10:42" from an ISO time, as the camera recorded it (no zone conversion). */
export function shortStamp(iso: string): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/.exec(iso);
  if (!m) return iso;
  const month = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"][Number(m[2]) - 1];
  return `${month} ${Number(m[3])} ${m[4]}:${m[5]}`;
}

/** S6's verdict: "5 h 00 m ahead", "1 day behind", "12 min ahead". */
export function verdict(ms: number): string {
  const mins = Math.round(Math.abs(ms) / MINUTE_MS);
  if (mins >= 23 * 60 || mins < 60) return shortVerdict(ms);
  const word = ms < 0 ? "ahead" : "behind";
  return `${Math.floor(mins / 60)} h ${pad(mins % 60)} m ${word}`;
}
