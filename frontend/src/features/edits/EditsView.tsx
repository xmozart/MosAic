import { Clapperboard, Copy, RectangleVertical, Sparkles } from "lucide-react";
import type { ReactNode } from "react";

import { EditCard } from "@/components/edit/EditCard";
import { Banner } from "@/components/ui/Banner";
import { Button } from "@/components/ui/Button";

import { cardDuration, cardName, coverShape, createdText, formatLabel, startFromChips, statusWords, type EditCardData, type StartFrom } from "./model";

export interface EditsViewProps {
  items: EditCardData[] | undefined;
  error?: boolean;
  onRetry?: () => void;
  coverUrl: (sampleId: number) => string;
  renderLink: (edit: EditCardData, children: ReactNode, className: string) => ReactNode;
  onCreate: () => void;
  onStartFrom: (s: StartFrom) => void;
  now?: Date;
}

/** S13 Edits (M2 basic): every edit of the project as a card, newest first. */
export function EditsView(p: EditsViewProps) {
  const chips = p.items ? startFromChips(p.items) : [];
  return (
    <div className="flex min-h-0 flex-1 flex-col gap-[22px] overflow-y-auto px-8 py-7">
      <div className="flex items-center gap-4">
        <div className="flex flex-col gap-1">
          <h1 className="text-title tracking-[-0.01em] text-text">Edits</h1>
          <p className="text-body text-text-muted">Every edit is made from the same analyzed library — no re-analysis needed.</p>
        </div>
        <Button variant="primary" size="lg" className="ml-auto" onClick={p.onCreate}>
          <Sparkles /> Create edit
        </Button>
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
          We couldn't load your edits.
        </Banner>
      ) : !p.items ? (
        <div aria-label="Loading edits" className="grid grid-cols-4 gap-5">
          {[0, 1, 2, 3].map((i) => (
            <div key={i} className="aspect-[4/3] animate-pulse rounded-lg bg-surface-1" />
          ))}
        </div>
      ) : p.items.length === 0 ? (
        <div className="flex flex-col items-center gap-4 rounded-lg border border-dashed border-border px-8 py-16 text-center">
          <Clapperboard aria-hidden className="size-8 text-text-muted" />
          <h2 className="text-heading text-text">Create your first edit</h2>
          <p className="max-w-[440px] text-body text-text-muted">Pick a length, a shape and a story. MosAic picks the shots from your analyzed library.</p>
          <Button variant="primary" onClick={p.onCreate}>
            <Sparkles /> Create edit
          </Button>
        </div>
      ) : (
        <>
          <div className="grid grid-cols-4 gap-5">
            {p.items.map((e) => (
              <EditCard
                key={e.edit_id}
                name={cardName(e)}
                format={formatLabel(e.aspect, e.resolution)}
                shape={coverShape(e.aspect)}
                coverUrl={e.cover_sample_id != null ? p.coverUrl(e.cover_sample_id) : undefined}
                duration={cardDuration(e)}
                versions={e.versions}
                status={statusWords(e)}
                progress={e.status === "generating" ? (e.pct ?? 0) : null}
                created={createdText(e.created_at, p.now)}
                preliminary={e.preliminary}
                renderLink={(children, className) => p.renderLink(e, children, className)}
              />
            ))}
          </div>
          {chips.length > 0 && (
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-caption text-text-muted">Start from:</span>
              {chips.map((c) => (
                <button
                  key={c.kind}
                  type="button"
                  onClick={() => p.onStartFrom(c)}
                  className="inline-flex items-center gap-1.5 rounded-full border border-border bg-surface-1 px-3 py-1.5 text-caption text-text hover:border-text-faint focus-visible:outline-2 focus-visible:outline-accent"
                >
                  {c.kind === "duplicate" ? <Copy aria-hidden className="size-3.5" /> : <RectangleVertical aria-hidden className="size-3.5" />}
                  {c.label}
                </button>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}
