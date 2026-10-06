import { cn } from "@/lib/cn";
import { seconds, tenths, type SourceTime } from "@/lib/time";

export interface TranscriptLine {
  id: number;
  start: SourceTime;
  end: SourceTime;
  text: string;
  words: { start: SourceTime; end: SourceTime; word: string }[];
}

function languageName(code: string): string {
  try {
    return new Intl.DisplayNames(["en"], { type: "language" }).of(code) ?? code;
  } catch {
    return code;
  }
}

/** COMPONENTS.md Transcript: lines with a timestamp each; every word seeks to itself.
 * No speaker labels (ADR 0043). Words stay out of the tab order: each line's timestamp is
 * its tab stop. */
export function Transcript({ lines, now, language, onSeek }: { lines: TranscriptLine[]; now: number; language: string | null; onSeek: (t: SourceTime) => void }) {
  return (
    <section aria-label="Transcript" className="flex flex-col gap-3 rounded-lg border border-border bg-surface-1 p-4">
      <header className="flex items-center gap-2">
        <h2 className="text-subhead font-semibold text-text">Transcript</h2>
        {language && <span className="rounded-full border border-border px-2 py-0.5 text-micro font-medium text-text-muted">{languageName(language)}</span>}
        <span className="ml-auto text-caption font-normal text-text-faint">Click a word to jump there</span>
      </header>
      <ol className="flex flex-col gap-2">
        {lines.map((l) => (
          <li key={l.id} className="flex gap-3">
            <button
              type="button"
              aria-label={`Jump to ${tenths(l.start)}`}
              onClick={() => onSeek(l.start)}
              className="mono w-14 shrink-0 rounded-sm text-left text-timecode-sm text-text-muted hover:text-text focus-visible:outline-2 focus-visible:outline-accent"
            >
              {tenths(l.start)}
            </button>
            <p className="text-small leading-6 text-text" data-testid="transcript-line">
              {l.words.length
                ? l.words.map((w, i) => {
                    const on = now >= seconds(w.start) && now < seconds(w.end);
                    return (
                      <span key={i}>
                        {i > 0 && " "}
                        <button
                          type="button"
                          tabIndex={-1}
                          aria-current={on || undefined}
                          onClick={() => onSeek(w.start)}
                          className={cn("rounded-[3px] px-px hover:bg-surface-3", on && "bg-accent-soft text-text underline decoration-accent underline-offset-4")}
                        >
                          {w.word}
                        </button>
                      </span>
                    );
                  })
                : l.text}
            </p>
          </li>
        ))}
      </ol>
    </section>
  );
}
