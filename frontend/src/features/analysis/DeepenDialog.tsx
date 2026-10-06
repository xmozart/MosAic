import { useMutation, useQuery } from "@tanstack/react-query";
import { X } from "lucide-react";
import { Dialog } from "radix-ui";
import { useState } from "react";
import { useNavigate } from "react-router";

import { api } from "@/api/client";
import { Button } from "@/components/ui/Button";
import { Segmented } from "@/components/ui/Segmented";
import { formatCost, formatWall, type Estimate } from "@/lib/estimate";
import { plural } from "@/lib/format";
import { useToasts } from "@/lib/toasts";

export type DeepenScopeKind = "trip" | "days" | "selection";
export type DeepenTarget = "balanced" | "thorough";

export interface DeepenDay {
  n: number; // trip day, from 1
  place: string | null;
  clips: number;
}

export interface DeepenBodyProps {
  days: DeepenDay[];
  selectionSize: number; // segments selected in the Library (0: none)
  scope: DeepenScopeKind;
  onScope: (s: DeepenScopeKind) => void;
  picked: ReadonlySet<number>;
  onToggleDay: (n: number) => void;
  target: DeepenTarget;
  onTarget: (t: DeepenTarget) => void;
  estimate: Estimate | undefined;
  estimating: boolean;
  starting: boolean;
  onStart: () => void;
  onCancel: () => void;
}

/** S25 body: scope, day checklist with clip counts, target and estimate. Presentational. */
export function DeepenBody(p: DeepenBodyProps) {
  const nothing = (p.scope === "days" && p.picked.size === 0) || (p.scope === "selection" && p.selectionSize === 0);
  return (
    <div className="flex flex-col gap-4">
      <p className="text-small text-text-muted">Look closer at the days that matter. Everything done so far is reused.</p>
      <div className="flex flex-col gap-2">
        <span className="text-caption text-text-muted">Scope</span>
        <Segmented
          label="Scope"
          className="self-start"
          value={p.scope}
          onChange={p.onScope}
          options={[
            { value: "trip", label: "Whole trip" },
            { value: "days", label: "Selected days" },
            { value: "selection", label: "Current selection" },
          ]}
        />
        {p.scope === "selection" && p.selectionSize === 0 && (
          <p className="text-caption font-normal text-text-muted">Select clips in the Library first, then choose Deepen analysis.</p>
        )}
        {p.scope === "selection" && p.selectionSize > 0 && (
          <p className="text-caption font-normal text-text-muted">{plural(p.selectionSize, "selected moment")}</p>
        )}
      </div>
      {p.scope === "days" && (
        <fieldset className="flex max-h-60 flex-col gap-0.5 overflow-y-auto">
          <legend className="sr-only">Days</legend>
          {p.days.length === 0 && <p className="text-small text-text-muted">No clips with capture dates yet, so there are no days to pick.</p>}
          {p.days.map((d) => (
            <label key={d.n} className="flex cursor-pointer items-center gap-3 rounded-md px-2.5 py-2 hover:bg-surface-2">
              <input
                type="checkbox"
                checked={p.picked.has(d.n)}
                onChange={() => p.onToggleDay(d.n)}
                className="size-4 accent-accent focus-visible:outline-2 focus-visible:outline-accent"
              />
              <span className="flex-1 text-small text-text">
                Day {d.n}
                {d.place ? ` · ${d.place}` : ""}
              </span>
              <span className="mono text-timecode-sm text-text-muted">{plural(d.clips, "clip")}</span>
            </label>
          ))}
        </fieldset>
      )}
      <div className="flex flex-col gap-2">
        <span className="text-caption text-text-muted">Target</span>
        <Segmented
          label="Target"
          className="self-start"
          value={p.target}
          onChange={p.onTarget}
          options={[
            { value: "balanced", label: "Balanced" },
            { value: "thorough", label: "Thorough" },
          ]}
        />
      </div>
      <div className="flex flex-col gap-1 rounded-lg border border-border bg-surface-2 p-4">
        <span className="text-caption text-text-muted">Estimate</span>
        {nothing ? (
          <span className="text-small text-text-muted">Choose what to deepen.</span>
        ) : p.estimating || !p.estimate ? (
          <span role="status" className="block h-[18px] w-1/2 animate-pulse rounded-sm bg-surface-3">
            <span className="sr-only">Estimating</span>
          </span>
        ) : (
          <>
            <span className="mono text-timecode text-text">
              {`${formatWall(p.estimate.wall_seconds)} · ${formatCost(p.estimate.cost_usd)}`}
            </span>
            <span className="text-caption font-normal text-text-muted">
              {plural(p.estimate.videos, "clip") + (p.estimate.days ? ` · ${plural(p.estimate.days, "day")}` : "")}
            </span>
          </>
        )}
      </div>
      <div className="flex justify-end gap-2">
        <Button variant="ghost" onClick={p.onCancel}>
          Cancel
        </Button>
        <Button variant="primary" disabled={nothing || p.starting || !p.estimate} onClick={p.onStart}>
          Start
        </Button>
      </div>
    </div>
  );
}

function scopeQuery(scope: DeepenScopeKind, days: number[], selection: number[]): string {
  if (scope === "days") return `days:${days.join(",")}`;
  if (scope === "selection") return `selection:${selection.join(",")}`;
  return "trip";
}

/** S25 Deepen analysis (560 px dialog): `/analysis/estimate?scope=`, `POST /analysis-runs`. */
export function DeepenDialog({ pid, open, onClose, selection = [] }: { pid: string; open: boolean; onClose: () => void; selection?: number[] }) {
  const navigate = useNavigate();
  const toast = useToasts((s) => s.push);
  const [scope, setScope] = useState<DeepenScopeKind>(selection.length ? "selection" : "days");
  const [picked, setPicked] = useState<Set<number>>(new Set());
  const [target, setTarget] = useState<DeepenTarget>("thorough");
  const inventory = useQuery({
    queryKey: ["inventory", pid],
    enabled: open,
    queryFn: async () => (await api.GET("/api/projects/{pid}/inventory", { params: { path: { pid } } })).data as unknown as {
      days: { date: string; n: number | null; clips?: number }[];
    },
  });
  const context = useQuery({
    queryKey: ["trip-context", pid],
    enabled: open,
    queryFn: async () =>
      (await api.GET("/api/projects/{pid}/trip-context", { params: { path: { pid } } })).data as unknown as { days: { date: string; place: string }[] },
  });
  const raw = inventory.data?.days ?? [];
  const places = new Map((context.data?.days ?? []).map((d) => [d.date, d.place]));
  const days: DeepenDay[] = raw
    .filter((d) => (d.clips ?? 0) > 0 && d.n !== null)
    // The server's day number: the one deepening and the editor use (ADR 0041).
    .map((d) => ({ n: d.n!, place: places.get(d.date) || null, clips: d.clips ?? 0 }));
  const chosen = [...picked].sort((a, b) => a - b);
  const empty = (scope === "days" && !chosen.length) || (scope === "selection" && !selection.length);
  const q = scopeQuery(scope, chosen, selection);
  const estimate = useQuery({
    queryKey: ["estimate", pid, target, q],
    enabled: open && !empty,
    queryFn: async () =>
      (await api.GET("/api/projects/{pid}/analysis/estimate", { params: { path: { pid }, query: { mode: target, scope: q } } })).data as unknown as Estimate,
  });
  const start = useMutation({
    mutationFn: async () => {
      const body =
        scope === "days"
          ? { kind: "days" as const, days: chosen }
          : scope === "selection"
            ? { kind: "selection" as const, segment_ids: selection }
            : { kind: "trip" as const };
      const { data, error } = await api.POST("/api/projects/{pid}/analysis-runs", {
        params: { path: { pid } },
        body: { mode: target, scope: { days: [], segment_ids: [], ...body } },
      });
      if (error || !data) throw new Error("run");
      return (data as { job_id: number | null }).job_id;
    },
    onSuccess: (job) => {
      onClose();
      if (job === null) toast({ kind: "info", message: "Nothing to add: that part of the trip already has this depth." });
      else navigate(`/p/${pid}/analysis?job=${job}`);
    },
    onError: () => toast({ kind: "error", message: "Couldn't start deepening. Try again." }),
  });
  return (
    <Dialog.Root open={open} onOpenChange={(o) => !o && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-scrim" />
        <Dialog.Content
          aria-describedby={undefined}
          className="fixed top-1/2 left-1/2 z-50 flex w-[560px] -translate-x-1/2 -translate-y-1/2 flex-col gap-4 rounded-[16px] border border-border bg-surface-1 p-6 shadow-[0_24px_64px_rgba(0,0,0,0.5)]"
        >
          <div className="flex items-center gap-2">
            <Dialog.Title className="text-heading text-text">Deepen analysis</Dialog.Title>
            <Dialog.Close asChild>
              <Button size="icon" aria-label="Close" className="ml-auto size-[34px]">
                <X />
              </Button>
            </Dialog.Close>
          </div>
          <DeepenBody
            days={days}
            selectionSize={selection.length}
            scope={scope}
            onScope={setScope}
            picked={picked}
            onToggleDay={(n) =>
              setPicked((s) => {
                const next = new Set(s);
                if (next.has(n)) next.delete(n);
                else next.add(n);
                return next;
              })
            }
            target={target}
            onTarget={setTarget}
            estimate={empty ? undefined : estimate.data}
            estimating={estimate.isFetching}
            starting={start.isPending}
            onStart={() => start.mutate()}
            onCancel={onClose}
          />
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
