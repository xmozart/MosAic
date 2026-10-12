import { ChevronDown, ChevronUp } from "lucide-react";
import { useEffect, useState } from "react";

import { BeatsEditor, LevelSlider, MusicTrackCard, PaceSlider, WeightSlider, type TrackInfo } from "@/components/edit/Controls";
import { AspectPicker, ChoiceChip, DurationChips, EditSummaryPanel, StoryPresetCard, WizardStepNav, type AspectOption } from "@/components/edit/Wizard";
import { CheckboxRow } from "@/components/ui/Checkbox";
import { Banner } from "@/components/ui/Banner";
import { Button } from "@/components/ui/Button";
import { Segmented } from "@/components/ui/Segmented";
import { SwitchRow } from "@/components/ui/Switch";
import { TextField } from "@/components/ui/TextField";
import { formatClock } from "@/lib/time";

import {
  ARCS,
  ASPECTS,
  CATEGORIES,
  CHRONOLOGY,
  MAX_BEAT_CHARS,
  MAX_BEATS,
  MIN_BEATS,
  MUSIC_DEFAULT,
  PACES,
  PHOTO_SHARES,
  RULES,
  TRANSITIONS,
  WEIGHTS,
  beatsProblem,
  paceReadout,
  type Arc,
  type Category,
  type CategoryCount,
  type Music,
  type PhotoShare,
  type Transitions,
  type Weight,
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
import { RadioGroup } from "@/components/ui/RadioGroup";

const OPEN = STEPS.filter((s) => !s.later).map((s) => s.id);
const TITLES: Record<number, string> = {
  1: "How long, and where will it play?",
  2: "What kind of story?",
  3: "What should we feature?",
  4: "Pace and transitions",
  5: "Sound",
  6: "Anything else for the editor?",
};
const FEATURED = 6; // step 3 shows the six categories that matter most in this footage
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
  /** Step 3: the library's categories, most frequent first; missing while loading. */
  categories?: CategoryCount[];
  /** Step 5: the chosen track as read; null while reading. */
  track?: TrackInfo | null;
  trackError?: string | null;
  /** Step 5: pick a track (the desktop's file dialog; false when cancelled); without one the
   * view asks for the track's path. */
  onChooseTrack?: () => Promise<boolean>;
}

/** S14 Create edit wizard: six steps and the summary panel (ADR 0048, 0086). Presentational. */
export function WizardView(p: WizardViewProps) {
  const r = p.request;
  const [customPicked, setCustomLength] = useState(false);
  // A length that is not a chip (a prefilled 75 s) is custom without a click.
  const customLength = customPicked || !(DURATIONS as readonly number[]).includes(r.duration_s);
  const [moreFormat, setMoreFormat] = useState(false);
  const featured = p.presets?.filter((x) => x.featured) ?? [];
  const [moreStory, setMoreStory] = useState(r.arc !== "classic_travel");
  const [extraCategories, setExtraCategories] = useState<Category[]>([]);
  const [moreRules, setMoreRules] = useState(false);
  const [musicChoice, setMusicChoice] = useState<"none" | "track">(r.music ? "track" : "none");
  const [trackPath, setTrackPath] = useState(r.music?.path ?? "");
  // The level and fades outlive a change of track (Change, in a browser, clears the track).
  const [lastMusic, setLastMusic] = useState<Music | null>(r.music);
  const setWeight = (c: Category, w: Weight) => {
    const weights = { ...r.weights };
    if (w === "neutral") delete weights[c];
    else weights[c] = w;
    p.onChange({ weights });
  };
  const ranked = p.categories?.map((c) => c.category) ?? [];
  const shown = [...ranked.slice(0, FEATURED), ...extraCategories.filter((c) => !ranked.slice(0, FEATURED).includes(c))];
  const chooseTrack = () => {
    setMusicChoice("track");
    if (p.onChooseTrack) {
      void p.onChooseTrack().then((picked) => {
        if (!picked && !r.music) setMusicChoice("none"); // cancelled, and no track before
      });
    } else if (r.music) {
      setLastMusic(r.music);
      p.onChange({ music: null }); // Change, in a browser: type another path
    }
  };
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
  const badBeats = r.arc === "custom" && beatsProblem(r.beats);
  const { onCreate, creating } = p;
  useEffect(() => {
    const on = (e: KeyboardEvent) => {
      if (!(e.metaKey || e.ctrlKey)) return;
      if (e.key === "Enter" && !creating && !noFootage && !badBeats) {
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
      {badBeats && <Banner kind="warning">{badBeats}</Banner>}
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
            <RadioGroup label="Story" className="grid grid-cols-4 gap-3">
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
            </RadioGroup>
            {showOthers && (
              <div className="flex flex-col gap-2 rounded-lg border border-border bg-surface-1 p-[18px]">
                <span className="text-caption text-text-muted">More stories</span>
                <RadioGroup label="More stories" className="flex flex-wrap gap-2">
                  {others.map((x) => (
                    <ChoiceChip key={x.id} selected={r.story === x.id} onClick={() => p.onChange({ story: x.id })}>
                      {x.label}
                    </ChoiceChip>
                  ))}
                </RadioGroup>
                <p className="text-caption font-normal text-text-faint">
                  {others.find((x) => x.id === r.story)?.description ?? "Pick one, then describe the rest in step 6."}
                </p>
              </div>
            )}
            <div className="flex flex-col gap-1.5">
              <span className="text-caption text-text-muted">Chronology</span>
              <Segmented label="Chronology" value={r.chronology} options={CHRONOLOGY} onChange={(c) => p.onChange({ chronology: c })} className="self-start" />
            </div>
            <MoreToggle open={moreStory} onToggle={() => setMoreStory((m) => !m)}>
              More options
            </MoreToggle>
            {moreStory && (
              <div className="flex flex-col gap-4 rounded-lg border border-border bg-surface-1 p-[18px]">
                <div className="flex flex-col gap-1.5">
                  <span className="text-caption text-text-muted">Arc template</span>
                  <Segmented<Arc>
                    label="Arc template"
                    value={r.arc}
                    options={ARCS}
                    className="self-start"
                    onChange={(arc) =>
                      p.onChange(arc === "custom" ? { arc, beats: r.beats.length ? r.beats : ["", ""] } : { arc, beats: [] })
                    }
                  />
                </div>
                {r.arc === "custom" ? (
                  <BeatsEditor beats={r.beats} min={MIN_BEATS} max={MAX_BEATS} maxChars={MAX_BEAT_CHARS} onChange={(beats) => p.onChange({ beats })} />
                ) : (
                  <p className="text-caption font-normal text-text-faint">The editor plans the beats from your footage. Choose Custom beats to name and order them yourself.</p>
                )}
              </div>
            )}
          </section>
        )}

        {p.step === 3 && (
          <section aria-label="What to feature" className="flex flex-col gap-5">
            <p className="-mt-3 text-body text-text-muted">The six categories that matter most in your footage are shown first.</p>
            <div className="grid grid-cols-2 gap-3.5">
              {!p.categories
                ? [0, 1, 2, 3, 4, 5].map((i) => <div key={i} className="h-[66px] animate-pulse rounded-lg bg-surface-1" />)
                : shown.map((c) => (
                    <WeightSlider key={c} label={CATEGORIES[c]} value={r.weights[c] ?? "neutral"} steps={WEIGHTS} onChange={(w) => setWeight(c, w)} />
                  ))}
            </div>
            {p.categories && (
              <div className="flex flex-col gap-2">
                <span className="text-caption font-medium text-text-muted">More categories</span>
                <div className="flex flex-wrap gap-1.5">
                  {ranked.some((c) => !shown.includes(c)) && (
                    <button
                      type="button"
                      onClick={() => setExtraCategories(ranked)}
                      className="order-last rounded-full border border-border bg-surface-2 px-[9px] py-[3px] text-caption font-semibold text-text hover:border-text-faint focus-visible:outline-2 focus-visible:outline-accent"
                    >
                      All categories
                    </button>
                  )}
                  {ranked
                    .filter((c) => !shown.includes(c))
                    .map((c) => (
                      <button
                        key={c}
                        type="button"
                        onClick={() => setExtraCategories((xs) => [...xs, c])}
                        className="rounded-full border border-border bg-surface-2 px-[9px] py-[3px] text-caption text-text-muted hover:text-text focus-visible:outline-2 focus-visible:outline-accent"
                      >
                        {CATEGORIES[c]}
                      </button>
                    ))}
                </div>
              </div>
            )}
          </section>
        )}

        {p.step === 4 && (
          <section aria-label="Style" className="flex max-w-[720px] flex-col gap-5">
            <PaceSlider value={r.pace} stops={PACES} readout={paceReadout(r.pace)} onChange={(pace) => p.onChange({ pace })} />
            <div className="flex flex-col gap-1.5">
              <span className="text-caption text-text-muted">Transitions</span>
              <Segmented<Transitions> label="Transitions" value={r.transitions} options={TRANSITIONS} onChange={(transitions) => p.onChange({ transitions })} className="self-start" />
            </div>
            <div className="grid grid-cols-2 gap-2.5">
              {RULES.filter((x) => !x.more || moreRules).map((x) => (
                <CheckboxRow key={x.key} label={x.label} checked={r.rules[x.key]} onChange={(on) => p.onChange({ rules: { ...r.rules, [x.key]: on } })} />
              ))}
            </div>
            <MoreToggle open={moreRules} onToggle={() => setMoreRules((m) => !m)}>
              More options
            </MoreToggle>
            <div className="flex flex-col gap-1.5">
              <span className="text-caption text-text-muted">Photo share</span>
              <Segmented<PhotoShare> label="Photo share" value={r.photo_share} options={PHOTO_SHARES} onChange={(photo_share) => p.onChange({ photo_share })} className="self-start" />
            </div>
          </section>
        )}

        {p.step === 5 && (
          <section aria-label="Sound" className="flex max-w-[560px] flex-col gap-5">
            <SwitchRow label="Keep dialogue" description="Never cut someone mid-sentence" checked={r.audio.keep_dialogue} onChange={(on) => p.onChange({ audio: { ...r.audio, keep_dialogue: on } })} />
            <SwitchRow label="Keep natural sound" description="Waterfalls, waves, laughter" checked={r.audio.natural_sound} onChange={(on) => p.onChange({ audio: { ...r.audio, natural_sound: on } })} />
            <SwitchRow label="Reduce wind and noise" checked={r.audio.reduce_wind} onChange={(on) => p.onChange({ audio: { ...r.audio, reduce_wind: on } })} />
            <div className="flex flex-col gap-1.5">
              <span className="text-caption text-text-muted">Music</span>
              <Segmented<"none" | "track">
                label="Music"
                value={musicChoice}
                options={[
                  { value: "none", label: "None" },
                  { value: "track", label: "Choose track" },
                ]}
                className="self-start"
                onChange={(v) => {
                  if (v === "none") {
                    setMusicChoice("none");
                    p.onChange({ music: null });
                  } else chooseTrack();
                }}
              />
            </div>
            {musicChoice === "track" && r.music && <MusicTrackCard track={p.track ?? null} error={p.trackError} onChange={chooseTrack} />}
            {musicChoice === "track" && !p.onChooseTrack && (
              <form
                className="flex items-end gap-2"
                onSubmit={(e) => {
                  e.preventDefault();
                  const path = trackPath.trim();
                  if (path) p.onChange({ music: { ...(r.music ?? lastMusic ?? MUSIC_DEFAULT), path } });
                }}
              >
                <TextField className="flex-1" label="The track's full path" value={trackPath} placeholder="/Users/me/Music/Horizon.mp3" onChange={(e) => setTrackPath(e.target.value)} />
                <Button type="submit" variant="secondary">
                  Use this track
                </Button>
              </form>
            )}
            {r.music && (
              <LevelSlider
                label="Music level"
                value={r.music.level_db}
                min={-40}
                readout={`${r.music.level_db < 0 ? "−" : ""}${Math.abs(r.music.level_db)} dB under dialogue`}
                onChange={(level_db) => p.onChange({ music: { ...r.music!, level_db } })}
              />
            )}
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
        disabled={noFootage || Boolean(badBeats)}
        onCreate={p.onCreate}
      />
    </div>
  );
}

function MoreToggle({ open, onToggle, children }: { open: boolean; onToggle: () => void; children: React.ReactNode }) {
  return (
    <button
      type="button"
      aria-expanded={open}
      onClick={onToggle}
      className="inline-flex items-center gap-1.5 self-start rounded-full border border-border bg-surface-2 px-[9px] py-[3px] text-caption text-text-muted hover:text-text focus-visible:outline-2 focus-visible:outline-accent"
    >
      {open ? <ChevronUp aria-hidden className="size-3.5" /> : <ChevronDown aria-hidden className="size-3.5" />}
      {children}
    </button>
  );
}
