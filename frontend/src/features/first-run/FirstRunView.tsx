import { Check, Download, Map, RotateCw, X } from "lucide-react";
import { useEffect, type ReactNode } from "react";

import mark from "@/assets/brand/mosaic-mark.svg";
import { ChoiceCard } from "@/components/system/ChoiceCard";
import { SecretField } from "@/components/system/SecretField";
import { Button } from "@/components/ui/Button";
import { RadioGroup } from "@/components/ui/RadioGroup";
import { cn } from "@/lib/cn";

import { formatBytes } from "@/lib/format";

import type { ModelRow } from "./model";

export type FirstRunStep = 1 | 2 | 3;
export type AiMode = "hybrid" | "local";

export interface FirstRunViewProps {
  step: FirstRunStep;
  onStep: (s: FirstRunStep) => void;
  mode: AiMode;
  onMode: (m: AiMode) => void;
  providers: { id: string; label: string }[];
  provider: string;
  onProvider: (id: string) => void;
  keyLast4?: string;
  keyStatus?: "ok" | "invalid";
  validating?: boolean;
  onSaveKey: (value: string) => Promise<void>;
  onValidateKey: () => void;
  models: ModelRow[] | undefined;
  onRetry: (name: string) => void;
  onFinish: () => void;
  finishing?: boolean;
}

/** S1 First run (desktop only): welcome, AI mode and key, on-device models. Presentational. */
export function FirstRunView(p: FirstRunViewProps) {
  const { step, onStep, onFinish } = p;
  // Enter continues and Esc goes back from wherever focus is (S1 Keyboard). Keys typed
  // into a field or pressed on a button keep their own meaning (the key field's Save).
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement | null;
      if (e.repeat) return; // a held key acts once
      if (e.key === "Escape" && step > 1 && !(t && /^(INPUT|TEXTAREA)$/.test(t.tagName))) {
        e.preventDefault();
        onStep((step - 1) as FirstRunStep);
      } else if (e.key === "Enter" && !(t && /^(INPUT|TEXTAREA|SELECT|BUTTON)$/.test(t.tagName))) {
        e.preventDefault();
        if (step === 3) onFinish();
        else onStep((step + 1) as FirstRunStep);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [step, onStep, onFinish]);
  return (
    <main className="relative flex min-h-screen flex-col items-center justify-center overflow-hidden bg-bg px-6 py-16">
      <div aria-hidden className="pointer-events-none absolute -top-[520px] left-1/2 size-[820px] -translate-x-1/2 rounded-full bg-accent-soft blur-3xl" />
      <div className="relative flex w-full max-w-[860px] flex-col items-center gap-6">
        {p.step === 1 && <Welcome onStart={() => p.onStep(2)} />}
        {p.step === 2 && <AiStep {...p} />}
        {p.step === 3 && <ModelsStep {...p} />}
        <Dots step={p.step} />
      </div>
    </main>
  );
}

function Dots({ step }: { step: FirstRunStep }) {
  return (
    <div role="progressbar" aria-label="First-run step" aria-valuemin={1} aria-valuemax={3} aria-valuenow={step} className="flex items-center gap-1.5">
      {[1, 2, 3].map((n) => (
        <span key={n} className={cn("h-1.5 rounded-full", n === step ? "w-6 bg-accent" : n < step ? "w-1.5 bg-accent" : "w-1.5 bg-surface-3")} />
      ))}
    </div>
  );
}

function Welcome({ onStart }: { onStart: () => void }) {
  return (
    <div className="flex flex-col items-center gap-5 text-center">
      <span className="flex size-24 items-center justify-center rounded-lg bg-surface-1">
        <img src={mark} alt="" width={64} height={64} />
      </span>
      <h1 className="text-display font-semibold tracking-[-0.02em] text-text">
        Mos<span className="text-accent">Ai</span>c
      </h1>
      <p className="text-subhead text-text-muted">Your trip, told well.</p>
      <Button variant="primary" size="lg" autoFocus onClick={onStart}>
        Get started
      </Button>
    </div>
  );
}

const MODES: { id: AiMode; title: string; text: string; badge?: string }[] = [
  { id: "hybrid", title: "Hybrid", badge: "Recommended", text: "Processing stays on this Mac; the AI sees selected frames and text." },
  { id: "local", title: "Local only", text: "Most private. Story editing and scene understanding are limited." },
];

const LOCAL_LIMITS = [
  "No AI descriptions of scenes; clips are found by speech and similar shots only",
  "No AI story planning: edits follow time and the clips you rate",
  "No deep review of candidate shots",
];

function AiStep(p: FirstRunViewProps) {
  return (
    <div className="flex w-full flex-col items-center gap-5">
      <div className="flex flex-col items-center gap-2 text-center">
        <h1 className="text-title text-text">How should MosAic use AI?</h1>
        <p className="text-body text-text-muted">You can change this anytime in Settings.</p>
      </div>
      <RadioGroup label="AI mode" className="grid w-full grid-cols-2 gap-3">
        {MODES.map((m) => (
          <ChoiceCard key={m.id} selected={p.mode === m.id} title={m.title} text={m.text} badge={m.badge} onClick={() => p.onMode(m.id)} />
        ))}
      </RadioGroup>
      {p.mode === "hybrid" ? (
        <section aria-label="AI provider" className="flex w-full flex-col gap-3 rounded-lg border border-border bg-surface-1 p-5">
          <label className="flex items-center gap-2 text-caption text-text-muted">
            Provider
            <select
              value={p.provider}
              onChange={(e) => p.onProvider(e.target.value)}
              className="h-9 rounded-md border border-border bg-surface-3 px-2.5 text-small text-text focus-visible:outline-2 focus-visible:outline-accent"
            >
              {p.providers.map((x) => (
                <option key={x.id} value={x.id}>
                  {x.label}
                </option>
              ))}
            </select>
          </label>
          <SecretField
            label={`${p.providers.find((x) => x.id === p.provider)?.label ?? p.provider} API key`}
            where="Stored in your Mac's Keychain. It never goes into project folders."
            last4={p.keyLast4}
            status={p.keyStatus}
            validating={p.validating}
            onSave={p.onSaveKey}
            onValidate={p.onValidateKey}
          />
          {p.keyStatus === "invalid" && <p className="text-caption text-reject">That key was refused. Check it and paste it again.</p>}
          {!p.keyLast4 && <p className="text-caption font-normal text-text-faint">No key yet? You can continue and add it later in Settings.</p>}
        </section>
      ) : (
        <section aria-label="Not available in Local only" className="flex w-full flex-col gap-2 rounded-lg border border-border bg-surface-1 p-5">
          <span className="text-caption font-semibold text-text-faint">Not available in Local only</span>
          <ul className="flex flex-col gap-1.5">
            {LOCAL_LIMITS.map((t) => (
              <li key={t} className="flex items-start gap-2 text-small text-text-muted">
                <X aria-hidden className="mt-0.5 size-4 shrink-0 text-text-faint" />
                {t}
              </li>
            ))}
          </ul>
        </section>
      )}
      <div className="grid w-full grid-cols-3 gap-5 rounded-lg border border-border bg-surface-1 p-5">
        <Explain icon={<Check className="size-4 text-use" />} title="Sent to the AI">
          Contact sheets of sampled frames, transcripts of speech, your edit instructions.
        </Explain>
        <Explain icon={<X className="size-4 text-reject" />} title="Never sent">
          Your original video and photo files. API keys to anyone but the provider.
        </Explain>
        <Explain icon={<Map className="size-4 text-accent" />} title="Only if you allow">
          GPS locations. Off by default — place names you type are fine.
        </Explain>
      </div>
      <div className="flex w-full items-center justify-between">
        <Button variant="ghost" onClick={() => p.onStep(1)}>
          Back
        </Button>
        <Button variant="primary" onClick={() => p.onStep(3)}>
          Continue
        </Button>
      </div>
    </div>
  );
}

function Explain({ icon, title, children }: { icon: ReactNode; title: string; children: ReactNode }) {
  return (
    <div className="flex flex-col gap-1.5">
      <span className="flex items-center gap-2 text-small font-semibold text-text">
        {icon}
        {title}
      </span>
      <span className="text-caption font-normal text-text-muted">{children}</span>
    </div>
  );
}

const DESCRIPTION: Record<string, string> = {
  transcriber: "Transcribes what people say in your clips",
  embedder: "Powers visual search and similar-shot grouping",
};

function ModelsStep(p: FirstRunViewProps) {
  const rows = p.models?.filter((m) => m.needed);
  return (
    <div className="flex w-full max-w-[620px] flex-col items-center gap-5">
      <div className="flex flex-col items-center gap-2 text-center">
        <h1 className="text-title text-text">Downloading on-device models</h1>
        <p className="text-body text-text-muted">These run on your Mac so speech and search stay private. One-time download.</p>
      </div>
      {!rows ? (
        <div aria-label="Loading models" className="h-40 w-full animate-pulse rounded-lg bg-surface-1" />
      ) : (
        rows.map((m) => <ModelCard key={m.name} m={m} onRetry={() => p.onRetry(m.name)} />)
      )}
      <div className="flex w-full items-center justify-between">
        <Button variant="ghost" onClick={() => p.onStep(2)}>
          Back
        </Button>
        <Button variant="primary" autoFocus disabled={p.finishing} onClick={p.onFinish}>
          {rows && rows.every((m) => m.installed) ? "Continue" : "Continue while downloading"}
        </Button>
      </div>
    </div>
  );
}

function ModelCard({ m, onRetry }: { m: ModelRow; onRetry: () => void }) {
  const pct = m.installed ? 100 : Math.floor((100 * m.downloaded_bytes) / Math.max(1, m.bytes));
  const paused = !m.installed && m.job?.state === "failed";
  return (
    <section aria-label={m.label} className="flex w-full flex-col gap-3 rounded-lg border border-border bg-surface-1 p-5">
      <div className="flex items-center gap-3">
        {m.installed ? <Check aria-hidden className="size-4 text-use" /> : <Download aria-hidden className="size-4 text-accent" />}
        <div className="flex min-w-0 flex-col">
          <span className="text-body font-semibold text-text">{m.capability === "transcriber" ? "Speech recognition" : "Image understanding"}</span>
          <span className="text-caption font-normal text-text-muted">{DESCRIPTION[m.capability]}</span>
        </div>
        <span className="mono ml-auto text-timecode text-text-muted">{formatBytes(m.bytes)}</span>
      </div>
      <span className="h-1.5 w-full overflow-hidden rounded-full bg-surface-3">
        <span className="block h-full rounded-full bg-accent transition-[width] duration-300" style={{ width: `${pct}%` }} />
      </span>
      <div className="flex items-center justify-between text-caption">
        <span className="text-text">{pct}%</span>
        {m.installed ? (
          <span className="text-text-muted">Ready</span>
        ) : paused ? (
          <span className="flex items-center gap-2 text-text-muted">
            Download paused — check your connection
            <Button size="sm" onClick={onRetry}>
              <RotateCw /> Retry
            </Button>
          </span>
        ) : (
          <span className="text-text-muted">
            {formatBytes(m.downloaded_bytes)} of {formatBytes(m.bytes)}
          </span>
        )}
      </div>
    </section>
  );
}

