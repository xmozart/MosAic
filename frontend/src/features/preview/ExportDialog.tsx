import { Dialog } from "radix-ui";
import { Folder, X } from "lucide-react";
import { useId, useState } from "react";

import { ChoiceCard } from "@/components/system/ChoiceCard";
import { Button } from "@/components/ui/Button";
import { CheckboxRow } from "@/components/ui/Checkbox";
import { RadioGroup } from "@/components/ui/RadioGroup";
import { Segmented } from "@/components/ui/Segmented";
import { formatBytes } from "@/lib/format";
import { fps, formatClock } from "@/lib/time";

export type Codec = "h264" | "hevc" | "prores";
export type Resolution = "720p" | "1080p" | "1440p" | "4k";
export type Sidecar = "srt" | "report" | "edl";

/** `GET /edits/{eid}/export` (ADR 0091). */
export interface ExportOptions {
  version: number;
  duration: { frames: number; rate: string };
  rate: string;
  resolution: Resolution;
  loudness: "web" | "tv";
  presets: Record<Codec, { available: boolean; encoder: string | null; reason: string | null; bytes: Record<Resolution, number>; seconds: Record<Resolution, number | null> }>;
  save_to: { default: string; can_choose: boolean };
}

export interface ExportChoice {
  codec: Codec;
  resolution: Resolution;
  loudness: "web" | "tv";
  sidecars: Sidecar[];
  /** A folder to copy the files into (desktop); none: they stay in Exports. */
  save_to: string | null;
}

export interface ExportDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  /** Undefined while they load. */
  options: ExportOptions | undefined;
  error?: string | null;
  busy?: boolean;
  /** The desktop's folder picker; null when cancelled. */
  onChooseFolder?: () => Promise<string | null>;
  onRender: (choice: ExportChoice) => void;
}

const PRESETS: { codec: Codec; title: string; text: string }[] = [
  { codec: "h264", title: "Web", text: "H.264 MP4 · best for sharing and YouTube" },
  { codec: "hevc", title: "High quality", text: "HEVC MP4 · smaller files, same quality" },
  { codec: "prores", title: "Master", text: "ProRes 422 MOV · for further editing" },
];
const RESOLUTIONS: { value: Resolution; label: string }[] = [
  { value: "720p", label: "1280 × 720 (720p)" },
  { value: "1080p", label: "1920 × 1080 (1080p)" },
  { value: "1440p", label: "2560 × 1440 (1440p)" },
  { value: "4k", label: "3840 × 2160 (4K)" },
];
const ENCODER_NAMES: Record<string, string> = {
  h264_videotoolbox: "VideoToolbox",
  hevc_videotoolbox: "VideoToolbox",
  prores_videotoolbox: "VideoToolbox",
  h264_nvenc: "NVENC",
  hevc_nvenc: "NVENC",
  h264_qsv: "Quick Sync",
  hevc_qsv: "Quick Sync",
  h264_amf: "AMF",
  hevc_amf: "AMF",
  prores_ks: "ProRes (software)",
};

function minutes(s: number): string {
  return s < 90 ? "about a minute" : `${Math.round(s / 60)} min`;
}

/** S19 Render final (900 px): the preset, resolution and loudness, the files to add, and
 * where they go; every render conforms from the original footage. */
export function ExportDialog(p: ExportDialogProps) {
  const o = p.options;
  return (
    <Dialog.Root open={p.open} onOpenChange={p.onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-scrim" />
        <Dialog.Content
          aria-describedby={undefined}
          onOpenAutoFocus={(e) => {
            // The chosen preset, not the close button (the radio group's Tab stop).
            const chosen = (e.currentTarget as HTMLElement).querySelector<HTMLElement>('[role="radio"][aria-checked="true"]');
            if (chosen) {
              e.preventDefault();
              chosen.focus();
            }
          }}
          className="fixed top-1/2 left-1/2 z-50 flex max-h-[92vh] w-[900px] -translate-x-1/2 -translate-y-1/2 flex-col gap-4 overflow-y-auto rounded-lg border border-border bg-surface-1 p-6 shadow-[0_24px_64px_rgba(0,0,0,0.5)]"
        >
          <div className="flex items-center gap-2">
            <Dialog.Title className="text-title tracking-[-0.01em] text-text">Render final</Dialog.Title>
            <Dialog.Close asChild>
              <Button variant="secondary" size="icon" aria-label="Close" className="ml-auto size-[34px]">
                <X />
              </Button>
            </Dialog.Close>
          </div>
          {o ? <Form {...p} options={o} key={o.version} /> : <div aria-label="Loading the export options" className="h-[420px] animate-pulse rounded-lg bg-surface-2" />}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

function Form(p: ExportDialogProps & { options: ExportOptions }) {
  const o = p.options;
  const firstAvailable = PRESETS.find((x) => o.presets[x.codec].available)?.codec ?? "h264";
  const [codec, setCodec] = useState<Codec>(firstAvailable);
  const [resolution, setResolution] = useState<Resolution>(o.resolution);
  const [loudness, setLoudness] = useState<"web" | "tv">(o.loudness);
  const [sidecars, setSidecars] = useState<Sidecar[]>(["srt", "report"]);
  const [folder, setFolder] = useState<string | null>(null);
  const resId = useId();
  const rateId = useId();
  const destId = useId();
  const preset = o.presets[codec];
  const toggle = (s: Sidecar, on: boolean) => setSidecars((xs) => (on ? [...xs, s] : xs.filter((x) => x !== s)));
  const length = formatClock(o.duration.frames / fps(o.duration.rate));
  return (
    <>
      <p className="text-small text-text-muted">
        {p.title} · v{o.version} · {length}
      </p>
      <RadioGroup label="Preset" className="grid grid-cols-3 gap-3.5">
        {PRESETS.map((x) => {
          const pr = o.presets[x.codec];
          const secs = pr.seconds[resolution];
          return (
            <ChoiceCard
              key={x.codec}
              selected={codec === x.codec}
              disabled={!pr.available}
              title={x.title}
              text={x.text}
              onClick={() => setCodec(x.codec)}
              footer={
                pr.available ? (
                  <span className="mono text-timecode-sm text-text-muted">
                    ≈ {formatBytes(pr.bytes[resolution])}
                    {secs !== null ? ` · ${minutes(secs)}` : ""}
                  </span>
                ) : (
                  <span className="text-caption font-normal text-text-muted">{pr.reason}</span>
                )
              }
            />
          );
        })}
      </RadioGroup>
      <div className="grid grid-cols-3 gap-4">
        <div className="flex flex-col gap-1.5">
          <label htmlFor={resId} className="text-caption text-text-muted">
            Resolution
          </label>
          <select
            id={resId}
            value={resolution}
            onChange={(e) => setResolution(e.target.value as Resolution)}
            className="h-10 rounded-md border border-border bg-surface-3 px-3 text-body text-text focus-visible:outline-2 focus-visible:outline-accent"
          >
            {RESOLUTIONS.map((r) => (
              <option key={r.value} value={r.value}>
                {r.label}
              </option>
            ))}
          </select>
        </div>
        <div className="flex flex-col gap-1.5">
          <label htmlFor={rateId} className="text-caption text-text-muted">
            Frame rate
          </label>
          <input id={rateId} readOnly value={(Math.round(fps(o.rate) * 100) / 100).toString()} title="The edit's own frame rate" className="mono h-10 rounded-md border border-border bg-surface-3 px-3 text-body text-text-muted" />
        </div>
        <div className="flex flex-col gap-1.5">
          <span className="text-caption text-text-muted">Loudness</span>
          <Segmented<"web" | "tv">
            label="Loudness"
            value={loudness}
            onChange={setLoudness}
            options={[
              { value: "web", label: "Web (−14 LUFS)" },
              { value: "tv", label: "TV (−23 LUFS)" },
            ]}
          />
        </div>
      </div>
      <div className="flex flex-col gap-2">
        <span className="text-caption text-text-muted">Also include</span>
        <div className="flex flex-col gap-3">
          <CheckboxRow label="Captions file (SRT)" hint="From the transcript" checked={sidecars.includes("srt")} onChange={(on) => toggle("srt", on)} />
          <CheckboxRow label="Selection report" hint="Why each shot was chosen, and what was left out" checked={sidecars.includes("report")} onChange={(on) => toggle("report", on)} />
          <CheckboxRow label="Edit data (JSON)" checked={sidecars.includes("edl")} onChange={(on) => toggle("edl", on)} />
          <div className="flex items-center gap-2.5">
            <CheckboxRow label="Final Cut Pro / DaVinci Resolve timeline" checked={false} onChange={() => {}} disabled />
            <span className="inline-flex items-center rounded-full border border-border bg-surface-2 px-[9px] py-[3px] text-micro font-medium text-text-muted">Coming later</span>
          </div>
        </div>
      </div>
      <div className="flex flex-col gap-1.5">
        <label htmlFor={destId} className="text-caption text-text-muted">
          Save to
        </label>
        <div className="flex gap-2">
          <div className="relative flex-1">
            <Folder aria-hidden className="absolute top-1/2 left-3 size-4 -translate-y-1/2 text-text-faint" />
            <input id={destId} readOnly value={folder ?? o.save_to.default} className="mono h-10 w-full truncate rounded-md border border-border bg-surface-3 pr-3 pl-9 text-timecode text-text" />
          </div>
          {o.save_to.can_choose && p.onChooseFolder ? (
            <>
              <Button
                onClick={async () => {
                  const chosen = await p.onChooseFolder!();
                  if (chosen) setFolder(chosen);
                }}
              >
                Choose…
              </Button>
              {folder && (
                <Button variant="ghost" onClick={() => setFolder(null)}>
                  Reset
                </Button>
              )}
            </>
          ) : null}
        </div>
        {!o.save_to.can_choose && <span className="text-caption font-normal text-text-faint">Download the files from Exports when they're ready.</span>}
        {folder && <span className="text-caption font-normal text-text-faint">A copy goes here too; nothing already in the folder is replaced.</span>}
      </div>
      {p.error && (
        <p role="alert" className="text-small text-reject">
          {p.error}
        </p>
      )}
      <div className="flex items-center gap-2">
        <span className="text-caption font-normal text-text-faint">
          Renders from your original footage{preset.encoder ? ` · ${ENCODER_NAMES[preset.encoder] ?? preset.encoder}` : ""}
        </span>
        <span className="flex-1" />
        <Dialog.Close asChild>
          <Button variant="ghost">Cancel</Button>
        </Dialog.Close>
        <Button variant="primary" disabled={p.busy || !preset.available} onClick={() => p.onRender({ codec, resolution, loudness, sidecars, save_to: folder })}>
          Render
        </Button>
      </div>
    </>
  );
}
