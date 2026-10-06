import { Check, Clock } from "lucide-react";
import type { ReactNode } from "react";

import { UnsupportedRow } from "@/components/system/UnsupportedRow";
import { Button } from "@/components/ui/Button";
import { CAMERA_ICONS } from "@/lib/cameraIcons";
import { shortVerdict } from "@/lib/clock";
import { cn } from "@/lib/cn";
import { formatBytes, formatDay, formatDuration, formatShortRange, plural, tripDay } from "@/lib/format";

import { attentionKey, type Attention, type Camera, type Inventory } from "./model";

/** Camera series colours (cam-1…6 tokens, ADR 0040); further cameras repeat them. */
const CAM_BG = ["bg-cam-1", "bg-cam-2", "bg-cam-3", "bg-cam-4", "bg-cam-5", "bg-cam-6"];
const camBg = (i: number) => CAM_BG[i % CAM_BG.length]!;

function countLine(c: Camera): string {
  const parts: string[] = [];
  if (c.clips) {
    const chaptered = c.files > c.clips + c.photos;
    let clips = plural(c.clips, chaptered ? "recording" : "clip");
    if (chaptered) clips += ` (${plural(c.files, "file")})`;
    else if (c.limited) clips += ` (${c.limited.toLocaleString("en-US")} ${c.limited === 1 ? "is" : "are"} 360°)`;
    parts.push(clips);
  }
  if (c.photos) parts.push(plural(c.photos, "photo"));
  if (c.footage_seconds) parts.push(formatDuration(c.footage_seconds));
  return parts.join(" · ");
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col gap-0.5">
      <dt className="text-caption font-normal text-text-muted">{label}</dt>
      <dd className="text-title text-text">{value}</dd>
    </div>
  );
}

function Panel({ title, aside, children, className }: { title: ReactNode; aside?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={cn("flex flex-col gap-3 rounded-lg border border-border bg-surface-1 p-5", className)}>
      <header className="flex items-center gap-2">
        <h2 className="text-subhead font-semibold text-text">{title}</h2>
        {aside && <span className="ml-auto">{aside}</span>}
      </header>
      {children}
    </section>
  );
}

function CameraCard({ c, frame }: { c: Camera; frame: string | null }) {
  const Icon = CAMERA_ICONS[c.kind] ?? CAMERA_ICONS.camera;
  return (
    <article className="flex flex-col overflow-hidden rounded-lg border border-border bg-surface-1">
      <div className="aspect-video bg-surface-3">{frame && <img src={frame} alt="" className="size-full object-cover" />}</div>
      <div className="flex flex-col gap-1.5 px-3.5 py-3">
        <h3 className="flex items-center gap-1.5 text-body font-semibold text-text">
          <Icon aria-hidden className="size-4 shrink-0 text-text-muted" />
          <span className="truncate">{c.label}</span>
        </h3>
        <p className="text-caption font-normal text-text-muted">{countLine(c)}</p>
        {c.badges.length > 0 && (
          <ul className="flex flex-wrap gap-1">
            {c.badges.map((b) => (
              <li key={b} className="rounded-full border border-border bg-surface-2 px-2 py-0.5 text-tag font-medium text-text-muted">
                {b}
              </li>
            ))}
          </ul>
        )}
        {c.clock && (
          <p className="flex items-center gap-1.5 text-caption font-normal text-maybe">
            <Clock aria-hidden className="size-3.5" />
            Clock {shortVerdict(c.clock.offset_ms)}?
          </p>
        )}
      </div>
    </article>
  );
}

function CameraSkeleton() {
  return (
    <div aria-hidden className="flex flex-col overflow-hidden rounded-lg border border-border bg-surface-1">
      <div className="aspect-video animate-pulse bg-surface-3" />
      <div className="flex flex-col gap-2 px-3.5 py-3">
        <div className="h-4 w-3/4 animate-pulse rounded-sm bg-surface-3" />
        <div className="h-3 w-1/2 animate-pulse rounded-sm bg-surface-2" />
      </div>
    </div>
  );
}

function TripTimeline({ inv }: { inv: Inventory }) {
  const order = inv.cameras.map((c) => c.key);
  const label = Object.fromEntries(inv.cameras.map((c) => [c.key, c.label]));
  const first = inv.days[0]?.date;
  const max = Math.max(1, ...inv.days.map((d) => Object.values(d.by_camera).reduce((a, b) => a + b, 0)));
  return (
    <Panel
      title="Trip timeline"
      aside={
        <ul aria-label="Cameras" className="flex flex-wrap items-center gap-3.5">
          {inv.cameras.map((c, i) => (
            <li key={c.key} className="flex items-center gap-1.5 text-micro font-normal text-text-muted">
              <span aria-hidden className={cn("size-2 rounded-full", camBg(i))} />
              {c.label}
            </li>
          ))}
        </ul>
      }
    >
      {inv.days.length === 0 ? (
        <p className="text-small text-text-muted">No capture dates found yet.</p>
      ) : (
        <ol className="flex items-end gap-2">
          {inv.days.map((d) => {
            const n = first ? tripDay(first, d.date) : 0;
            const parts = order.filter((k) => (d.by_camera[k] ?? 0) > 0);
            const words = parts.map((k) => `${label[k]} ${formatDuration(d.by_camera[k]!)}`).join(", ");
            return (
              <li key={d.date} className="flex min-w-0 flex-1 flex-col items-center gap-1.5" aria-label={`Day ${n}, ${formatDay(d.date)}${words ? `: ${words}` : ": photos only"}`}>
                <div className="flex h-[150px] w-full flex-col-reverse gap-px overflow-hidden rounded-sm">
                  {parts.map((k) => (
                    <div
                      key={k}
                      className={camBg(order.indexOf(k))}
                      style={{ height: `${(100 * d.by_camera[k]!) / max}%` }}
                    />
                  ))}
                </div>
                <span className="mono text-timecode-sm text-text-muted">D{n}</span>
              </li>
            );
          })}
        </ol>
      )}
    </Panel>
  );
}

function clockSentence(cams: Camera[]): string {
  const said = cams.map((c, i) => (i === 0 ? `${c.label} looks ${shortVerdict(c.clock!.offset_ms)}` : `${c.label} ${shortVerdict(c.clock!.offset_ms)}`));
  const joined = said.length > 1 ? `${said.slice(0, -1).join(", ")} and ${said.at(-1)}` : said[0];
  return `${joined}. Fixing this keeps your story in order.`;
}

function ClockCard({ cams, onReview }: { cams: Camera[]; onReview: () => void }) {
  return (
    <section className="flex items-center gap-3.5 rounded-lg border border-border bg-surface-1 p-[18px]">
      <div className="flex min-w-0 flex-1 flex-col gap-0.5">
        <h2 className="text-subhead font-semibold text-text">
          {cams.length ? `${plural(cams.length, "camera")} may have the wrong time` : "Camera clocks"}
        </h2>
        <p className="text-small text-text-muted">
          {cams.length
            ? clockSentence(cams)
            : "No clock problems found so far. Cameras are compared once the analysis has run, and you can set a clock by hand."}
        </p>
      </div>
      <Button onClick={onReview}>Review clocks</Button>
    </section>
  );
}

export interface InventoryViewProps {
  inv: Inventory | undefined;
  scanning: boolean;
  frameUrl: (sampleId: number) => string;
  hidden: ReadonlySet<string>;
  /** Percent of a running cloud download, or null. */
  downloadPct: number | null;
  onShowFiles: (a: Attention) => void;
  onHide: (a: Attention) => void;
  onDownload: () => void;
  onReviewClocks: () => void;
  onContinue: () => void;
}

/** S5 Inventory: what the scan found, before analysis. Nothing is changed here. */
export function InventoryView(p: InventoryViewProps) {
  const inv = p.inv;
  const attention = (inv?.attention ?? []).filter((a) => !p.hidden.has(attentionKey(a)));
  const clocks = (inv?.cameras ?? []).filter((c) => c.clock);
  const notes = inv
    ? [
        inv.notes.chaptered_recordings && `Chapters joined into ${plural(inv.notes.chaptered_recordings, "recording")}`,
        inv.notes.live_photos && `${plural(inv.notes.live_photos, "Live Photo")} paired`,
        inv.notes.bursts && `${plural(inv.notes.bursts, "photo burst")} grouped`,
      ].filter(Boolean)
    : [];
  const showCards = inv && inv.cameras.length > 0;
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex flex-1 flex-col gap-[22px] overflow-y-auto px-8 py-7">
        <div className="flex items-start gap-6">
          <div className="flex flex-col gap-1">
            <h1 className="text-title text-text">Here's what we found</h1>
            <p className="text-body text-text-muted">Nothing has been changed. Review anything that needs attention, then continue.</p>
          </div>
          {inv && (
            <dl className="ml-auto flex gap-12">
              <Stat label="Footage" value={formatDuration(inv.summary.footage_seconds)} />
              <Stat label="Clips" value={inv.summary.clips.toLocaleString("en-US")} />
              <Stat label="Photos" value={inv.summary.photos.toLocaleString("en-US")} />
              <Stat label="Dates" value={formatShortRange(inv.summary.first_date, inv.summary.last_date) ?? "—"} />
              <Stat label="Cameras" value={String(inv.summary.cameras)} />
            </dl>
          )}
        </div>

        <div className="grid grid-cols-5 gap-3.5" aria-busy={p.scanning || undefined}>
          {showCards && inv.cameras.map((c) => <CameraCard key={c.key} c={c} frame={c.sample_id ? p.frameUrl(c.sample_id) : null} />)}
          {(p.scanning || !inv) && Array.from({ length: Math.max(1, 5 - (inv?.cameras.length ?? 0)) }, (_, i) => <CameraSkeleton key={i} />)}
          {inv && !p.scanning && inv.cameras.length === 0 && (
            <p className="col-span-5 text-body text-text-muted">No videos or photos were found in this folder.</p>
          )}
        </div>

        {inv && (
          <div className="grid grid-cols-[1.1fr_1fr] items-start gap-[18px]">
            <div className="flex flex-col gap-[18px]">
              <TripTimeline inv={inv} />
              <ClockCard cams={clocks} onReview={p.onReviewClocks} />
            </div>
            {attention.length === 0 ? (
              <section className="flex flex-col gap-2 rounded-lg border border-border bg-surface-1 p-[18px]">
                <p className="flex items-center gap-2 text-body text-use">
                  <Check aria-hidden className="size-4" /> Nothing needs attention.
                </p>
                {notes.length > 0 && <p className="text-caption font-normal text-text-muted">{notes.join(" · ")}</p>}
              </section>
            ) : (
              <section aria-labelledby="needs-attention" className="flex flex-col rounded-lg border border-border bg-surface-1 px-[18px] pt-[18px] pb-3">
                <header className="flex items-center gap-2">
                  <h2 id="needs-attention" className="text-subhead font-semibold text-text">
                    Needs attention
                  </h2>
                  <span className="rounded-full border border-maybe px-2 py-0.5 text-micro font-medium text-maybe">{attention.length}</span>
                </header>
                {attention.map((a) => (
                  <AttentionRow key={attentionKey(a)} a={a} {...p} />
                ))}
                {notes.length > 0 && <p className="pt-1 text-caption font-normal text-text-muted">{notes.join(" · ")}</p>}
              </section>
            )}
          </div>
        )}
      </div>
      <footer className="sticky bottom-0 flex h-[68px] shrink-0 items-center gap-2.5 border-t border-border bg-surface-1 px-8">
        <p className="text-small text-text-muted">Next: optional trip details, then analysis</p>
        <Button variant="primary" className="ml-auto" onClick={p.onContinue}>
          Continue
        </Button>
      </footer>
    </div>
  );
}

function AttentionRow({ a, ...p }: { a: Attention } & InventoryViewProps) {
  const reason = [a.example && a.reason ? `${a.example}: ${a.reason}` : (a.reason ?? a.example), a.fix].filter(Boolean).join(" ");
  if (a.kind === "cloud") {
    const running = p.downloadPct !== null;
    return (
      <UnsupportedRow
        kind="cloud"
        title={`${plural(a.count, "file")}${a.bytes ? ` (${formatBytes(a.bytes)})` : ""} ${a.count === 1 ? "is" : "are"} only in the cloud`}
        reason={a.reason ?? ""}
        progress={
          running && (
            <div className="mt-1.5 flex items-center gap-2" role="progressbar" aria-label="Downloading" aria-valuenow={p.downloadPct ?? 0} aria-valuemin={0} aria-valuemax={100}>
              <div className="h-1 w-40 overflow-hidden rounded-full bg-surface-3">
                <div className="h-full bg-accent" style={{ width: `${p.downloadPct}%` }} />
              </div>
              <span className="mono text-timecode-sm text-text-muted">Downloading… {p.downloadPct}%</span>
            </div>
          )
        }
        actions={
          !running && (
            <>
              <Button size="sm" onClick={p.onDownload}>
                Download now
              </Button>
              <Button size="sm" variant="ghost" onClick={() => p.onHide(a)}>
                Skip these
              </Button>
            </>
          )
        }
      />
    );
  }
  if (a.kind === "limited") {
    return (
      <UnsupportedRow
        kind="limited"
        title={`${plural(a.count, "clip")} ${a.count === 1 ? "is" : "are"} 360°`}
        reason={reason}
        actions={
          <Button size="sm" variant="ghost" onClick={() => p.onShowFiles(a)}>
            Show files
          </Button>
        }
      />
    );
  }
  return (
    <UnsupportedRow
      kind={a.count === 1 ? "damaged" : "unreadable"}
      title={`${plural(a.count, "file")} can't be read`}
      reason={reason}
      actions={
        <>
          <Button size="sm" variant="ghost" onClick={() => p.onShowFiles(a)}>
            {a.count === 1 ? "Show" : "Show files"}
          </Button>
          <Button size="sm" variant="ghost" onClick={() => p.onHide(a)}>
            Ignore
          </Button>
        </>
      }
    />
  );
}
