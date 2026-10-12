import { Dialog } from "radix-ui";
import { Check, X } from "lucide-react";
import { useEffect, useId, useRef, useState, type KeyboardEvent } from "react";

import { Button } from "@/components/ui/Button";
import { cn } from "@/lib/cn";

/** `GET /projects/{pid}/labeling-questions` items (ADR 0085). */
export interface LabelingQuestion {
  question_id: string;
  kind: "place" | "same_person" | "event";
  day: number | null;
  text: string;
  asset_ids: number[];
  sample_ids: (number | null)[];
  status: string;
  people?: { label: string; description: string }[];
}

export type Choice = "yes" | "no" | "not_sure";
export interface LabelAnswer {
  skip?: boolean;
  choice?: Choice;
  name?: string;
  text?: string;
}

export interface HelpLabelDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Undefined while they load. */
  questions: LabelingQuestion[] | undefined;
  frame: (sampleId: number) => string;
  /** Records an answer; rejects with the reason when it isn't taken. */
  onAnswer: (questionId: string, answer: LabelAnswer) => Promise<void>;
  /** Questions already answered or skipped, with the answers given (stories: the
   * summary). The dialog starts at the first one not in it. */
  given?: Record<string, { outcome: "answered" | "skipped"; answer?: LabelAnswer }>;
}

const CHOICES: { value: Choice; label: string }[] = [
  { value: "yes", label: "Yes, same person" },
  { value: "no", label: "No" },
  { value: "not_sure", label: "Not sure" },
];
const NOTE: Record<LabelingQuestion["kind"], string> = {
  place: "Your answer goes into the trip details, so titles and summaries can name the place.",
  same_person: "Answering helps MosAic keep people consistent across days. Faces are not stored or recognized — this only links clips.",
  event: "A few words are enough. They go into that day's notes in the trip details.",
};

type Outcome = "answered" | "skipped";

/** S24 Help me label: up to five skippable questions from the analysis; answers become
 * trip details or links between clips, never face data (ADR 0085, 0092). */
export function HelpLabelDialog(p: HelpLabelDialogProps) {
  // The keys are the dialog's: focus may sit on the dialog itself after a question changes.
  const keys = useRef<((e: KeyboardEvent) => void) | null>(null);
  return (
    <Dialog.Root open={p.open} onOpenChange={p.onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-scrim" />
        <Dialog.Content
          aria-describedby={undefined}
          // The question gets the focus (its field, or its first answer), not Close.
          onOpenAutoFocus={(e) => {
            const first = (e.currentTarget as HTMLElement).querySelector<HTMLElement>("input, textarea, [role=radio]");
            if (first) {
              e.preventDefault();
              first.focus();
            }
          }}
          onKeyDown={(e) => keys.current?.(e)}
          className="fixed top-1/2 left-1/2 z-50 flex max-h-[92vh] w-[640px] -translate-x-1/2 -translate-y-1/2 flex-col gap-4 overflow-y-auto rounded-lg border border-border bg-surface-1 p-6 shadow-[0_24px_64px_rgba(0,0,0,0.5)]"
        >
          {p.questions ? (
            <Questions
              {...p}
              questions={p.questions}
              onKeys={(fn) => {
                keys.current = fn;
              }}
              key={p.questions.map((q) => q.question_id).join()}
            />
          ) : (
            <>
              <Header />
              <div aria-label="Loading the questions" className="h-64 animate-pulse rounded-md bg-surface-2" />
            </>
          )}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

function Header({ at, of }: { at?: number; of?: number }) {
  return (
    <div className="flex items-center gap-2.5">
      <Dialog.Title className="text-heading font-semibold tracking-[-0.01em] text-text">Help me label</Dialog.Title>
      {at !== undefined && of !== undefined && (
        <span className="inline-flex items-center rounded-full border border-border bg-surface-2 px-[9px] py-[3px] text-micro font-medium text-text-muted">
          Question {at} of {of}
        </span>
      )}
      <Dialog.Close asChild>
        <Button variant="secondary" size="icon" aria-label="Close" className="ml-auto size-[34px]">
          <X />
        </Button>
      </Dialog.Close>
    </div>
  );
}

function Questions(p: HelpLabelDialogProps & { questions: LabelingQuestion[]; onKeys: (fn: (e: KeyboardEvent) => void) => void }) {
  const qs = p.questions;
  const given = p.given ?? {};
  const [i, setI] = useState(() => {
    const first = qs.findIndex((q) => !given[q.question_id]);
    return first === -1 ? qs.length : first;
  });
  const [outcomes, setOutcomes] = useState<Record<string, Outcome>>(() => Object.fromEntries(Object.entries(given).map(([k, v]) => [k, v.outcome])));
  const [drafts, setDrafts] = useState<Record<string, LabelAnswer>>(() => Object.fromEntries(Object.entries(given).map(([k, v]) => [k, v.answer ?? {}])));
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const field = useRef<HTMLInputElement | HTMLTextAreaElement>(null);
  const box = useRef<HTMLDivElement>(null);
  const fieldId = useId();

  const done = i >= qs.length;
  const q = qs[i];
  const draft = (q && drafts[q.question_id]) ?? {};
  const outcome = q ? outcomes[q.question_id] : undefined;
  const set = (patch: LabelAnswer) => q && setDrafts((d) => ({ ...d, [q.question_id]: { ...d[q.question_id], ...patch } }));

  // Each question takes the focus: its field, its chosen (else first) answer, or Next
  // when it was answered already; the summary's Close at the end.
  useEffect(() => {
    const el = box.current;
    if (!el) return;
    const target =
      el.querySelector<HTMLElement>("[role=radio][aria-checked=true]") ??
      el.querySelector<HTMLElement>("[role=radio]") ??
      el.querySelector<HTMLElement>("input:not([readonly]), textarea") ??
      el.querySelector<HTMLElement>("[data-next]") ??
      el.querySelector<HTMLElement>("[data-close]");
    target?.focus();
  }, [i]);

  if (done || !q)
    return (
      <div ref={box}>
        <Summary questions={qs} outcomes={outcomes} linked={qs.some((x) => x.kind === "same_person" && outcomes[x.question_id] === "answered" && drafts[x.question_id]?.choice === "yes")} />
      </div>
    );

  const name = (draft.name ?? "").trim();
  const text = (draft.text ?? "").trim();
  const ready = q.kind === "same_person" ? draft.choice !== undefined && (draft.choice !== "yes" || name !== "") : text !== "";
  const match = q.kind === "same_person" && name ? q.people?.find((x) => x.label.toLowerCase() === name.toLowerCase()) : undefined;

  const send = async (answer: LabelAnswer, as: Outcome) => {
    setSending(true);
    setError(null);
    try {
      await p.onAnswer(q.question_id, answer);
      setOutcomes((o) => ({ ...o, [q.question_id]: as }));
      setI((n) => n + 1);
    } catch (e) {
      const message = e instanceof Error ? e.message : "That answer couldn't be saved.";
      if (/answered already/i.test(message)) {
        // Answered elsewhere (another window): nothing to do here, move on.
        setOutcomes((o) => ({ ...o, [q.question_id]: "answered" }));
        setI((n) => n + 1);
      } else setError(message);
    } finally {
      setSending(false);
    }
  };
  const next = () => {
    if (outcome) {
      setError(null);
      return setI((n) => n + 1); // already answered: just move on
    }
    if (!ready || sending) return;
    void send(q.kind === "same_person" ? { choice: draft.choice, ...(name ? { name } : {}) } : { text }, "answered");
  };
  const onKey = (e: KeyboardEvent) => {
    if (outcome || e.metaKey || e.ctrlKey || e.altKey) return;
    const inField = e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement;
    if (q.kind === "same_person" && !inField && ["1", "2", "3"].includes(e.key)) {
      e.preventDefault();
      set({ choice: CHOICES[Number(e.key) - 1]!.value });
    } else if (e.key === "Enter" && !e.shiftKey && !(e.target instanceof HTMLButtonElement)) {
      e.preventDefault();
      next();
    }
  };

  p.onKeys(onKey); // only sets the dialog's key ref: the handler of the question shown
  return (
    <div ref={box} className="flex flex-col gap-4">
      <Header at={i + 1} of={qs.length} />
      <div aria-hidden className="h-1 shrink-0 overflow-hidden rounded-full bg-surface-3">
        <div className="h-full rounded-full bg-accent" style={{ width: `${((i + 1) / qs.length) * 100}%` }} />
      </div>
      <h2 className="text-heading font-semibold tracking-[-0.01em] text-text">{q.text}</h2>
      <p className="text-small text-text-muted">{NOTE[q.kind]}</p>
      <div className="flex gap-2.5">
        {q.sample_ids.map((sid, k) => (
          <div key={k} className="aspect-video w-[180px] shrink-0 overflow-hidden rounded-md bg-surface-3">
            {sid != null && <img src={p.frame(sid)} alt="" className="size-full object-cover" />}
          </div>
        ))}
      </div>
      {outcome ? (
        <p className="flex items-center gap-1.5 text-small text-use">
          <Check aria-hidden className="size-4" /> {outcome === "skipped" ? "Skipped." : answeredText(q, drafts[q.question_id])}
        </p>
      ) : q.kind === "same_person" ? (
        <>
          <div role="radiogroup" aria-label="Same person?" className="flex gap-2">
            {CHOICES.map((c, k) => (
              <Button
                key={c.value}
                role="radio"
                aria-checked={draft.choice === c.value}
                variant={c.value === "not_sure" && draft.choice !== c.value ? "ghost" : "secondary"}
                className={cn(draft.choice === c.value && "border-accent bg-accent-soft")}
                onClick={() => set({ choice: c.value })}
                title={`${k + 1}`}
              >
                {c.label}
              </Button>
            ))}
          </div>
          <div className="flex flex-col gap-1.5">
            <label htmlFor={fieldId} className="text-caption text-text-muted">
              Who is it? {draft.choice === "yes" ? "(needed to link the clips)" : "(optional)"}
            </label>
            <input
              id={fieldId}
              ref={field as React.RefObject<HTMLInputElement>}
              list={`${fieldId}-people`}
              value={draft.name ?? ""}
              maxLength={60}
              onChange={(e) => set({ name: e.target.value })}
              className="h-10 rounded-md border border-border bg-surface-3 px-3 text-body text-text focus-visible:outline-2 focus-visible:outline-accent"
            />
            <datalist id={`${fieldId}-people`}>
              {q.people?.map((x) => <option key={x.label} value={x.label} />)}
            </datalist>
            {match && (
              <span className="text-caption font-normal text-text-faint">
                Matches your trip details: “{match.label}
                {match.description ? ` — ${match.description}` : ""}”
              </span>
            )}
          </div>
        </>
      ) : (
        <div className="flex flex-col gap-1.5">
          <label htmlFor={fieldId} className="text-caption text-text-muted">
            {q.kind === "place" ? "Place" : "What happened?"}
          </label>
          {q.kind === "place" ? (
            <input
              id={fieldId}
              ref={field as React.RefObject<HTMLInputElement>}
              value={draft.text ?? ""}
              maxLength={120}
              placeholder="La Fortuna, Arenal"
              onChange={(e) => set({ text: e.target.value })}
              className="h-10 rounded-md border border-border bg-surface-3 px-3 text-body text-text placeholder:text-text-faint focus-visible:outline-2 focus-visible:outline-accent"
            />
          ) : (
            <textarea
              id={fieldId}
              ref={field as React.RefObject<HTMLTextAreaElement>}
              value={draft.text ?? ""}
              maxLength={500}
              rows={3}
              onChange={(e) => set({ text: e.target.value })}
              className="rounded-md border border-border bg-surface-3 px-3 py-2 text-body text-text focus-visible:outline-2 focus-visible:outline-accent"
            />
          )}
        </div>
      )}
      {error && (
        <p role="alert" className="text-small text-reject">
          {error}
        </p>
      )}
      <div className="flex items-center gap-2">
        {!outcome && (
          <Button variant="ghost" disabled={sending} onClick={() => void send({ skip: true }, "skipped")}>
            Skip
          </Button>
        )}
        <span className="flex-1" />
        <Button variant="ghost" disabled={i === 0 || sending} onClick={() => {
            setError(null);
            setI((n) => n - 1);
          }}>
          Back
        </Button>
        <Button data-next variant="primary" disabled={(!outcome && !ready) || sending} onClick={next}>
          {i === qs.length - 1 ? "Done" : "Next"}
        </Button>
      </div>
    </div>
  );
}

function answeredText(q: LabelingQuestion, a: LabelAnswer | undefined): string {
  if (q.kind !== "same_person") return "Answered — saved to your trip details.";
  return a?.choice === "yes" ? `Answered — these clips are linked to ${a.name ?? "that person"}.` : "Answered — nothing is linked.";
}

function Summary({ questions, outcomes, linked }: { questions: LabelingQuestion[]; outcomes: Record<string, Outcome>; linked: boolean }) {
  const answered = Object.values(outcomes).filter((o) => o === "answered").length;
  const skipped = Object.values(outcomes).filter((o) => o === "skipped").length;
  return (
    <div className="flex flex-col gap-4">
      <Header />
      {questions.length === 0 ? (
        <p className="text-body text-text">Nothing to ask right now. Questions come once the analysis knows enough about your trip.</p>
      ) : (
        <>
          <h2 className="text-heading font-semibold tracking-[-0.01em] text-text">Thanks — that helps.</h2>
          <p className="text-body text-text-muted">
            {answered} answered{skipped ? `, ${skipped} skipped` : ""}. Places and notes are in your trip details{linked ? ", and the clips you confirmed are linked to the person you named" : ""}.
          </p>
        </>
      )}
      <div className="flex justify-end">
        <Dialog.Close asChild>
          <Button data-close variant="primary">
            Close
          </Button>
        </Dialog.Close>
      </div>
    </div>
  );
}
