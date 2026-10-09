import { Film, RotateCw } from "lucide-react";
import { useState, type ReactNode } from "react";

import { Banner } from "@/components/ui/Banner";
import { Button } from "@/components/ui/Button";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { cn } from "@/lib/cn";
import { formatBytes } from "@/lib/format";
import { renderStatusText, renderTime, type RenderRow, type RenderStatus } from "@/lib/renders";

export interface ExportsViewProps {
  /** Where the files are saved (the project's renders folder). */
  folder: string | null;
  items: RenderRow[] | undefined;
  error?: boolean;
  onRetry?: () => void;
  hasMore?: boolean;
  loadingMore?: boolean;
  onMore?: () => void;
  coverUrl: (sampleId: number) => string;
  fileUrl: (r: RenderRow, download: boolean) => string;
  onCancel: (r: RenderRow) => void;
  onRerender: (r: RenderRow) => void;
  onDeleteFile: (r: RenderRow) => void;
  onEdits: () => void;
  /** Rows with an action in flight: their buttons wait. */
  busy?: ReadonlySet<number>;
}

const DOT: Record<RenderStatus, string> = {
  queued: "bg-text-faint",
  rendering: "bg-accent",
  paused: "bg-maybe",
  done: "bg-use",
  failed: "bg-reject",
  cancelled: "bg-text-faint",
  deleted: "bg-text-faint",
  missing: "bg-maybe",
};

const COLS = "grid grid-cols-[120px_1.6fr_1fr_1fr_1fr_auto] items-center gap-4";

/** S20 Exports: the render queue and history (the one place a list is fine). */
export function ExportsView(p: ExportsViewProps) {
  const [details, setDetails] = useState<RenderRow | null>(null);
  const [deleting, setDeleting] = useState<RenderRow | null>(null);
  return (
    <div className="flex min-h-0 flex-1 flex-col gap-[18px] overflow-y-auto px-8 py-7">
      <div className="flex flex-col gap-1">
        <h1 className="text-title tracking-[-0.01em] text-text">Exports</h1>
        {p.folder && (
          <p className="text-body text-text-muted">
            Renders are saved in <span className="mono text-timecode">{p.folder}</span>.
          </p>
        )}
      </div>
      {p.error ? (
        <Banner
          kind="danger"
          action={
            <Button size="sm" onClick={p.onRetry}>
              Try again
            </Button>
          }
        >
          We couldn't load your exports.
        </Banner>
      ) : !p.items ? (
        <div aria-label="Loading exports" className="h-64 animate-pulse rounded-lg bg-surface-1" />
      ) : p.items.length === 0 ? (
        <div className="flex flex-col items-center gap-4 rounded-lg border border-dashed border-border px-8 py-16 text-center">
          <Film aria-hidden className="size-8 text-text-muted" />
          <h2 className="text-heading text-text">No exports yet</h2>
          <p className="max-w-[440px] text-body text-text-muted">Open an edit to watch its preview, then render the final. Every render shows here.</p>
          <Button onClick={p.onEdits}>Go to Edits</Button>
        </div>
      ) : (
        <div role="table" aria-label="Exports" className="overflow-hidden rounded-lg border border-border bg-surface-1">
          <div role="row" className={cn(COLS, "border-b border-border px-4 py-2.5 text-caption font-normal text-text-faint")}>
            <span role="columnheader">
              <span className="sr-only">Cover</span>
            </span>
            <span role="columnheader">Edit</span>
            <span role="columnheader">Status</span>
            <span role="columnheader">Size</span>
            <span role="columnheader">Time</span>
            <span role="columnheader" className="w-[220px]">
              <span className="sr-only">Actions</span>
            </span>
          </div>
          {p.items.map((r) => (
            <Row key={r.render_id} r={r} p={p} onDetails={setDetails} onDelete={setDeleting} />
          ))}
        </div>
      )}
      {p.hasMore && (
        <Button variant="ghost" className="self-center" disabled={p.loadingMore} onClick={p.onMore}>
          {p.loadingMore ? "Loading…" : "Show more"}
        </Button>
      )}
      <ConfirmDialog
        open={details !== null}
        onOpenChange={(o) => !o && setDetails(null)}
        title="Why the render stopped"
        body={<p className="mono text-timecode break-words text-text">{details?.error ?? "The render stopped without saying why. Try rendering it again."}</p>}
        actions={[
          { label: "Close", variant: "ghost", onClick: () => setDetails(null) },
          {
            label: "Re-render",
            variant: "primary",
            disabled: details !== null && Boolean(p.busy?.has(details.render_id)),
            onClick: () => {
              if (details) p.onRerender(details);
              setDetails(null);
            },
          },
        ]}
      />
      <ConfirmDialog
        open={deleting !== null}
        onOpenChange={(o) => !o && setDeleting(null)}
        title="Delete this file?"
        body={<p className="text-body text-text-muted">The video file is removed from the renders folder. The edit stays, and you can render it again at any time.</p>}
        actions={[
          { label: "Keep it", variant: "ghost", onClick: () => setDeleting(null) },
          {
            label: "Delete file",
            variant: "danger",
            onClick: () => {
              if (deleting) p.onDeleteFile(deleting);
              setDeleting(null);
            },
          },
        ]}
      />
    </div>
  );
}

function Row({ r, p, onDetails, onDelete }: { r: RenderRow; p: ExportsViewProps; onDetails: (r: RenderRow) => void; onDelete: (r: RenderRow) => void }) {
  const busy = p.busy?.has(r.render_id);
  const portrait = r.height > r.width;
  const name = r.edit_name ?? r.display_id;
  let actions: ReactNode;
  switch (r.status) {
    case "queued":
      actions = <Act onClick={() => p.onCancel(r)} disabled={busy} label={`Remove ${name} v${r.version} from the queue`}>Remove</Act>;
      break;
    case "rendering":
    case "paused":
      actions = <Act onClick={() => p.onCancel(r)} disabled={busy} label={`Cancel ${name} v${r.version}`}>Cancel</Act>;
      break;
    case "done":
      actions = (
        <>
          <Button size="sm" asChild>
            <a href={p.fileUrl(r, false)} target="_blank" rel="noreferrer" aria-label={`Open ${name} v${r.version}`}>
              Open
            </a>
          </Button>
          <Button size="sm" variant="ghost" asChild>
            <a href={p.fileUrl(r, true)} download aria-label={`Download ${name} v${r.version}`}>
              Download
            </a>
          </Button>
          <Act onClick={() => onDelete(r)} disabled={busy} label={`Delete the file of ${name} v${r.version}`}>
            Delete
          </Act>
        </>
      );
      break;
    case "failed":
      actions = (
        <>
          <Act onClick={() => onDetails(r)} label={`Details of ${name} v${r.version}`}>
            Details
          </Act>
          <Button size="sm" disabled={busy} onClick={() => p.onRerender(r)} aria-label={`Re-render ${name} v${r.version}`}>
            <RotateCw /> Re-render
          </Button>
        </>
      );
      break;
    default:
      actions = (
        <Button size="sm" disabled={busy} onClick={() => p.onRerender(r)} aria-label={`Re-render ${name} v${r.version}`}>
          <RotateCw /> Re-render
        </Button>
      );
  }
  const time = r.status === "failed" && r.pct != null ? `Stopped at ${r.pct}%` : r.status === "done" ? renderTime(r.seconds) : "—";
  return (
    <div role="row" className={cn(COLS, "border-b border-border px-4 py-3 last:border-b-0")}>
      <span role="cell" className="flex aspect-video items-center justify-center overflow-hidden rounded-md bg-surface-2">
        {r.cover_sample_id != null && <img src={p.coverUrl(r.cover_sample_id)} alt="" loading="lazy" className={cn("h-full object-cover", portrait ? "aspect-[9/16]" : "w-full")} />}
      </span>
      <span role="cell" className="flex min-w-0 flex-col gap-1">
        <span className="truncate text-body font-medium text-text">{name}</span>
        <span className="flex items-center gap-1.5">
          <span className="rounded-full border border-border bg-surface-2 px-[9px] py-[3px] text-micro font-medium text-text-muted">v{r.version}</span>
          <span className="text-caption font-normal text-text-muted">{r.label}</span>
        </span>
      </span>
      <span role="cell" className="flex flex-col gap-1.5">
        <span className="flex items-center gap-1.5 text-small text-text">
          <span aria-hidden className={cn("size-2 shrink-0 rounded-full", DOT[r.status])} />
          {renderStatusText(r)}
        </span>
        {r.status === "rendering" && (
          <span className="h-1 overflow-hidden rounded-full bg-surface-3">
            <span className="block h-full rounded-full bg-accent transition-[width] duration-300" style={{ width: `${r.pct ?? 0}%` }} />
          </span>
        )}
      </span>
      <span role="cell" className="mono text-timecode-sm text-text-muted">
        {r.size_bytes != null ? formatBytes(r.size_bytes) : "—"}
      </span>
      <span role="cell" className="mono text-timecode-sm text-text-muted">
        {time}
      </span>
      <span role="cell" className="flex w-[220px] justify-end gap-1.5">
        {actions}
      </span>
    </div>
  );
}

function Act({ children, onClick, disabled, label }: { children: ReactNode; onClick: () => void; disabled?: boolean; label?: string }) {
  return (
    <Button size="sm" variant="ghost" disabled={disabled} onClick={onClick} aria-label={label}>
      {children}
    </Button>
  );
}
