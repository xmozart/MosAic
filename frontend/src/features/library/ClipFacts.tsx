import { Plus, X } from "lucide-react";
import { useState } from "react";

import { DispositionChip } from "@/components/media/DispositionChip";
import { DispositionControl } from "@/components/media/DispositionControl";
import { IncludeToggle } from "@/components/media/IncludeToggle";
import { QualityRow } from "@/components/media/QualityRow";
import { StarRating } from "@/components/media/StarRating";

import { aiVersusYou, clock, factsLine, type ClipDetail, type DecisionChange } from "./model";

export function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="flex flex-col gap-2 border-t border-border pt-4">
      <h3 className="text-caption text-text-muted">{title}</h3>
      {children}
    </section>
  );
}

export interface ClipFactsProps {
  clip: ClipDetail;
  frameUrl: (sampleId: number) => string;
  onDecide: (change: DecisionChange) => void;
  onShowClip?: (id: number) => void;
  onMoment?: (start: { ticks: number; tb: string }) => void;
}

/** The clip's decisions and the AI's reasoning, shared by the S10 inspector and S11 so they
 * never differ: title line, disposition and stars, AI-vs-you, include, Why, Moments,
 * Quality, Similar, Tags, Note, Used in edits (COMPONENTS.md ClipInspector order). */
export function ClipFacts(p: ClipFactsProps) {
  const c = p.clip;
  const d = c.decision;
  const [tag, setTag] = useState("");
  const [note, setNote] = useState<string | null>(null);
  const addTag = () => {
    const t = tag.trim();
    if (t && !d.tags.includes(t)) p.onDecide({ add_tags: [t] });
    setTag("");
  };
  const facts = factsLine(c);
  return (
    <>
        <div className="flex flex-col gap-1">
          <div className="flex flex-wrap items-center gap-1.5">
            <h2 className="mono min-w-0 truncate text-subhead font-semibold text-text">{c.name ?? `Clip ${c.asset_id}`}</h2>
            {c.badges.map((b) => (
              <span key={b} className="rounded-full border border-border bg-surface-2 px-2 py-0.5 text-tag font-medium text-text-muted">
                {b}
              </span>
            ))}
          </div>
          <p className="text-caption font-normal text-text-muted">{facts}</p>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <DispositionControl value={d.disposition ?? undefined} onChange={(v) => p.onDecide({ disposition: d.disposition === v ? null : v })} />
          <StarRating value={d.stars ?? 0} onChange={(n) => p.onDecide({ stars: n || null })} />
        </div>
        <p className="flex items-center gap-2 text-caption font-normal text-text-muted">
          {c.status_shown && c.decided_by && <DispositionChip value={c.status_shown} by={c.decided_by} size="sm" />}
          {aiVersusYou(c)}
        </p>
        <IncludeToggle value={d.include ?? "none"} onChange={(v) => p.onDecide({ include: v === "none" ? null : v })} />
        {(c.why.description || c.why.reasons.length > 0) && (
          <Section title="Why">
            {c.why.description && <p className="text-small text-text">{c.why.description}</p>}
            {c.why.reasons.length > 0 && <p className="text-caption font-normal text-text-muted">{c.why.reasons.join(" · ")}</p>}
          </Section>
        )}
        {c.moments.some((m) => m.description) && (
          <Section title="Moments">
            <ul className="flex flex-col gap-1.5">
              {c.moments
                .filter((m) => m.description)
                .map((m) => (
                  <li key={m.segment_id} className="flex gap-3 text-small">
                    {p.onMoment ? (
                      <button
                        type="button"
                        onClick={() => p.onMoment!(m.usable_start)}
                        className="mono w-14 shrink-0 rounded-sm text-left text-timecode-sm text-accent hover:underline focus-visible:outline-2 focus-visible:outline-accent"
                      >
                        {clock(m.usable_start)}
                      </button>
                    ) : (
                      <span className="mono w-14 shrink-0 text-timecode-sm text-text-muted">{clock(m.usable_start)}</span>
                    )}
                    <span className="text-text">{m.description}</span>
                  </li>
                ))}
            </ul>
          </Section>
        )}
        <Section title="Quality">
          <QualityRow
            sharpness={c.quality.sharpness ?? "None"}
            steadiness={c.quality.steadiness ?? "None"}
            exposure={c.quality.exposure ?? "None"}
            audio={c.quality.audio ?? "None"}
          />
        </Section>
        {c.similar.length > 0 && (
          <Section title="Similar">
            <div className="flex gap-2 overflow-x-auto">
              {c.similar.map((s) => (
                <button
                  key={s.asset_id}
                  type="button"
                  aria-label={`Show similar clip ${s.asset_id}`}
                  onClick={() => p.onShowClip?.(s.asset_id)}
                  className="aspect-video w-24 shrink-0 overflow-hidden rounded-md bg-surface-3 focus-visible:outline-2 focus-visible:outline-accent"
                >
                  {s.sample_id && <img src={p.frameUrl(s.sample_id)} alt="" className="size-full object-cover" />}
                </button>
              ))}
            </div>
          </Section>
        )}
        <Section title="Tags">
          <ul aria-label="Tags" className="flex flex-wrap gap-1.5">
            {d.tags.map((t) => (
              <li key={t} className="inline-flex items-center gap-1 rounded-full border border-user px-2.5 py-0.5 text-caption text-user">
                {t}
                <button type="button" aria-label={`Remove ${t}`} onClick={() => p.onDecide({ remove_tags: [t] })} className="rounded-full p-0.5 focus-visible:outline-2 focus-visible:outline-accent">
                  <X aria-hidden className="size-3" />
                </button>
              </li>
            ))}
            <li className="inline-flex items-center gap-1">
              <Plus aria-hidden className="size-3 text-text-faint" />
              <input
                aria-label="Add a tag"
                placeholder="Add tag"
                maxLength={60}
                value={tag}
                onChange={(e) => setTag(e.target.value)}
                onKeyDown={(e) => {
                  e.stopPropagation(); // typing is not a grid key
                  if (e.key === "Enter") addTag();
                }}
                onBlur={addTag}
                className="h-7 w-28 rounded-full border border-border bg-surface-3 px-2.5 text-caption text-text placeholder:text-text-faint focus-visible:outline-2 focus-visible:outline-accent"
              />
            </li>
          </ul>
        </Section>
        <Section title="Note">
          <textarea
            aria-label="Note"
            maxLength={2000}
            value={note ?? d.note ?? ""}
            onChange={(e) => setNote(e.target.value)}
            onKeyDown={(e) => e.stopPropagation()}
            onBlur={() => {
              if (note !== null && note !== (d.note ?? "")) p.onDecide({ note: note.trim() || null });
              setNote(null);
            }}
            className="h-[60px] resize-y rounded-md border border-border bg-surface-3 p-2.5 text-small text-text focus-visible:outline-2 focus-visible:outline-accent"
          />
        </Section>
        {c.used_in.length > 0 && (
          <Section title="Used in edits">
            <ul className="flex flex-col gap-1">
              {c.used_in.map((e) => (
                <li key={e.edit_id} className="text-small text-text">
                  {e.name} · v{e.version}
                </li>
              ))}
            </ul>
          </Section>
        )}
    </>
  );
}
