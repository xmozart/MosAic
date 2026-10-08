import { ChevronDown, ChevronUp } from "lucide-react";
import { useEffect, useState } from "react";

import { AspectPicker, ChoiceChip, DurationChips, EditSummaryPanel, StoryPresetCard, WizardStepNav, type AspectOption } from "@/components/edit/Wizard";
import { radioArrows } from "@/components/edit/radioArrows";
import { Banner } from "@/components/ui/Banner";
import { Button } from "@/components/ui/Button";
import { Segmented } from "@/components/ui/Segmented";
import { SwitchRow } from "@/components/ui/Switch";
import { TextField } from "@/components/ui/TextField";
import { formatClock } from "@/lib/time";

import {
  ASPECTS,
  CHRONOLOGY,
  DEFAULT_TOLERANCE,
  DURATIONS,
  FRAME_RATES,
  IDEAS,
  MAX_INSTRUCTIONS,
  MAX_SECONDS,
  MIN_SECONDS,
  RESOLUTIONS,
  STEPS,
  estimateText,
  frameRateLabel,
  lengthLabel,
  resolutionLabel,
  summaryLines,
  toleranceSeconds,
  type Aspect,
  type EditEstimate,
  type EditRequest,
  type Preset,
  type Resolution,
} from "./model";

const OPEN = STEPS.filter((s) => !s.later).map((s) => s.id);
const TITLES: Record<number, string> = {
  1: "How long, and where will it play?",
  2: "What kind of story?",
  6: "Anything else for the editor?",
};
const ASPECT_OPTIONS: AspectOption<Aspect | "native">[] = [...ASPECTS, { value: "native", label: "Native", w: 56, h: 36, disabled: true }];

export interface WizardViewProps {
  step: number;
  onStep: (step: number) => void;
  request: EditRequest;
  onChange: (patch: Partial<EditRequest>) => void;
  title: string;
  presets: Preset[] | undefined;
  /** Frame URLs per preset; missing while loading. */
  collages: Record<string, string[] | undefined>;
  estimate: EditEstimate | undefined;
  estimateError?: boolean;
  /** The request changed since the shown estimate: it is dimmed until the new one lands. */
  estimatePending?: boolean;
  creating: boolean;
  onCreate: () => void;
  /** Preliminary banner: go back to the analysis instead. */
  onWait: () => void;
}

/** S14 Create edit wizard (M2 basic: steps 1, 2, 6). Presentational. */
export function WizardView(p: WizardViewProps) {
  const r = p.request;
  const [customPicked, setCustomLength] = useState(false);
  // A length that is not a chip (a prefilled 75 s) is custom without a click.
  const customLength = customPicked || !(DURATIONS as readonly number[]).includes(r.duration_s);
  const [moreFormat, setMoreFormat] = useState(false);
  const featured = p.presets?.filter((x) => x.featured) ?? [];
  const others = p.presets?.filter((x) => !x.featured) ?? [];
  const [customStory, setCustomStory] = useState(false);
  const storyIsOther = others.some((x) => x.id === r.story);
  const showOthers = customStory || storyIsOther;

  const go = (delta: 1 | -1) => {
    const i = OPEN.indexOf(p.step);
    const next = OPEN[i + delta];
    if (next !== undefined) p.onStep(next);
  };
  const est = p.estimate;
  const noFootage = est !== undefined && est.candidates === 0;
  const { onCreate, creating } = p;
  useEffect(() => {
    const on = (e: KeyboardEvent) => {
      if (!(e.metaKey || e.ctrlKey)) return;
      if (e.key === "Enter" && !creating && !noFootage) {
        e.preventDefault();
        onCreate();
      } else if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        e.preventDefault();
        go(e.key === "ArrowDown" ? 1 : -1);
      }
    };
    window.addEventListener("keydown", on);
    return () => window.removeEventListener("keydown", on);
  });

  const warnings = (
    <>
      {noFootage && (
        <Banner kind="warning">Nothing to edit yet: no analyzed clips can be used. Analyze the folder first, or bring back rejected clips.</Banner>
      )}
      {est && !noFootage && !est.enough_footage && (
        <Banner kind="warning">
          Your usable footage adds up to about {formatClock(est.usable_seconds)} — shorter than {formatClock(r.duration_s)}. The edit may come out shorter.
        </Banner>
      )}
    </>
  );
  const nextLabel = (() => {
    const i = OPEN.indexOf(p.step);
    const next = OPEN[i + 1];
    return next === undefined ? null : `Next: ${STEPS.find((s) => s.id === next)!.label}`;
  })();

  return (
    <div className="flex min-h-0 flex-1">
      <WizardStepNav steps={STEPS} current={p.step} done={new Set(OPEN.filter((s) => s < p.step))} onStep={p.onStep} />
      <div className="flex min-w-0 flex-1 flex-col gap-[18px] overflow-y-auto px-9 py-7">
        {est?.preliminary && (
          <Banner
            kind="info"
            action={
              <span className="flex gap-2">
                <Button size="sm" onClick={p.onCreate} disabled={p.creating || noFootage}>
                  Create now (preliminary)
                </Button>
                <Button size="sm" variant="ghost" onClick={p.onWait}>
                  Wait
                </Button>
              </span>
            }
          >
            Analysis is {est.analysis_pct ?? 0}% done. You can create a preliminary edit now or wait for better results.
          </Banner>
        )}
        <div className="flex flex-col gap-1">
          <span className="text-caption font-semibold text-text-faint">Step {p.step} of 6</span>
          <h1 className="text-title tracking-[-0.01em] text-text">{TITLES[p.step]}</h1>
        </div>

        {p.step === 1 && (
          <section aria-label="Length and format" className="flex flex-col gap-5">
            <DurationChips
              options={DURATIONS}
              value={r.duration_s}
              custom={customLength}
              format={lengthLabel}
              onChange={(s) => {
                setCustomLength(false);
                p.onChange({ duration_s: s });
              }}
              onCustom={() => setCustomLength(true)}
            />
            {customLength && (
              <TextField
                className="w-56"
                type="number"
                label="Length in seconds"
                min={MIN_SECONDS}
                max={MAX_SECONDS}
                value={r.duration_s}
                hint={lengthLabel(r.duration_s)}
                onChange={(e) => {
                  const v = Number(e.target.value);
                  if (Number.isFinite(v) && v >= MIN_SECONDS && v <= MAX_SECONDS) p.onChange({ duration_s: Math.round(v) });
                }}
              />
            )}
            <div className="max-w-[420px]">
              <SwitchRow
                label="Strict length"
                description={`Otherwise ±${toleranceSeconds({ duration_s: r.duration_s, tolerance_pct: DEFAULT_TOLERANCE })} s`}
                checked={r.tolerance_pct === 0}
                onChange={(on) => p.onChange({ tolerance_pct: on ? 0 : DEFAULT_TOLERANCE })}
              />
            </div>
            <AspectPicker options={ASPECT_OPTIONS} value={r.aspect} onChange={(a) => a !== "native" && p.onChange({ aspect: a })} />
            <div className="flex flex-col gap-3">
              <button
                type="button"
                aria-expanded={moreFormat}
                onClick={() => setMoreFormat((m) => !m)}
                className="inline-flex items-center gap-1.5 self-start rounded-full border border-border bg-surface-2 px-[9px] py-[3px] text-caption text-text-muted hover:text-text focus-visible:outline-2 focus-visible:outline-accent"
              >
                {moreFormat ? <ChevronUp aria-hidden className="size-3.5" /> : <ChevronDown aria-hidden className="size-3.5" />}
                More options: resolution {resolutionLabel(r.resolution)} · {r.fps ? frameRateLabel(r.fps) : "native frame rate"}
              </button>
              {moreFormat && (
                <div className="flex flex-wrap items-end gap-6 rounded-lg border border-border bg-surface-1 p-[18px]">
                  <div className="flex flex-col gap-1.5">
                    <span className="text-caption text-text-muted">Resolution of the final render</span>
                    <Segmented<Resolution> label="Resolution" value={r.resolution} options={RESOLUTIONS} onChange={(v) => p.onChange({ resolution: v })} />
                  </div>
                  <label className="flex flex-col gap-1.5">
                    <span className="text-caption text-text-muted">Frame rate</span>
                    <select
                      value={r.fps ?? ""}
                      onChange={(e) => p.onChange({ fps: e.target.value || null })}
                      className="h-10 rounded-md border border-border bg-surface-3 px-3 text-body text-text focus-visible:outline-2 focus-visible:outline-accent"
                    >
                      {FRAME_RATES.map((f) => (
                        <option key={f.label} value={f.value ?? ""}>
                          {f.label}
                        </option>
                      ))}
                    </select>
                  </label>
                  <p className="basis-full text-caption font-normal text-text-faint">Previews are always 720p. Changing the shape or resolution later only re-renders.</p>
                </div>
              )}
            </div>
          </section>
        )}

        {p.step === 2 && (
          <section aria-label="Story" className="flex flex-col gap-5">
            <div role="radiogroup" aria-label="Story" onKeyDown={radioArrows} className="grid grid-cols-4 gap-3">
              {!p.presets
                ? [0, 1, 2, 3, 4, 5, 6, 7].map((i) => <div key={i} className="aspect-[4/3] animate-pulse rounded-lg bg-surface-1" />)
                : [
                    ...featured.map((x) => (
                      <StoryPresetCard
                        key={x.id}
                        label={x.label}
                        frames={p.collages[x.id] ?? []}
                        loading={p.collages[x.id] === undefined}
                        selected={!showOthers && r.story === x.id}
                        onClick={() => {
                          setCustomStory(false);
                          p.onChange({ story: x.id });
                        }}
                      />
                    )),
                    <StoryPresetCard key="custom" label="Custom" frames={[]} custom selected={showOthers} onClick={() => setCustomStory(true)} />,
                  ]}
            </div>
            {showOthers && (
              <div className="flex flex-col gap-2 rounded-lg border border-border bg-surface-1 p-[18px]">
                <span className="text-caption text-text-muted">More stories</span>
                <div role="radiogroup" aria-label="More stories" onKeyDown={radioArrows} className="flex flex-wrap gap-2">
                  {others.map((x) => (
                    <ChoiceChip key={x.id} selected={r.story === x.id} onClick={() => p.onChange({ story: x.id })}>
                      {x.label}
                    </ChoiceChip>
                  ))}
                </div>
                <p className="text-caption font-normal text-text-faint">
                  {others.find((x) => x.id === r.story)?.description ?? "Pick one, then describe the rest in step 6."}
                </p>
              </div>
            )}
            <div className="flex flex-col gap-1.5">
              <span className="text-caption text-text-muted">Chronology</span>
              <Segmented label="Chronology" value={r.chronology} options={CHRONOLOGY} onChange={(c) => p.onChange({ chronology: c })} className="self-start" />
            </div>
          </section>
        )}

        {p.step === 6 && (
          <section aria-label="Anything else" className="flex flex-col gap-3">
            <label className="flex flex-col gap-1.5">
              <span className="sr-only">Instructions for the editor</span>
              <textarea
                value={r.instructions}
                maxLength={MAX_INSTRUCTIONS}
                rows={6}
                placeholder="For example: avoid long driving sequences, include funny reactions and animal encounters, end with the strongest sunset or drone shot."
                onChange={(e) => p.onChange({ instructions: e.target.value })}
                className="w-full max-w-[720px] resize-y rounded-md border border-border bg-surface-3 px-3 py-2.5 text-body text-text placeholder:text-text-faint focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
              />
            </label>
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-caption text-text-muted">Ideas:</span>
              {IDEAS.map((idea) => (
                <button
                  key={idea}
                  type="button"
                  disabled={r.instructions.includes(idea)}
                  onClick={() => p.onChange({ instructions: [r.instructions.trim(), idea].filter(Boolean).join(" ").slice(0, MAX_INSTRUCTIONS) })}
                  className="rounded-full border border-border bg-surface-1 px-3 py-1.5 text-caption text-text hover:border-text-faint focus-visible:outline-2 focus-visible:outline-accent disabled:opacity-50"
                >
                  {idea.replace(/\.$/, "")}
                </button>
              ))}
            </div>
          </section>
        )}

        <div className="mt-auto flex items-center gap-2 pt-4">
          {p.step !== OPEN[0] && (
            <Button variant="ghost" onClick={() => go(-1)}>
              Back
            </Button>
          )}
          <span className="flex-1" />
          {nextLabel && <Button onClick={() => go(1)}>{nextLabel}</Button>}
        </div>
      </div>
      <EditSummaryPanel
        title={p.title}
        lines={summaryLines(r, p.presets ?? [])}
        warnings={warnings}
        estimate={p.estimateError ? "Estimate unavailable" : est ? estimateText(est) : null}
        estimatePending={p.estimatePending}
        creating={p.creating}
        disabled={noFootage}
        onCreate={p.onCreate}
      />
    </div>
  );
}
