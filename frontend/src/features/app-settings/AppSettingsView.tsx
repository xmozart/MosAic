import { Check, Cloud, HardDrive, MonitorSmartphone, Plus, ShieldCheck, X } from "lucide-react";
import { useState, type ReactNode } from "react";

import { radioArrows } from "@/components/edit/radioArrows";
import { SectionNav } from "@/components/system/SectionNav";
import { SecretField } from "@/components/system/SecretField";
import { SettingRow, type SettingSource } from "@/components/system/SettingRow";
import { Banner } from "@/components/ui/Banner";
import { Button } from "@/components/ui/Button";
import { Segmented } from "@/components/ui/Segmented";
import { TextField } from "@/components/ui/TextField";
import { cn } from "@/lib/cn";
import { formatBytes } from "@/lib/format";
import type { ThemeChoice } from "@/lib/theme";

import {
  MODE_LABEL,
  PROVIDER_LABEL,
  SECTIONS,
  TASKS,
  keyProviders,
  sourceWords,
  storeText,
  type AppSettings,
  type MediaRoot,
  type ProviderOptions,
  type Providers,
  type SystemInfo,
} from "./model";

export interface AppSettingsViewProps {
  theme: ThemeChoice;
  onTheme: (t: ThemeChoice) => void;
  settings: AppSettings | undefined;
  onSetting: (key: string, value: unknown) => void;
  providers: Providers | undefined;
  options: ProviderOptions | undefined;
  onProvider: (task: string, choice: { provider: string; model: string } | null) => void;
  /** Key validation results per provider ("ok" | "invalid"); absent: not validated. */
  keyChecks: Record<string, "ok" | "invalid" | "checking">;
  onSaveKey: (provider: string, value: string) => Promise<void>;
  onValidateKey: (provider: string) => void;
  /** Removes the key the user entered (a deployment key, if any, is used again). */
  onRemoveKey: (provider: string) => void;
  system: SystemInfo | undefined;
  /** Server only (S22b): the folders users may open; undefined on desktop. */
  roots?: MediaRoot[];
  onAddRoot?: (path: string, label: string) => void;
  onRemoveRoot?: (root: MediaRoot) => void;
  /** The open trip, for "This trip's settings". */
  trip?: { name: string; onOpen: () => void };
}

/** S22 App settings (M2: appearance, analysis defaults, AI providers, processing, media
 * roots, about; ADR 0053). Presentational. */
export function AppSettingsView(p: AppSettingsViewProps) {
  const [active, setActive] = useState("ai");
  const sections = SECTIONS.filter((s) => s.id !== "roots" || p.roots !== undefined);
  const go = (id: string) => {
    setActive(id);
    document.getElementById(`section-${id}`)?.scrollIntoView({ behavior: "smooth", block: "start" });
  };
  return (
    <div className="flex min-h-0 flex-1">
      <SectionNav title="Settings" sections={sections} active={active} onSelect={go} />
      <div className="min-w-0 flex-1 overflow-y-auto px-9 py-7">
        <div className="flex max-w-[920px] flex-col gap-10">
          {p.trip && (
            <div className="flex items-center gap-3 rounded-lg border border-border bg-surface-1 px-[18px] py-3.5">
              <span className="text-body text-text">Settings for “{p.trip.name}”: analysis, cameras, storage.</span>
              <Button size="sm" className="ml-auto" onClick={p.trip.onOpen}>
                Project settings
              </Button>
            </div>
          )}
          <Appearance {...p} />
          <AnalysisDefaults {...p} />
          <AIProviders {...p} />
          <Processing {...p} />
          {p.roots !== undefined && <Roots {...p} />}
          <About {...p} />
        </div>
      </div>
    </div>
  );
}

function Title({ id, children, sub }: { id: string; children: ReactNode; sub?: ReactNode }) {
  return (
    <div className="flex flex-col gap-1">
      <h2 id={`section-${id}`} className="scroll-mt-6 text-title tracking-[-0.01em] text-text">
        {children}
      </h2>
      {sub && <p className="text-body text-text-muted">{sub}</p>}
    </div>
  );
}

function Card({ children, title }: { children: ReactNode; title?: string }) {
  return (
    <div className="flex flex-col gap-3 rounded-lg border border-border bg-surface-1 p-[18px]">
      {title && <h3 className="text-subhead font-semibold tracking-[-0.01em] text-text">{title}</h3>}
      {children}
    </div>
  );
}

function src(s: AppSettings | undefined, key: string): SettingSource {
  return (s?.[key]?.source ?? "default") as SettingSource;
}

function Appearance(p: AppSettingsViewProps) {
  return (
    <section aria-labelledby="section-appearance" className="flex flex-col gap-3">
      <Title id="appearance">Appearance</Title>
      <SettingRow
        label="Theme"
        description="System follows your computer's light or dark setting. Kept in this browser."
        source={p.theme === "system" ? "default" : "user"}
        onReset={() => p.onTheme("system")}
        control={
          <Segmented<ThemeChoice>
            label="Theme"
            value={p.theme}
            onChange={p.onTheme}
            options={[
              { value: "system", label: "System" },
              { value: "dark", label: "Dark" },
              { value: "light", label: "Light" },
            ]}
          />
        }
      />
    </section>
  );
}

function MoneyInput({ label, value, onCommit }: { label: string; value: unknown; onCommit: (v: number) => void }) {
  const [draft, setDraft] = useState<string | null>(null);
  const shown = draft ?? (value == null ? "" : String(value));
  return (
    <span className="relative">
      <span aria-hidden className="pointer-events-none absolute top-1/2 left-3 -translate-y-1/2 text-body text-text-faint">
        $
      </span>
      <input
        aria-label={label}
        type="number"
        min={0}
        step={1}
        value={shown}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={() => {
          const n = Number(shown);
          if (shown.trim() !== "" && Number.isFinite(n) && n >= 0 && n !== value) onCommit(n);
          setDraft(null);
        }}
        className="mono h-10 w-32 rounded-md border border-border bg-surface-3 pr-3 pl-7 text-timecode text-text focus-visible:outline-2 focus-visible:outline-accent"
      />
    </span>
  );
}

function AnalysisDefaults(p: AppSettingsViewProps) {
  const s = p.settings;
  return (
    <section aria-labelledby="section-analysis" className="flex flex-col gap-2">
      <Title id="analysis" sub="Used by new trips. Each trip can change them in its own settings.">
        Analysis defaults
      </Title>
      {!s ? (
        <div aria-label="Loading settings" className="h-24 animate-pulse rounded-lg bg-surface-1" />
      ) : (
        <div className="flex flex-col">
          <SettingRow
            label="Analysis mode"
            source={src(s, "analysis.mode")}
            onReset={() => p.onSetting("analysis.mode", null)}
            control={
              <Segmented
                label="Default analysis mode"
                value={String(s["analysis.mode"]?.value ?? "balanced")}
                onChange={(v) => p.onSetting("analysis.mode", v)}
                options={[
                  { value: "quick", label: "Quick" },
                  { value: "balanced", label: "Balanced" },
                  { value: "thorough", label: "Thorough" },
                ]}
              />
            }
          />
          <SettingRow
            label="AI cost limit per run"
            description="A job pauses here and asks before it spends more."
            source={src(s, "ai.budget.per_job_usd")}
            onReset={() => p.onSetting("ai.budget.per_job_usd", null)}
            control={<MoneyInput label="Default AI cost limit in dollars" value={s["ai.budget.per_job_usd"]?.value} onCommit={(v) => p.onSetting("ai.budget.per_job_usd", v)} />}
          />
        </div>
      )}
    </section>
  );
}

function AIProviders(p: AppSettingsViewProps) {
  const localOnly = Boolean(p.settings?.["ai.local_only"]?.value);
  const sendGps = Boolean(p.settings?.["ai.send_gps"]?.value);
  return (
    <section aria-labelledby="section-ai" className="flex flex-col gap-4">
      <Title id="ai">AI providers</Title>
      {!p.providers || !p.options ? (
        <div aria-label="Loading providers" className="h-64 animate-pulse rounded-lg bg-surface-1" />
      ) : (
        <>
          {keyProviders(p.providers).map(({ provider, key }) => (
            <Card key={provider}>
              <SecretField
                label={`${PROVIDER_LABEL[provider] ?? provider} API key`}
                where={key?.from_deployment ? `${storeText(key)} · a key you add here is used instead` : storeText(key)}
                last4={key?.configured ? (key.last4 ?? "????") : undefined}
                validating={p.keyChecks[provider] === "checking"}
                status={p.keyChecks[provider] === "invalid" ? "invalid" : p.keyChecks[provider] === "ok" ? "ok" : undefined}
                onSave={(v) => p.onSaveKey(provider, v)}
                onValidate={() => p.onValidateKey(provider)}
                onRemove={key?.configured && !key.from_deployment ? () => p.onRemoveKey(provider) : undefined}
                validateBlocked={localOnly ? "Local only is on: nothing is sent to check the key." : undefined}
              />
              {!key?.configured && !localOnly && (
                <p className="text-caption font-normal text-text-muted">
                  Without a key, the tasks below that use {PROVIDER_LABEL[provider] ?? provider} can't run. Analysis on this computer still works.
                </p>
              )}
            </Card>
          ))}
          <Card title="Models by task">
            {localOnly && <Banner kind="info">Local only is on: cloud and installed-app tasks are paused until you switch it off.</Banner>}
            <div role="table" aria-label="Models by task" className="flex flex-col">
              <div role="row" className="sr-only">
                <span role="columnheader">Task</span>
                <span role="columnheader">Provider</span>
                <span role="columnheader">Model</span>
                <span role="columnheader">Runs</span>
                <span role="columnheader">Reset</span>
              </div>
              {TASKS.filter((t) => p.providers![t.id]).map((t) => (
                <TaskRow key={t.id} task={t} {...p} localOnly={localOnly} />
              ))}
            </div>
            <p className="text-caption font-normal text-text-faint">Each task uses the provider and model shown. Change any row; Reset returns it to the default.</p>
          </Card>
          <div className="flex flex-col gap-2">
            <span className="text-caption text-text-muted">Privacy mode</span>
            <div role="radiogroup" aria-label="Privacy mode" onKeyDown={radioArrows} className="grid grid-cols-2 gap-3">
              <PrivacyCard
                selected={!localOnly}
                title="Hybrid"
                icon={<Cloud aria-hidden className="size-4" />}
                text="Processing stays here; the AI sees selected frames and text."
                onClick={() => p.onSetting("ai.local_only", false)}
              />
              <PrivacyCard
                selected={localOnly}
                title="Local only"
                icon={<HardDrive aria-hidden className="size-4" />}
                text="Nothing leaves this computer. Scene understanding and editing pause until you switch back."
                onClick={() => p.onSetting("ai.local_only", true)}
              />
            </div>
          </div>
          <Card title={localOnly ? "What leaves this computer in Local only" : "What leaves this computer in Hybrid"}>
            <ul className="flex flex-col gap-1.5">
              <Leaves yes={!localOnly}>Contact sheets of sampled frames</Leaves>
              <Leaves yes={!localOnly}>Transcripts and your instructions</Leaves>
              <Leaves yes={false}>Original video and photo files</Leaves>
              <Leaves yes={false}>GPS {sendGps ? "(on by default for new trips; no analysis step sends it yet)" : "(off)"}</Leaves>
              <Leaves yes={false}>API keys</Leaves>
            </ul>
          </Card>
        </>
      )}
    </section>
  );
}

function TaskRow({ task, providers, options, onProvider, localOnly }: AppSettingsViewProps & { task: { id: string; label: string }; localOnly: boolean }) {
  const cur = providers![task.id]!;
  const offered = Object.entries(options!.providers).filter(([, o]) => o.capabilities.includes(task.id));
  // The current provider is always shown, even one the options don't offer (e.g. a test one).
  const choices = offered.some(([n]) => n === cur.provider) ? offered : [[cur.provider, undefined] as const, ...offered];
  const opt = options!.providers[cur.provider];
  const [model, setModel] = useState<string | null>(null);
  const paused = localOnly && cur.mode !== "local";
  const field = "h-9 rounded-md border border-border bg-surface-3 px-2.5 text-small text-text focus-visible:outline-2 focus-visible:outline-accent disabled:opacity-50";
  return (
    <div role="row" className={cn("grid grid-cols-[1.2fr_1fr_1.2fr_160px_64px] items-center gap-3.5 border-b border-border py-3 last:border-b-0", paused && "opacity-60")}>
      <span role="rowheader" className="flex flex-col">
        <span className="text-body font-medium text-text">{task.label}</span>
        <span className="text-micro font-normal text-text-faint">From: {sourceWords(cur.source)}</span>
      </span>
      <span role="cell">
        <select
          aria-label={`${task.label}: provider`}
          value={cur.provider}
          disabled={offered.length < 2 || paused}
          onChange={(e) => {
            const next = e.target.value;
            const preset = options!.presets[next]?.[task.id];
            const fallback = options!.providers[next]?.models[0] ?? "";
            onProvider(task.id, { provider: next, model: preset ?? fallback });
          }}
          className={cn(field, "w-full")}
        >
          {choices.map(([name, o]) => (
            <option key={name} value={name} disabled={o === undefined}>
              {PROVIDER_LABEL[name] ?? name}
            </option>
          ))}
        </select>
      </span>
      <span role="cell">
        {opt?.fixed_models ? (
          <select aria-label={`${task.label}: model`} value={cur.model} disabled={paused} onChange={(e) => onProvider(task.id, { provider: cur.provider, model: e.target.value })} className={cn(field, "mono w-full")}>
            {opt.models.map((m) => (
              <option key={m} value={m}>
                {m}
              </option>
            ))}
          </select>
        ) : (
          <>
            <input
              aria-label={`${task.label}: model`}
              list={`models-${task.id}`}
              value={model ?? cur.model}
              disabled={paused}
              onChange={(e) => setModel(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && e.currentTarget.blur()}
              onBlur={() => {
                const v = (model ?? cur.model).trim();
                if (v && v !== cur.model) onProvider(task.id, { provider: cur.provider, model: v });
                setModel(null);
              }}
              className={cn(field, "mono w-full")}
            />
            <datalist id={`models-${task.id}`}>
              {(opt?.models ?? []).map((m) => (
                <option key={m} value={m} />
              ))}
            </datalist>
          </>
        )}
      </span>
      <span role="cell" className="inline-flex items-center gap-1.5 justify-self-start rounded-full border border-border bg-surface-2 px-[9px] py-[3px] text-micro font-medium whitespace-nowrap text-text-muted">
        {cur.mode === "local" ? <MonitorSmartphone aria-hidden className="size-3.5 text-info" /> : <Cloud aria-hidden className="size-3.5" />}
        {paused ? "Paused · local only" : MODE_LABEL[cur.mode]}
      </span>
      <span role="cell" className="w-14 text-right">
        {cur.source === "user" && (
          <Button size="sm" variant="ghost" onClick={() => onProvider(task.id, null)} aria-label={`Reset ${task.label}`}>
            Reset
          </Button>
        )}
      </span>
    </div>
  );
}

function PrivacyCard({ selected, title, icon, text, onClick }: { selected: boolean; title: string; icon: ReactNode; text: string; onClick: () => void }) {
  return (
    <button
      type="button"
      role="radio"
      aria-checked={selected}
      tabIndex={selected ? 0 : -1}
      onClick={onClick}
      className={cn(
        "flex flex-col gap-2 rounded-lg border-[1.5px] p-[18px] text-left text-text focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent",
        selected ? "border-accent bg-accent-soft" : "border-border bg-surface-1 hover:border-text-faint",
      )}
    >
      <span className="flex items-center gap-2.5">
        <span className={cn("flex size-[18px] items-center justify-center rounded-full border-[1.5px]", selected ? "border-accent" : "border-border")}>
          {selected && <span className="size-[9px] rounded-full bg-accent" />}
        </span>
        <span className="text-subhead font-semibold">{title}</span>
        <span className="ml-auto text-text-muted">{icon}</span>
      </span>
      <span className="text-small text-text-muted">{text}</span>
    </button>
  );
}

function Leaves({ yes, children }: { yes: boolean; children: ReactNode }) {
  return (
    <li className="flex items-center gap-2 text-small text-text">
      {yes ? <Check aria-label="Sent" className="size-4 text-use" /> : <X aria-label="Never sent" className="size-4 text-text-faint" />}
      {children}
    </li>
  );
}

const WORKER_OPTIONS = [
  { value: "0", label: "Auto" },
  { value: "2", label: "2" },
  { value: "4", label: "4" },
  { value: "8", label: "8" },
] as const;

function Processing(p: AppSettingsViewProps) {
  const hw = p.system?.hardware;
  const s = p.settings;
  const cpu = String(Number(s?.["workers.cpu"]?.value ?? 0));
  return (
    <section aria-labelledby="section-processing" className="flex flex-col gap-3">
      <Title id="processing">Processing & hardware</Title>
      <Card>
        {!p.system ? (
          <div aria-label="Loading hardware" className="h-12 animate-pulse rounded-md bg-surface-2" />
        ) : (
          <div className="flex flex-col gap-1">
            <span className="text-body text-text">
              {[hw?.cpu_model ?? hw?.machine, hw?.cpu_logical && `${hw.cpu_logical} threads`, hw?.memory_bytes && `${formatBytes(hw.memory_bytes)} memory`].filter(Boolean).join(" · ")}
            </span>
            <span className="text-small text-text-muted">
              Hardware video: {hw?.hw_encoders?.length ? hw.hw_encoders.join(", ") : "none found — renders use the software encoder"}
            </span>
          </div>
        )}
      </Card>
      {s && (
        <SettingRow
          label="Background workers"
          description={`Analysis tasks at once. Auto sizes them from this computer${p.system ? ` (now ${p.system.workers.cpu ?? "?"})` : ""}.`}
          source={src(s, "workers.cpu")}
          onReset={() => p.onSetting("workers.cpu", null)}
          control={
            <Segmented
              label="Background workers"
              value={cpu}
              onChange={(v) => p.onSetting("workers.cpu", Number(v))}
              // A count set elsewhere (mosaic config) still shows as the effective value.
              options={WORKER_OPTIONS.some((o) => o.value === cpu) ? WORKER_OPTIONS : [...WORKER_OPTIONS, { value: cpu, label: `Custom: ${cpu}` }]}
            />
          }
        />
      )}
    </section>
  );
}

function Roots(p: AppSettingsViewProps) {
  const [path, setPath] = useState("");
  const [label, setLabel] = useState("");
  return (
    <section aria-labelledby="section-roots" className="flex flex-col gap-3">
      <Title id="roots" sub="Folders on this server that people can open. Nothing outside them is visible.">
        Media roots
      </Title>
      <Card>
        {p.roots!.length === 0 ? (
          <p className="text-body text-text-muted">No media roots yet: add the folders that hold your trips.</p>
        ) : (
          <ul className="flex flex-col">
            {p.roots!.map((r) => (
              <li key={r.id} className="flex items-center gap-3 border-b border-border py-2.5 last:border-b-0">
                <span className="flex min-w-0 flex-col">
                  <span className="mono truncate text-timecode text-text">{r.path}</span>
                  <span className="text-caption font-normal text-text-faint">
                    {r.label ?? "No label"}
                    {r.source === "env" ? " · from the server's configuration" : ""}
                  </span>
                </span>
                {r.source !== "env" && (
                  <Button size="sm" variant="ghost" className="ml-auto" onClick={() => p.onRemoveRoot?.(r)} aria-label={`Remove ${r.path}`}>
                    Remove
                  </Button>
                )}
              </li>
            ))}
          </ul>
        )}
        <form
          className="flex items-end gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            if (!path.trim()) return;
            p.onAddRoot?.(path.trim(), label.trim());
            setPath("");
            setLabel("");
          }}
        >
          <TextField className="flex-1" label="Folder on the server" mono value={path} onChange={(e) => setPath(e.target.value)} placeholder="/media/travel" />
          <TextField className="w-48" label="Label (optional)" value={label} onChange={(e) => setLabel(e.target.value)} />
          <Button type="submit" disabled={!path.trim()}>
            <Plus /> Add media root
          </Button>
        </form>
      </Card>
    </section>
  );
}

function About(p: AppSettingsViewProps) {
  const ff = p.system?.ffmpeg as { version?: string; license?: string } | undefined;
  return (
    <section aria-labelledby="section-about" className="flex flex-col gap-3">
      <Title id="about">About</Title>
      <Card>
        <span className="flex items-center gap-2 text-body text-text">
          <ShieldCheck aria-hidden className="size-4 text-use" />
          MosAic {p.system?.version ?? ""}
        </span>
        {ff?.version && (
          <span className="text-small text-text-muted">
            FFmpeg {ff.version}
            {ff.license ? ` (${ff.license})` : ""}
          </span>
        )}
        <span className="text-small text-text-muted">Your footage never leaves this computer, and API keys are never shown or exported.</span>
      </Card>
    </section>
  );
}
