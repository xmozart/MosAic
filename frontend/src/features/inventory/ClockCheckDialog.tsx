import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, X } from "lucide-react";
import { Dialog } from "radix-ui";
import { useState } from "react";

import { api } from "@/api/client";
import { ClockOffsetRow, type ClockChoice } from "@/components/system/ClockOffsetRow";
import { Button } from "@/components/ui/Button";
import { HOUR_MS, MINUTE_MS, formatOffset, shortStamp, verdict } from "@/lib/clock";
import { media } from "@/lib/media";
import { useToasts } from "@/lib/toasts";

/** A row of `GET /projects/{pid}/devices` (ADR 0027). */
export interface DeviceRow {
  id: number;
  label: string | null;
  make: string | null;
  model: string | null;
  assets: number;
  clock_offset_ms: number;
  suggestion: {
    offset_ms: number;
    verdict: string;
    applied: boolean;
    reference_device_id: number;
    pairs: number;
    evidence: { device_time: string; reference_time: string; device_sample: number | null; reference_sample: number | null }[];
  } | null;
}

export type ClockChange = { id: number; accept_suggestion: true } | { id: number; clock_offset_ms: number };

const MAX_MS = 7 * 24 * HOUR_MS; // the API's limit

const name = (d: DeviceRow) => d.label || [d.make, d.model].filter(Boolean).join(" ") || `Camera ${d.id}`;
const short = (d: DeviceRow) => name(d).split(" ")[0]!;

interface Draft {
  offset: number;
  choice: ClockChoice;
}

/** The S6 body: suspect cameras with evidence, cameras without a suggestion (manual
 * stepper), and the consistent ones in one line. Presentational (stories, tests). */
export function ClockCheckBody({
  devices,
  frameUrl,
  busy,
  onApply,
  onSkip,
}: {
  devices: DeviceRow[];
  frameUrl: (sampleId: number) => string;
  busy?: boolean;
  onApply: (changes: ClockChange[]) => void;
  onSkip: () => void;
}) {
  const used = devices.filter((d) => d.assets > 0);
  const refs = new Set(used.flatMap((d) => (d.suggestion ? [d.suggestion.reference_device_id] : [])));
  const suspect = used.filter((d) => d.suggestion && !d.suggestion.applied);
  const consistent = used.filter((d) => d.suggestion?.applied || refs.has(d.id));
  const unknown = used.length > 1 ? used.filter((d) => !d.suggestion && !refs.has(d.id)) : [];
  const byId = Object.fromEntries(used.map((d) => [d.id, d]));
  const [draft, setDraft] = useState<Record<number, Draft>>(() =>
    Object.fromEntries(
      [...suspect, ...unknown].map((d) => [
        d.id,
        d.suggestion && !d.suggestion.applied
          ? { offset: d.suggestion.offset_ms, choice: "accept" as const }
          : { offset: d.clock_offset_ms, choice: "leave" as const },
      ]),
    ),
  );
  const set = (d: DeviceRow, next: Partial<Draft>) => setDraft((s) => ({ ...s, [d.id]: { ...s[d.id]!, ...next } }));
  const choose = (d: DeviceRow, choice: ClockChoice) => {
    if (choice === "accept" && d.suggestion) set(d, { choice, offset: d.suggestion.offset_ms });
    else if (choice === "leave") set(d, { choice, offset: d.clock_offset_ms });
    else set(d, { choice });
  };
  const step = (d: DeviceRow, dir: -1 | 1, fine: boolean) => {
    const cur = draft[d.id]!.offset;
    const offset = Math.max(-MAX_MS, Math.min(MAX_MS, cur + dir * (fine ? MINUTE_MS : HOUR_MS)));
    set(d, { offset, choice: "adjust" });
  };
  const changes: ClockChange[] = Object.entries(draft).flatMap(([id, v]): ClockChange[] => {
    const d = byId[Number(id)]!;
    if (v.choice === "accept") return [{ id: d.id, accept_suggestion: true }];
    if (v.choice === "adjust" && v.offset !== d.clock_offset_ms) return [{ id: d.id, clock_offset_ms: v.offset }];
    return [];
  });
  const allFine = suspect.length === 0 && unknown.length === 0;

  return (
    <div className="flex flex-col gap-4">
      <p className="text-body text-text-muted">Cameras often have the wrong time. We compared shots of the same moments to suggest a fix.</p>
      <div className="flex max-h-[60vh] flex-col gap-4 overflow-y-auto">
        {suspect.map((d) => {
          const sg = d.suggestion!;
          const e = sg.evidence[0];
          const ref = byId[sg.reference_device_id];
          return (
            <ClockOffsetRow
              key={d.id}
              device={name(d)}
              summary={`Appears ${verdict(sg.offset_ms - d.clock_offset_ms)}`}
              offset={formatOffset(draft[d.id]!.offset)}
              evidence={
                e && {
                  reference: `${ref ? short(ref) : "Reference"} · ${shortStamp(e.reference_time)}`,
                  device: `${short(d)} · ${shortStamp(e.device_time)}`,
                  frames: [e.reference_sample ? frameUrl(e.reference_sample) : null, e.device_sample ? frameUrl(e.device_sample) : null],
                  moment: sg.pairs > 1 ? `${sg.pairs} matching moments agree.` : undefined,
                }
              }
              choice={draft[d.id]!.choice}
              onChoice={(c) => choose(d, c)}
              onStep={(dir, fine) => step(d, dir, fine)}
            />
          );
        })}
        {unknown.map((d) => (
          <ClockOffsetRow
            key={d.id}
            device={name(d)}
            summary="No suggestion yet: cameras are compared during analysis. You can set its clock by hand."
            offset={formatOffset(draft[d.id]!.offset)}
            choice={draft[d.id]!.choice}
            onChoice={(c) => choose(d, c)}
            onStep={(dir, fine) => step(d, dir, fine)}
          />
        ))}
      </div>
      {consistent.length > 0 && (
        <p className="flex items-center gap-2 text-small text-text-muted">
          <Check aria-hidden className="size-4 text-use" />
          {allFine && consistent.length === used.length
            ? "All cameras look consistent."
            : `${listNames(consistent.map(name))} ${consistent.length === 1 ? "looks" : "look"} consistent.`}
        </p>
      )}
      <div className="flex items-center gap-2">
        {allFine ? (
          <Button variant="primary" className="ml-auto" onClick={onSkip}>
            Continue
          </Button>
        ) : (
          <>
            <Button variant="ghost" onClick={onSkip}>
              Skip — I'll fix it later
            </Button>
            <Button variant="primary" className="ml-auto" disabled={busy} onClick={() => (changes.length ? onApply(changes) : onSkip())}>
              Apply
            </Button>
          </>
        )}
      </div>
    </div>
  );
}

function listNames(names: string[]): string {
  return names.length > 1 ? `${names.slice(0, -1).join(", ")} and ${names.at(-1)}` : (names[0] ?? "");
}

/** S6 Clock check: 880 px dialog over S5 (`/devices`, `PUT /devices`). Offsets regroup
 * days at once; nothing is re-analysed. */
export function ClockCheckDialog({ pid, open, onOpenChange }: { pid: string; open: boolean; onOpenChange: (o: boolean) => void }) {
  const qc = useQueryClient();
  const toast = useToasts((s) => s.push);
  const devices = useQuery({
    queryKey: ["devices", pid],
    enabled: open,
    queryFn: async () => (await api.GET("/api/projects/{pid}/devices", { params: { path: { pid } } })).data as { devices: DeviceRow[] } | undefined,
  });
  const apply = useMutation({
    mutationFn: async (changes: ClockChange[]) => {
      const body = {
        devices: changes.map((c) => ({ accept_suggestion: false, clear_lut: false, ...c })),
      };
      const { data, error } = await api.PUT("/api/projects/{pid}/devices", { params: { path: { pid } }, body });
      if (error) throw new Error("the clocks were not updated");
      return data;
    },
    onSuccess: () => {
      onOpenChange(false);
      toast({ kind: "success", message: "Clocks updated. Days are regrouped; nothing is re-analysed." });
      void qc.invalidateQueries({ queryKey: ["inventory", pid] });
      void qc.invalidateQueries({ queryKey: ["devices", pid] });
    },
    onError: () => toast({ kind: "error", message: "Couldn't update the clocks. Try again." }),
  });
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-scrim" />
        <Dialog.Content
          aria-describedby={undefined}
          className="fixed top-1/2 left-1/2 z-50 flex w-[880px] -translate-x-1/2 -translate-y-1/2 flex-col gap-4 rounded-[16px] border border-border bg-surface-1 p-6 shadow-[0_24px_64px_rgba(0,0,0,0.5)]"
        >
          <div className="flex items-center gap-2">
            <Dialog.Title className="text-title text-text">Clock check</Dialog.Title>
            <Dialog.Close asChild>
              <Button variant="secondary" size="icon" aria-label="Close" className="ml-auto size-[34px]">
                <X />
              </Button>
            </Dialog.Close>
          </div>
          {devices.data ? (
            <ClockCheckBody
              key={devices.dataUpdatedAt}
              devices={devices.data.devices}
              frameUrl={(sid) => media.frame(pid, sid)}
              busy={apply.isPending}
              onApply={(c) => apply.mutate(c)}
              onSkip={() => onOpenChange(false)}
            />
          ) : (
            <div aria-label="Loading" className="h-40 animate-pulse rounded-lg bg-surface-2" />
          )}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
