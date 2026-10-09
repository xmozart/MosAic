import { ChevronDown } from "lucide-react";
import { useState, type ReactNode } from "react";

import { ModeCard } from "@/components/system/ModeCard";
import { Banner } from "@/components/ui/Banner";
import { Button } from "@/components/ui/Button";
import { Segmented } from "@/components/ui/Segmented";
import { SwitchRow } from "@/components/ui/Switch";
import { cn } from "@/lib/cn";
import { estimateLine, formatCost, formatWall, type Estimate } from "@/lib/estimate";
import { formatDuration, plural } from "@/lib/format";

import { FROM, MODES, SENSITIVITY, type Preset, type Setting, type Settings } from "./model";
import { RadioGroup } from "@/components/ui/RadioGroup";

const TILES: [number, number][] = [
  [3, 3],
  [4, 3],
  [4, 4],
  [5, 4],
  [6, 4],
];
const field =
  "h-10 w-full rounded-md border border-border bg-surface-3 px-3 text-body text-text focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:text-text-faint";

export interface AnalysisSetupViewProps {
  selected: Preset;
  onSelect: (m: Preset) => void;
  estimates: Partial<Record<Preset, Estimate>>;
  /** Effective settings with unsaved edits applied (value and where it comes from). */
  settings: Settings | undefined;
  edited: ReadonlySet<string>;
  onEdit: (key: string, value: unknown) => void; // null resets to the mode or app value
  sceneModel: string; // "Anthropic · claude-haiku-4-5"
  storyModel: string;
  device: string; // "Auto · Apple M4"
  localOnly: boolean;
  starting: boolean;
  onBack: () => void;
  onAnalyze: () => void;
}

function Field({ label, setting, edited, onReset, children }: { label: string; setting?: Setting; edited?: boolean; onReset?: () => void; children: ReactNode }) {
  const source = edited ? "Changed here" : setting ? FROM[setting.source] : null;
  return (
    <div className="flex flex-col gap-1.5">
      <span className="text-caption text-text-muted">{label}</span>
      {children}
      <span className="flex items-center gap-2 text-micro font-normal text-text-faint">
        {source}
        {onReset && (edited || setting?.source === "project") && (
          <button type="button" aria-label={`Reset ${label}`} onClick={onReset} className="rounded-sm text-text-muted underline-offset-2 hover:underline focus-visible:outline-2 focus-visible:outline-accent">
            Reset
          </button>
        )}
      </span>
    </div>
  );
}

/** A number field that can be emptied while typing: it commits valid numbers only, and
 * shows the effective value again when it loses focus empty. */
function NumberInput(p: { label: string; value: unknown; min: number; max: number; step: number; className: string; onCommit: (n: number) => void }) {
  const [text, setText] = useState<string | null>(null);
  const shown = text ?? (p.value === null || p.value === undefined ? "" : String(p.value));
  return (
    <input
      aria-label={p.label}
      type="number"
      inputMode="decimal"
      min={p.min}
      max={p.max}
      step={p.step}
      className={p.className}
      value={shown}
      onChange={(e) => {
        setText(e.target.value);
        const n = Number(e.target.value);
        if (e.target.value !== "" && Number.isFinite(n) && n >= p.min && n <= p.max) p.onCommit(n);
      }}
      onBlur={() => setText(null)}
    />
  );
}

/** S8 Analysis setup: three modes with honest estimates from the scanned footage, and
 * Advanced settings stored for this project (ADR 0041). Presentational. */
export function AnalysisSetupView(p: AnalysisSetupViewProps) {
  const [advanced, setAdvanced] = useState(false);
  const est = p.estimates[p.selected];
  const any = Object.values(p.estimates)[0];
  const s = p.settings;
  const v = (key: string) => s?.[key]?.value;
  const reset = (key: string) => () => p.onEdit(key, null);
  const tiles = v("analysis.tiles") as [number, number] | undefined;
  const sensitivity = (Object.entries(SENSITIVITY).find(([, sec]) => sec === v("analysis.forced_max_shot"))?.[0] ?? undefined) as
    | keyof typeof SENSITIVITY
    | undefined;
  const cloudOff = "Not available in Local only";
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex flex-1 flex-col gap-[22px] overflow-y-auto p-8">
        <div className="flex flex-col gap-1">
          <h1 className="text-title text-text">How deep should we look?</h1>
          <p className="text-body text-text-muted">
            {any
              ? `Estimates are for this trip: ${formatDuration(any.video_seconds)} of video and ${plural(any.photos, "photo")}.`
              : "Estimating from your footage…"}
          </p>
        </div>
        <RadioGroup label="Analysis mode" className="grid grid-cols-3 gap-4">
          {MODES.map((m) => {
            const e = p.estimates[m.id];
            return (
              <ModeCard
                key={m.id}
                title={m.title}
                description={m.description}
                recommended={m.id === "balanced"}
                selected={p.selected === m.id}
                onSelect={() => p.onSelect(m.id)}
                estimate={e ? estimateLine(e) : ""}
                loading={!e}
              />
            );
          })}
        </RadioGroup>
        <Banner kind="info">You can start editing as soon as the first pass finishes, and deepen analysis later for the days that matter.</Banner>
        <section className="flex flex-col gap-4 rounded-lg border border-border bg-surface-1 p-5">
          <button
            type="button"
            aria-expanded={advanced}
            aria-controls={advanced ? "advanced" : undefined}
            onClick={() => setAdvanced(!advanced)}
            className="flex items-center gap-2 rounded-sm text-left focus-visible:outline-2 focus-visible:outline-accent"
          >
            <ChevronDown aria-hidden className={cn("size-4 text-text-muted transition-transform", advanced ? "" : "-rotate-90")} />
            <span className="text-subhead font-semibold text-text">Advanced</span>
            <span className="ml-auto text-caption font-normal text-text-muted">
              Showing settings for {MODES.find((m) => m.id === p.selected)!.title}
            </span>
          </button>
          {advanced && (
            <div id="advanced" className="flex flex-col gap-5">
              <div className="grid grid-cols-4 gap-4">
                <Field label="Sample a frame every" setting={s?.["analysis.sample_interval"]} edited={p.edited.has("analysis.sample_interval")} onReset={reset("analysis.sample_interval")}>
                  <span className="relative">
                    <NumberInput
                      label="Sample a frame every (seconds)"
                      min={0.5}
                      max={600}
                      step={0.5}
                      className={cn(field, "mono pr-8")}
                      value={v("analysis.sample_interval")}
                      onCommit={(x) => p.onEdit("analysis.sample_interval", String(x))}
                    />
                    <span className="pointer-events-none absolute top-1/2 right-3 -translate-y-1/2 text-small text-text-muted">s</span>
                  </span>
                </Field>
                <Field label="Frames per contact sheet" setting={s?.["analysis.tiles"]} edited={p.edited.has("analysis.tiles")} onReset={reset("analysis.tiles")}>
                  <select
                    aria-label="Frames per contact sheet"
                    className={cn(field, "mono")}
                    value={tiles ? tiles.join("x") : ""}
                    onChange={(e) => p.onEdit("analysis.tiles", e.target.value.split("x").map(Number))}
                  >
                    {TILES.map(([c, r]) => (
                      <option key={`${c}x${r}`} value={`${c}x${r}`}>
                        {c * r} ({c} × {r})
                      </option>
                    ))}
                  </select>
                </Field>
                <Field label="Scene sensitivity" setting={s?.["analysis.forced_max_shot"]} edited={p.edited.has("analysis.forced_max_shot")} onReset={reset("analysis.forced_max_shot")}>
                  <Segmented
                    label="Scene sensitivity"
                    value={sensitivity}
                    onChange={(x) => p.onEdit("analysis.forced_max_shot", SENSITIVITY[x])}
                    options={[
                      { value: "low", label: "Low" },
                      { value: "medium", label: "Medium" },
                      { value: "high", label: "High" },
                    ]}
                  />
                </Field>
                <Field label="Preview resolution" setting={s?.["analysis.proxy"]} edited={p.edited.has("analysis.proxy")} onReset={reset("analysis.proxy")}>
                  <select aria-label="Preview resolution" className={field} value={String(v("analysis.proxy") ?? "720")} onChange={(e) => p.onEdit("analysis.proxy", e.target.value)}>
                    <option value="720">720p</option>
                    <option value="lrf_or_540">540p, or the camera's own preview</option>
                  </select>
                </Field>
                <Field label="Speech model" setting={s?.["analysis.stt_model"]} edited={p.edited.has("analysis.stt_model")} onReset={reset("analysis.stt_model")}>
                  <select
                    aria-label="Speech model"
                    className={field}
                    value={String(v("analysis.stt_model") ?? "")}
                    onChange={(e) => p.onEdit("analysis.stt_model", e.target.value || null)}
                  >
                    <option value="">Auto · on this computer</option>
                    <option value="small">Small · on this computer</option>
                    <option value="medium">Medium · on this computer</option>
                    <option value="large-v3">Large · on this computer</option>
                  </select>
                </Field>
                <Field label="Scene understanding">
                  <input aria-label="Scene understanding" readOnly disabled={p.localOnly} className={field} value={p.localOnly ? cloudOff : p.sceneModel} />
                </Field>
                <Field label="Story & editing">
                  <input aria-label="Story & editing" readOnly disabled={p.localOnly} className={field} value={p.localOnly ? cloudOff : p.storyModel} />
                </Field>
                <Field label="Processing device">
                  <input aria-label="Processing device" readOnly className={field} value={p.device} />
                </Field>
              </div>
              <div className="grid grid-cols-[1fr_220px] items-end gap-6">
                <SwitchRow
                  label="Use GPS for analysis"
                  description="Location stays on this computer. No analysis step uses it yet."
                  checked={Boolean(v("ai.send_gps"))}
                  onChange={(on) => p.onEdit("ai.send_gps", on)}
                />
                <Field label="Cost limit for this project" setting={s?.["analysis.cost_limit_usd"]} edited={p.edited.has("analysis.cost_limit_usd")} onReset={reset("analysis.cost_limit_usd")}>
                  <span className="relative">
                    <span className="pointer-events-none absolute top-1/2 left-3 -translate-y-1/2 text-body text-text-muted">$</span>
                    <NumberInput
                      label="Cost limit for this project (dollars)"
                      min={0}
                      max={10000}
                      step={1}
                      className={cn(field, "mono pl-7")}
                      value={v("analysis.cost_limit_usd")}
                      onCommit={(x) => p.onEdit("analysis.cost_limit_usd", x)}
                    />
                  </span>
                </Field>
              </div>
            </div>
          )}
        </section>
      </div>
      <footer className="sticky bottom-0 flex h-[68px] shrink-0 items-center gap-4 border-t border-border bg-surface-1 px-8">
        <Button variant="ghost" onClick={p.onBack}>
          Back
        </Button>
        <span className="mono ml-auto text-timecode text-text-muted">
          {est ? `${MODES.find((m) => m.id === p.selected)!.title} · ${formatWall(est.wall_seconds).toLowerCase()} · ${formatCost(est.cost_usd)}` : "Estimating…"}
        </span>
        <Button variant="primary" disabled={p.starting || !est} onClick={p.onAnalyze}>
          Analyze
        </Button>
      </footer>
    </div>
  );
}
