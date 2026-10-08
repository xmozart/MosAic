import { Clock, Pencil, Trash2 } from "lucide-react";
import { Switch } from "radix-ui";
import { useState, type ReactNode } from "react";

import { PlacementBadge, type Placement } from "@/components/system/PlacementBadge";
import { SectionNav } from "@/components/system/SectionNav";
import { SettingRow, type SettingSource } from "@/components/system/SettingRow";
import { StorageBreakdown } from "@/components/system/StorageBreakdown";
import { Button } from "@/components/ui/Button";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { Segmented } from "@/components/ui/Segmented";
import { TextField } from "@/components/ui/TextField";
import type { Settings } from "@/features/analysis/model";
import type { TripContext } from "@/features/context/model";
import { formatOffset } from "@/lib/clock";
import { formatBytes, formatDateRange, plural } from "@/lib/format";

import { SECTIONS, type DeviceSummary, type StorageData } from "./model";

export interface ProjectSettingsViewProps {
  name: string;
  folder: string;
  placement: Placement;
  readOnly?: boolean;
  onRename: (name: string) => void;
  settings: Settings | undefined;
  onSetting: (key: string, value: unknown) => void;
  onAnalysisSetup: () => void;
  devices: DeviceSummary[] | undefined;
  onCheckClocks: () => void;
  context: TripContext | undefined;
  onEditContext: () => void;
  storage: StorageData | undefined;
  clearing?: boolean;
  onClear: () => void;
  removing?: boolean;
  onRemove: (confirmName: string) => void;
  /** Opens a confirmation at first render (stories of S21's two dialog states). */
  initialDialog?: "clear" | "remove";
}

/** S21 Project settings: one column of sections beside the section nav. Presentational. */
export function ProjectSettingsView(p: ProjectSettingsViewProps) {
  const [active, setActive] = useState("general");
  const go = (id: string) => {
    setActive(id);
    document.getElementById(`section-${id}`)?.scrollIntoView({ behavior: "smooth", block: "start" });
  };
  return (
    <div className="flex min-h-0 flex-1">
      <SectionNav title="Project settings" sections={SECTIONS} active={active} onSelect={go} />
      <div className="min-w-0 flex-1 overflow-y-auto px-9 py-7">
        <div className="flex max-w-[720px] flex-col gap-10">
          <General {...p} />
          <Analysis {...p} />
          <Devices {...p} />
          <Context {...p} />
          <Storage {...p} />
          <Danger {...p} />
        </div>
      </div>
    </div>
  );
}

function SectionTitle({ id, children, sub }: { id: string; children: ReactNode; sub?: ReactNode }) {
  return (
    <div className="flex flex-col gap-1">
      <h2 id={`section-${id}`} className="scroll-mt-6 text-title tracking-[-0.01em] text-text">
        {children}
      </h2>
      {sub && <p className="text-body text-text-muted">{sub}</p>}
    </div>
  );
}

function Card({ children, danger }: { children: ReactNode; danger?: boolean }) {
  return <div className={danger ? "flex flex-col gap-2 rounded-lg border border-reject bg-surface-1 p-[18px]" : "flex flex-col gap-3.5 rounded-lg border border-border bg-surface-1 p-[22px]"}>{children}</div>;
}

function General(p: ProjectSettingsViewProps) {
  const [draft, setDraft] = useState<string | null>(null); // null: showing the saved name
  const name = draft ?? p.name;
  const commit = () => {
    const v = name.trim();
    if (v && v !== p.name) p.onRename(v);
    setDraft(null);
  };
  return (
    <section aria-labelledby="section-general" className="flex flex-col gap-4">
      <SectionTitle id="general">General</SectionTitle>
      <Card>
        <TextField
          label="Name"
          value={name}
          maxLength={120}
          disabled={p.readOnly}
          icon={<Pencil />}
          onChange={(e) => setDraft(e.target.value)}
          onBlur={commit}
          onKeyDown={(e) => {
            if (e.key === "Enter") e.currentTarget.blur();
            if (e.key === "Escape") setDraft(null);
          }}
          hint="Only MosAic's name for the trip; the folder keeps its own."
        />
        <div className="flex flex-col gap-1.5">
          <span className="text-caption text-text-muted">Folder</span>
          <span className="flex items-center gap-2">
            <span className="mono min-w-0 truncate text-timecode text-text">{p.folder}</span>
            <PlacementBadge placement={p.placement} />
          </span>
        </div>
      </Card>
    </section>
  );
}

const MODE_OPTIONS = [
  { value: "quick", label: "Quick" },
  { value: "balanced", label: "Balanced" },
  { value: "thorough", label: "Thorough" },
] as const;

function Analysis(p: ProjectSettingsViewProps) {
  const s = p.settings;
  const src = (k: string): SettingSource => (s?.[k]?.source ?? "default") as SettingSource;
  const stored = s?.["analysis.cost_limit_usd"]?.value;
  const [draft, setDraft] = useState<string | null>(null);
  const limit = draft ?? (stored == null ? "" : String(stored));
  return (
    <section aria-labelledby="section-analysis" className="flex flex-col gap-2">
      <SectionTitle id="analysis" sub="How this trip is analyzed. Each row says where its value comes from; Reset returns it to your preference or the default.">
        Analysis
      </SectionTitle>
      {!s ? (
        <div aria-label="Loading settings" className="h-40 animate-pulse rounded-lg bg-surface-1" />
      ) : (
        <div className="flex flex-col">
          <SettingRow
            label="Analysis mode"
            description="The default for the next analysis run."
            source={src("analysis.mode")}
            onReset={p.readOnly ? undefined : () => p.onSetting("analysis.mode", null)}
            control={
              <Segmented
                label="Analysis mode"
                disabled={p.readOnly}
                value={MODE_OPTIONS.some((m) => m.value === s["analysis.mode"]?.value) ? (s["analysis.mode"]?.value as string) : undefined}
                options={MODE_OPTIONS}
                onChange={(v) => !p.readOnly && p.onSetting("analysis.mode", v)}
              />
            }
          />
          <SettingRow
            label="AI cost limit per run"
            description="An analysis pauses here and asks before it spends more."
            source={src("analysis.cost_limit_usd")}
            onReset={p.readOnly ? undefined : () => p.onSetting("analysis.cost_limit_usd", null)}
            control={
              <span className="relative">
                <span aria-hidden className="pointer-events-none absolute top-1/2 left-3 -translate-y-1/2 text-body text-text-faint">$</span>
                <input
                  aria-label="AI cost limit in dollars"
                  type="number"
                  min={0}
                  step={1}
                  value={limit}
                  disabled={p.readOnly}
                  placeholder="No limit"
                  onChange={(e) => setDraft(e.target.value)}
                  onBlur={() => {
                    const v = limit.trim() === "" ? null : Number(limit);
                    if ((v === null || (Number.isFinite(v) && v >= 0)) && v !== (stored ?? null)) p.onSetting("analysis.cost_limit_usd", v);
                    setDraft(null);
                  }}
                  className="mono h-10 w-32 rounded-md border border-border bg-surface-3 pr-3 pl-7 text-timecode text-text focus-visible:outline-2 focus-visible:outline-accent"
                />
              </span>
            }
          />
          <SettingRow
            label="Use GPS for analysis"
            description="Location stays on this computer. No analysis step uses it yet."
            source={src("ai.send_gps")}
            onReset={p.readOnly ? undefined : () => p.onSetting("ai.send_gps", null)}
            control={
              <Switch.Root
                aria-label="Use GPS for analysis"
                checked={Boolean(s["ai.send_gps"]?.value)}
                disabled={p.readOnly}
                onCheckedChange={(on) => p.onSetting("ai.send_gps", on)}
                className="relative h-[22px] w-[38px] shrink-0 rounded-full border border-border bg-surface-3 transition-colors duration-150 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:opacity-50 data-[state=checked]:border-accent data-[state=checked]:bg-accent"
              >
                <Switch.Thumb className="block size-4 translate-x-[2px] rounded-full bg-text transition-transform duration-150 data-[state=checked]:translate-x-[18px] data-[state=checked]:bg-accent-fg" />
              </Switch.Root>
            }
          />
          <Button variant="ghost" size="sm" className="mt-2 self-start" onClick={p.onAnalysisSetup}>
            More analysis settings…
          </Button>
        </div>
      )}
    </section>
  );
}

function Devices(p: ProjectSettingsViewProps) {
  return (
    <section aria-labelledby="section-devices" className="flex flex-col gap-4">
      <SectionTitle id="devices" sub="The cameras in this trip, their clock corrections and color LUTs.">
        Devices
      </SectionTitle>
      <Card>
        {!p.devices ? (
          <div aria-label="Loading devices" className="h-24 animate-pulse rounded-md bg-surface-2" />
        ) : p.devices.length === 0 ? (
          <p className="text-body text-text-muted">No cameras yet: they appear once the folder is scanned.</p>
        ) : (
          <ul className="flex flex-col">
            {p.devices.map((d) => (
              <li key={d.id} className="flex items-center gap-3 border-b border-border py-2.5 last:border-b-0">
                <span className="flex min-w-0 flex-col">
                  <span className="truncate text-body text-text">{d.label ?? ([d.make, d.model].filter(Boolean).join(" ") || "Unknown camera")}</span>
                  <span className="text-caption font-normal text-text-faint">
                    {plural(d.assets, "clip")}
                    {d.lut_path ? ` · LUT ${d.lut_path.split("/").at(-1)}` : ""}
                  </span>
                </span>
                <span className="mono ml-auto text-timecode text-text-muted">{d.clock_offset_ms ? `Clock ${formatOffset(d.clock_offset_ms)}` : "Clock as recorded"}</span>
              </li>
            ))}
          </ul>
        )}
        <Button className="self-start" onClick={p.onCheckClocks} disabled={p.readOnly || !p.devices?.length}>
          <Clock /> Check camera clocks…
        </Button>
      </Card>
    </section>
  );
}

function Context({ context: c, onEditContext }: ProjectSettingsViewProps) {
  const days = c?.days ?? [];
  const range = days.length ? formatDateRange(days[0]!.date, days.at(-1)!.date) : null;
  const facts = c
    ? [range && `${range}`, days.length && plural(days.length, "day"), c.people.length && plural(c.people.length, "person", "people"), c.must_include.length && `${c.must_include.length} must-include`]
        .filter(Boolean)
        .join(" · ")
    : "";
  return (
    <section aria-labelledby="section-context" className="flex flex-col gap-4">
      <SectionTitle id="context" sub="What the editor knows about the trip: names, days, people, what to include or avoid.">
        Trip context
      </SectionTitle>
      <Card>
        {!c ? (
          <div aria-label="Loading trip context" className="h-12 animate-pulse rounded-md bg-surface-2" />
        ) : (
          <div className="flex flex-col gap-0.5">
            <span className="text-body text-text">{c.trip_name || "No trip context yet"}</span>
            {facts && <span className="text-caption font-normal text-text-muted">{facts}</span>}
          </div>
        )}
        <Button className="self-start" onClick={onEditContext}>
          Edit trip context
        </Button>
      </Card>
    </section>
  );
}

function Storage(p: ProjectSettingsViewProps) {
  const [confirm, setConfirm] = useState(p.initialDialog === "clear");
  const st = p.storage;
  const frees = st ? formatBytes(st.regenerable_bytes) : "";
  return (
    <section aria-labelledby="section-storage" className="flex flex-col gap-4">
      <SectionTitle id="storage" sub={st ? <>MosAic files for this project live in <span className="mono text-timecode">{st.folder}</span>.</> : undefined}>
        Storage
      </SectionTitle>
      <Card>
        {!st ? (
          <div aria-label="Loading storage" className="h-40 animate-pulse rounded-md bg-surface-2" />
        ) : (
          <>
            <div className="flex items-baseline gap-2">
              <span className="text-title tracking-[-0.01em] text-text">{formatBytes(st.total_bytes)}</span>
              <span className="text-small text-text-muted">used by MosAic</span>
            </div>
            <StorageBreakdown parts={st.groups.map((g) => ({ label: g.label, bytes: g.bytes, size: formatBytes(g.bytes), regenerable: g.regenerable }))} />
            <div className="flex items-center gap-3">
              <Button onClick={() => setConfirm(true)} disabled={p.readOnly || p.clearing || st.regenerable_bytes === 0}>
                <Trash2 /> {p.clearing ? "Clearing…" : "Clear regenerable files"}
              </Button>
              <span className="text-caption font-normal text-text-faint">{p.clearing ? "Previews are being removed." : st.regenerable_bytes ? `Frees ${frees}` : "Nothing to clear"}</span>
            </div>
          </>
        )}
      </Card>
      <ConfirmDialog
        open={confirm}
        onOpenChange={setConfirm}
        title="Clear regenerable files?"
        body={
          <div className="flex flex-col gap-2 text-body text-text-muted">
            <p>
              This frees <span className="mono text-timecode text-text">{frees}</span>. Previews are made again the next time you analyze this trip; until then, clips and edits can't play.
            </p>
            <p>Kept: ratings, notes and decisions, the AI analysis, frames and contact sheets, edits and renders.</p>
          </div>
        }
        actions={[
          { label: "Cancel", variant: "ghost", onClick: () => setConfirm(false) },
          {
            label: `Clear ${frees}`,
            variant: "primary",
            onClick: () => {
              setConfirm(false);
              p.onClear();
            },
          },
        ]}
      />
    </section>
  );
}

function Danger(p: ProjectSettingsViewProps) {
  const [open, setOpen] = useState(p.initialDialog === "remove");
  const [typed, setTyped] = useState("");
  return (
    <section aria-labelledby="section-danger" className="flex flex-col gap-2">
      <h2 id="section-danger" className="scroll-mt-6 text-caption font-semibold text-reject">
        Danger zone
      </h2>
      <Card danger>
        <div className="flex items-center gap-3">
          <div className="flex flex-col gap-[3px]">
            <span className="text-body font-medium text-text">Remove MosAic data from this folder</span>
            <span className="text-caption font-normal text-text-muted">Deletes the MosAic folder and project file. Your original footage is untouched.</span>
          </div>
          <Button variant="danger" className="ml-auto" disabled={p.readOnly || p.removing} onClick={() => setOpen(true)}>
            Remove…
          </Button>
        </div>
      </Card>
      <ConfirmDialog
        open={open}
        onOpenChange={(o) => {
          setOpen(o);
          if (!o) setTyped("");
        }}
        title="Remove MosAic data?"
        body={
          <div className="flex flex-col gap-3 text-body text-text-muted">
            <p>This deletes the analysis, decisions, edits and renders for “{p.name}”. Your original footage stays exactly as it is.</p>
            <TextField label={`Type “${p.name}” to confirm`} value={typed} onChange={(e) => setTyped(e.target.value)} autoFocus />
          </div>
        }
        actions={[
          { label: "Cancel", variant: "ghost", onClick: () => setOpen(false) },
          {
            label: "Remove",
            variant: "danger",
            disabled: !p.name || typed.trim() !== p.name,
            onClick: () => {
              setOpen(false);
              p.onRemove(typed.trim());
              setTyped("");
            },
          },
        ]}
      />
    </section>
  );
}
