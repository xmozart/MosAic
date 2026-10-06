import { Search } from "lucide-react";
import { forwardRef, useState, type KeyboardEvent } from "react";

import { ClipTile } from "@/components/media/ClipTile";
import { Banner } from "@/components/ui/Banner";
import { Segmented } from "@/components/ui/Segmented";
import type { CameraKind, DecidedBy, Disposition } from "@/lib/domain";
import { plural } from "@/lib/format";
import { formatClock, seconds, type SourceTime } from "@/lib/time";

export type SearchMode = "all" | "visual" | "speech";

/** One result of `GET /projects/{pid}/search` (API_MAP; ADR 0029, 0042). */
export interface SearchItem {
  segment_id: number;
  asset_id: number;
  start: SourceTime;
  end: SourceTime;
  sample_id: number | null;
  status: Disposition | null;
  decided_by: DecidedBy | null;
  ai_status: Disposition | null;
  score: number;
  matched: string[];
  name: string | null;
  kind: string;
  camera: { label: string; kind: CameraKind };
  stars: number | null;
  has_speech: boolean;
}

export interface SearchViewProps {
  query: string;
  mode: SearchMode;
  items: SearchItem[] | undefined; // undefined: searching (or idle with no query)
  error?: boolean;
  onRetry?: () => void;
  visual: "ok" | "unavailable" | "off" | undefined;
  suggestions: string[];
  frameUrl: (sampleId: number) => string;
  onSearch: (q: string) => void;
  onMode: (m: SearchMode) => void;
  onOpen: (item: SearchItem) => void;
}

const MODES = [
  { value: "all", label: "All" },
  { value: "visual", label: "Visual" },
  { value: "speech", label: "Speech" },
] as const;

function Suggestions({ items, onSearch }: { items: string[]; onSearch: (q: string) => void }) {
  if (!items.length) return null;
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      <span className="text-caption font-normal text-text-muted">Try:</span>
      {items.slice(0, 8).map((s) => (
        <button
          key={s}
          type="button"
          onClick={() => onSearch(s)}
          className="rounded-full border border-border bg-surface-1 px-2.5 py-1 text-caption text-text-muted hover:text-text focus-visible:outline-2 focus-visible:outline-accent"
        >
          {s}
        </button>
      ))}
    </div>
  );
}

/** S12 Search: natural-language results over visuals and speech; each tile says what
 * matched. Presentational. */
export const SearchView = forwardRef<HTMLInputElement, SearchViewProps>(function SearchView(p, ref) {
  const [text, setText] = useState(p.query);
  const onKey = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter" && text.trim()) p.onSearch(text.trim());
    if (e.key === "Escape") setText("");
  };
  const idle = !p.query;
  const searching = !idle && !p.error && p.items === undefined;
  const none = !idle && !p.error && p.items?.length === 0;
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex flex-col gap-3 border-b border-border px-6 py-4">
        <label className="relative">
          <Search aria-hidden className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-text-faint" />
          <input
            ref={ref}
            aria-label="Search footage"
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={onKey}
            placeholder="Search: “monkeys in trees”, “people laughing”"
            className="h-[38px] w-full rounded-md border border-border bg-surface-3 pr-3 pl-9 text-body text-text placeholder:text-text-faint focus-visible:outline-2 focus-visible:outline-accent"
          />
        </label>
      </div>
      <div className="flex flex-1 flex-col gap-4 overflow-y-auto px-6 py-5">
        <div className="flex flex-wrap items-center gap-4">
          <h1 className="text-heading text-text" aria-live="polite">
            {idle
              ? "Search this trip"
              : searching
                ? `Searching for “${p.query}”…`
                : p.error
                  ? `Search for “${p.query}”`
                  : `${plural(p.items!.length, "result")} for “${p.query}”`}
          </h1>
          {!idle && <Segmented label="Search in" value={p.mode} options={MODES} onChange={p.onMode} />}
          {!none && (
            <span className="ml-auto">
              <Suggestions items={p.suggestions} onSearch={(q) => (setText(q), p.onSearch(q))} />
            </span>
          )}
        </div>
        {p.visual === "unavailable" && !p.error && (
          <Banner kind="info">While analysis runs, results may improve once it finishes.</Banner>
        )}
        {p.error && (
          <Banner
            kind="danger"
            action={
              <button type="button" onClick={p.onRetry} className="text-small text-text underline-offset-2 hover:underline focus-visible:outline-2 focus-visible:outline-accent">
                Try again
              </button>
            }
          >
            Couldn't search right now.
          </Banner>
        )}
        {idle || p.error ? null : searching ? (
          <div className="grid grid-cols-4 gap-[18px]" role="status">
            <span className="sr-only">Searching</span>
            {Array.from({ length: 8 }, (_, i) => (
              <div key={i} className="aspect-video animate-pulse rounded-md bg-surface-2" />
            ))}
          </div>
        ) : none ? (
          <div className="flex flex-col items-center gap-3 py-16 text-center">
            <p className="text-subhead font-semibold text-text">No clips match “{p.query}”</p>
            <p className="text-body text-text-muted">Nothing like that in this trip. Try one of these instead:</p>
            <Suggestions items={p.suggestions} onSearch={(q) => (setText(q), p.onSearch(q))} />
          </div>
        ) : (
          <ul className="grid grid-cols-4 gap-[18px]" aria-label="Results">
            {p.items!.map((it) => (
              <li key={it.segment_id} className="flex min-w-0 flex-col gap-1">
                <ClipTile
                  asset={{
                    name: it.name ?? `Clip ${it.asset_id}`,
                    duration: formatClock(seconds({ ticks: it.end.ticks - it.start.ticks, tb: it.end.tb })),
                    camera: it.camera,
                    thumbnail: it.sample_id ? p.frameUrl(it.sample_id) : undefined,
                    livePhoto: it.kind === "live_photo",
                  }}
                  disposition={it.status ?? undefined}
                  decidedBy={it.decided_by ?? "ai"}
                  stars={it.stars ?? 0}
                  hasSpeech={it.has_speech}
                  onSelect={() => p.onOpen(it)}
                  onOpen={() => p.onOpen(it)}
                />
                <p className="truncate text-caption font-normal text-text-muted" title={it.matched.join(" · ")}>
                  <span className="text-text-faint">matched:</span> {it.matched.join(" · ")}
                </p>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
});
