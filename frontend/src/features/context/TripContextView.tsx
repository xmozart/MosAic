import { Loader2, Plus, Sparkles, X } from "lucide-react";
import { useState, type KeyboardEvent } from "react";

import { Banner } from "@/components/ui/Banner";
import { Button } from "@/components/ui/Button";
import { TextField } from "@/components/ui/TextField";
import { cn } from "@/lib/cn";
import { formatDay, tripDay } from "@/lib/format";

import type { Day, Highlights, TripContext } from "./model";

const SHOWN_DAYS = 7;
const input =
  "h-[34px] w-full min-w-0 rounded-[8px] border border-border bg-surface-3 px-2.5 text-small text-text placeholder:text-text-faint focus-visible:outline-2 focus-visible:outline-accent";

export type ContextTab = "paste" | "details";

export interface TripContextViewProps {
  value: TripContext;
  onChange: (v: TripContext) => void;
  /** Days that have footage, so the table has a row per trip day before any is typed. */
  footageDays: string[];
  highlights: Highlights;
  tab: ContextTab;
  onTab: (t: ContextTab) => void;
  paste: string;
  onPaste: (t: string) => void;
  parsing: boolean;
  parseError: string | null;
  onParse: () => void;
  saving: boolean;
  onSave: () => void;
  onSkip: () => void;
}

/** S7 Trip context: optional details that help story and titles. Saving re-runs
 * summaries only, never the analysis. Presentational (stories, tests). */
export function TripContextView(p: TripContextViewProps) {
  const v = p.value;
  const set = (patch: Partial<TripContext>) => p.onChange({ ...v, ...patch });
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex flex-1 flex-col gap-[18px] overflow-y-auto px-8 py-7">
        <div className="flex items-start gap-4">
          <div className="flex flex-col gap-1">
            <h1 className="text-title text-text">Trip details</h1>
            <p className="text-body text-text-muted">
              Optional. Helps with story, titles and chronology. You can add or change this anytime — it won't re-run analysis.
            </p>
          </div>
          <span className="ml-auto rounded-full border border-border bg-surface-2 px-2.5 py-0.5 text-caption text-text-muted">Optional</span>
        </div>
        <div
          role="tablist"
          aria-label="Trip details"
          className="flex gap-5 border-b border-border"
          onKeyDown={(e) => {
            if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
            e.preventDefault();
            const next = p.tab === "paste" ? "details" : "paste";
            p.onTab(next);
            document.getElementById(`tab-${next}`)?.focus();
          }}
        >
          {(
            [
              ["paste", "Quick paste"],
              ["details", "Details"],
            ] as const
          ).map(([id, label]) => (
            <button
              key={id}
              type="button"
              role="tab"
              id={`tab-${id}`}
              aria-selected={p.tab === id}
              aria-controls={p.tab === id ? `panel-${id}` : undefined}
              tabIndex={p.tab === id ? 0 : -1}
              onClick={() => p.onTab(id)}
              className={cn(
                "-mb-px border-b-2 py-2.5 text-body focus-visible:outline-2 focus-visible:outline-accent",
                p.tab === id ? "border-accent font-semibold text-text" : "border-transparent text-text-muted hover:text-text",
              )}
            >
              {label}
            </button>
          ))}
        </div>
        {p.tab === "paste" ? <PastePanel {...p} /> : <DetailsPanel {...p} set={set} />}
      </div>
      <footer className="sticky bottom-0 flex h-[68px] shrink-0 items-center gap-2.5 border-t border-border bg-surface-1 px-8">
        <Button variant="ghost" onClick={p.onSkip}>
          Skip for now
        </Button>
        <Button variant="primary" className="ml-auto" disabled={p.saving} onClick={p.onSave}>
          Save
        </Button>
      </footer>
    </div>
  );
}

function PastePanel(p: TripContextViewProps) {
  const onKey = (e: KeyboardEvent) => {
    if (e.key === "Enter" && (e.metaKey || e.ctrlKey) && p.paste.trim() && !p.parsing) {
      e.preventDefault();
      p.onParse();
    }
  };
  return (
    <div role="tabpanel" id="panel-paste" aria-labelledby="tab-paste" className="flex max-w-[760px] flex-col gap-3">
      <p className="text-small text-text-muted">
        Paste an itinerary, a message or a few notes. MosAic organizes them into days, people and must-haves for you to check.
      </p>
      <textarea
        aria-label="Trip notes"
        value={p.paste}
        onChange={(e) => p.onPaste(e.target.value)}
        onKeyDown={onKey}
        maxLength={20000}
        placeholder={"Day 1 San José → La Fortuna, long drive\nDay 2 La Fortuna waterfall hike…"}
        className="h-56 resize-y rounded-md border border-border bg-surface-3 p-3 text-small text-text placeholder:text-text-faint focus-visible:outline-2 focus-visible:outline-accent"
      />
      {p.parseError && (
        <p role="alert" className="text-small text-reject">
          {p.parseError}
        </p>
      )}
      <div className="flex items-center gap-3">
        <Button variant="primary" disabled={!p.paste.trim() || p.parsing} onClick={p.onParse}>
          {p.parsing ? <Loader2 className="animate-spin" /> : <Sparkles />}
          {p.parsing ? "Parsing…" : "Parse"}
        </Button>
        <span className="text-caption font-normal text-text-faint">⌘Enter</span>
      </div>
    </div>
  );
}

function rowsFor(v: TripContext, footage: string[]): Day[] {
  const by = new Map(v.days.map((d) => [d.date, d]));
  for (const date of footage) if (!by.has(date)) by.set(date, { date, place: "", notes: "" });
  return [...by.values()].sort((a, b) => a.date.localeCompare(b.date));
}

function DetailsPanel(p: TripContextViewProps & { set: (patch: Partial<TripContext>) => void }) {
  const v = p.value;
  const [allDays, setAllDays] = useState(false);
  const rows = rowsFor(v, p.footageDays);
  const first = rows[0]?.date;
  const shown = allDays ? rows : rows.slice(0, SHOWN_DAYS);
  const editDay = (date: string, patch: Partial<Day>) => {
    const has = v.days.some((d) => d.date === date);
    const days = has
      ? v.days.map((d) => (d.date === date ? { ...d, ...patch } : d))
      : [...v.days, { date, place: "", notes: "", ...patch }].sort((a, b) => a.date.localeCompare(b.date));
    p.set({ days });
  };
  return (
    <div role="tabpanel" id="panel-details" aria-labelledby="tab-details" className="grid grid-cols-[1.6fr_1fr] gap-8">
      <div className="flex flex-col gap-3.5">
        <div className={cn("-m-1.5 rounded-md p-1.5", p.highlights.has("trip_name") && "bg-accent-soft")}>
          <TextField label="Trip name" value={v.trip_name} maxLength={120} onChange={(e) => p.set({ trip_name: e.target.value })} />
        </div>
        {p.highlights.size > 0 && (
          <Banner kind="info">We organized your pasted itinerary. New values are highlighted — check them.</Banner>
        )}
        <div className="flex flex-col gap-1.5">
          <h2 className="text-caption text-text-muted">Days</h2>
          {rows.length === 0 ? (
            <p className="text-small text-text-muted">Days appear here once the scan finds capture dates.</p>
          ) : (
            <ol className="flex flex-col gap-0.5">
              {shown.map((d) => {
                const n = first ? tripDay(first, d.date) : 1;
                return (
                  <li
                    key={d.date}
                    data-parsed={p.highlights.has(`day:${d.date}`) || undefined}
                    className={cn(
                      "grid grid-cols-[60px_90px_1.3fr_1fr] items-center gap-3 rounded-[8px] px-2.5 py-2",
                      p.highlights.has(`day:${d.date}`) && "bg-accent-soft",
                    )}
                  >
                    <span className="text-caption text-text">Day {n}</span>
                    <span className="mono text-timecode-sm text-text-muted">{formatDay(d.date)}</span>
                    <input
                      aria-label={`Place for day ${n}`}
                      className={input}
                      maxLength={200}
                      value={d.place}
                      onChange={(e) => editDay(d.date, { place: e.target.value })}
                    />
                    <input
                      aria-label={`Notes for day ${n}`}
                      className={input}
                      maxLength={500}
                      value={d.notes}
                      onChange={(e) => editDay(d.date, { notes: e.target.value })}
                    />
                  </li>
                );
              })}
            </ol>
          )}
          {rows.length > SHOWN_DAYS && (
            <button type="button" onClick={() => setAllDays(!allDays)} className="self-start rounded-sm text-caption font-normal text-text-muted hover:text-text focus-visible:outline-2 focus-visible:outline-accent">
              {allDays ? "Show fewer days" : `+ ${rows.length - SHOWN_DAYS} more days`}
            </button>
          )}
        </div>
      </div>
      <div className="flex flex-col gap-[18px]">
        <People {...p} />
        <Chips
          title="Must include"
          tone="user"
          items={v.must_include}
          highlighted={(t) => p.highlights.has(`must_include:${t}`)}
          onChange={(must_include) => p.set({ must_include })}
        />
        <Chips
          title="Avoid"
          tone="reject"
          items={v.avoid}
          highlighted={(t) => p.highlights.has(`avoid:${t}`)}
          onChange={(avoid) => p.set({ avoid })}
        />
        <div className="flex flex-col gap-2">
          <label htmlFor="trip-notes" className="text-caption text-text-muted">
            Notes
          </label>
          <textarea
            id="trip-notes"
            value={v.free_notes}
            maxLength={4000}
            onChange={(e) => p.set({ free_notes: e.target.value })}
            className={cn(
              "h-[70px] resize-y rounded-md border border-border bg-surface-3 p-2.5 text-small text-text focus-visible:outline-2 focus-visible:outline-accent",
              p.highlights.has("free_notes") && "bg-accent-soft",
            )}
          />
        </div>
      </div>
    </div>
  );
}

function People(p: TripContextViewProps & { set: (patch: Partial<TripContext>) => void }) {
  const [adding, setAdding] = useState(false);
  const [label, setLabel] = useState("");
  const [description, setDescription] = useState("");
  const add = () => {
    if (!label.trim()) return;
    p.set({ people: [...p.value.people, { label: label.trim(), description: description.trim() }] });
    setLabel("");
    setDescription("");
    setAdding(false);
  };
  return (
    <div className="flex flex-col gap-2">
      <h2 className="text-caption text-text-muted">People</h2>
      {p.value.people.map((person, i) => (
        <div
          key={`${person.label}-${i}`}
          className={cn("flex items-center gap-2.5 rounded-md bg-surface-2 px-2.5 py-2", p.highlights.has(`person:${person.label}`) && "bg-accent-soft")}
        >
          <span aria-hidden className="flex size-7 shrink-0 items-center justify-center rounded-full bg-surface-3 text-caption font-semibold text-text">
            {person.label[0]?.toUpperCase()}
          </span>
          <div className="flex min-w-0 flex-1 flex-col">
            <span className="text-small font-medium text-text">{person.label}</span>
            {person.description && <span className="text-caption font-normal text-text-muted">{person.description}</span>}
          </div>
          <button
            type="button"
            aria-label={`Remove ${person.label}`}
            onClick={() => p.set({ people: p.value.people.filter((_, j) => j !== i) })}
            className="rounded-sm p-1 text-text-faint hover:text-text focus-visible:outline-2 focus-visible:outline-accent"
          >
            <X aria-hidden className="size-3.5" />
          </button>
        </div>
      ))}
      {adding ? (
        <div className="flex flex-col gap-2 rounded-md border border-border p-2.5">
          <input aria-label="Name" placeholder="Name" maxLength={60} autoFocus className={input} value={label} onChange={(e) => setLabel(e.target.value)} onKeyDown={(e) => e.key === "Enter" && add()} />
          <input
            aria-label="How to recognise them"
            placeholder="How to recognise them, e.g. blue cap"
            maxLength={300}
            className={input}
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && add()}
          />
          <div className="flex justify-end gap-2">
            <Button size="sm" variant="ghost" onClick={() => setAdding(false)}>
              Cancel
            </Button>
            <Button size="sm" disabled={!label.trim()} onClick={add}>
              Add
            </Button>
          </div>
        </div>
      ) : (
        <AddChip label="Add person" onClick={() => setAdding(true)} />
      )}
    </div>
  );
}

function AddChip({ label, onClick }: { label: string; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="inline-flex items-center gap-1.5 self-start rounded-full border border-border bg-surface-2 px-2.5 py-0.5 text-caption text-text-muted hover:text-text focus-visible:outline-2 focus-visible:outline-accent"
    >
      <Plus aria-hidden className="size-3" />
      {label}
    </button>
  );
}

/** Must include (the user's own decisions: `user` blue) and Avoid (`reject`) chips. */
function Chips(p: { title: string; tone: "user" | "reject"; items: string[]; highlighted: (t: string) => boolean; onChange: (items: string[]) => void }) {
  const [adding, setAdding] = useState(false);
  const [text, setText] = useState("");
  const add = () => {
    const t = text.trim();
    if (t && !p.items.includes(t)) p.onChange([...p.items, t]);
    setText("");
    setAdding(false);
  };
  return (
    <div className="flex flex-col gap-2">
      <h2 className="text-caption text-text-muted">{p.title}</h2>
      <ul aria-label={p.title} className="flex flex-wrap gap-1.5">
        {p.items.map((t) => (
          <li
            key={t}
            className={cn(
              "inline-flex items-center gap-1 rounded-full border px-2.5 py-0.5 text-caption",
              p.tone === "user" ? "border-user text-user" : "border-reject text-reject",
              p.highlighted(t) ? "bg-accent-soft" : "bg-surface-2",
            )}
          >
            {t}
            <button
              type="button"
              aria-label={`Remove ${t}`}
              onClick={() => p.onChange(p.items.filter((x) => x !== t))}
              className="rounded-full p-0.5 opacity-70 hover:opacity-100 focus-visible:outline-2 focus-visible:outline-accent"
            >
              <X aria-hidden className="size-3" />
            </button>
          </li>
        ))}
        <li>
          {adding ? (
            <input
              aria-label={`Add to ${p.title}`}
              autoFocus
              maxLength={300}
              className={cn(input, "h-7 w-56 rounded-full")}
              value={text}
              onChange={(e) => setText(e.target.value)}
              onBlur={add}
              onKeyDown={(e) => {
                if (e.key === "Enter") add();
                if (e.key === "Escape") setAdding(false);
              }}
            />
          ) : (
            <AddChip label="Add" onClick={() => setAdding(true)} />
          )}
        </li>
      </ul>
    </div>
  );
}
