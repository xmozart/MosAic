import { keepPreviousData, useMutation, useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router";

import { api } from "@/api/client";
import { media } from "@/lib/media";
import { useToasts } from "@/lib/toasts";

import { DEFAULT_REQUEST, defaultName, isAspect, requestFrom, type EditCardData, type EditEstimate, type EditRequest, type Preset } from "./model";
import { WizardView } from "./WizardView";

const ESTIMATE_DEBOUNCE_MS = 400;

/** S14 Create edit (`/p/:pid/edits/new?from=&duration=&aspect=`): S13's "Start from" chips
 * prefill the request from another edit (ADR 0048). */
export function WizardScreen() {
  const [params] = useSearchParams();
  // A new start point (another ?from=) is a new wizard: nothing carries over.
  return <Wizard key={params.toString()} />;
}

function Wizard() {
  const { pid = "" } = useParams();
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const toast = useToasts((s) => s.push);
  const [step, setStep] = useState(1);
  const from = params.get("from");
  // With ``from``, nothing shows (and nothing is estimated) until the source edit's
  // request is in, so a late prefill never overwrites the owner's choices.
  const [edited, setEdited] = useState<EditRequest | undefined>(undefined);
  const edits = useQuery({
    queryKey: ["edits", pid],
    enabled: Boolean(from),
    queryFn: async () => ((await api.GET("/api/projects/{pid}/edits", { params: { path: { pid }, query: { limit: 200 } } })).data as unknown as { items: EditCardData[] }).items,
  });
  const prefill = useMemo(() => {
    if (!from) return DEFAULT_REQUEST;
    if (!edits.data && !edits.isError) return undefined;
    const patch: Partial<EditRequest> = {};
    const duration = Number(params.get("duration"));
    if (duration > 0) patch.duration_s = duration;
    const aspect = params.get("aspect");
    if (isAspect(aspect)) patch.aspect = aspect; // a hand-edited URL never reaches the API
    return requestFrom(edits.data?.find((e) => e.edit_id === from)?.request, patch);
  }, [from, edits.data, edits.isError, params]);
  const request = edited ?? prefill;

  const projects = useQuery({
    queryKey: ["projects"],
    queryFn: async () => (await api.GET("/api/projects")).data as { items: { id: string; name: string }[] } | undefined,
  });
  const trip = projects.data?.items.find((x) => x.id === pid)?.name;

  const presets = useQuery({
    queryKey: ["presets", pid],
    queryFn: async () => ((await api.GET("/api/projects/{pid}/presets", { params: { path: { pid } } })).data as unknown as { items: Preset[] }).items,
  });
  const featured = presets.data?.filter((x) => x.featured) ?? [];
  const collages = useQueries({
    queries: featured.map((x) => ({
      queryKey: ["collage", pid, x.id],
      staleTime: 60_000,
      queryFn: async () =>
        (
          (await api.GET("/api/projects/{pid}/presets/{preset}/collage", { params: { path: { pid, preset: x.id } } })).data as unknown as {
            frames: number[];
          }
        ).frames.map((sid) => media.frame(pid, sid)),
    })),
  });

  const settled = useDebounced(request, ESTIMATE_DEBOUNCE_MS); // one estimate per pause (STATUS: retrieval runs per call)
  const estimate = useQuery({
    queryKey: ["edit-estimate", pid, settled],
    enabled: settled !== undefined,
    placeholderData: keepPreviousData,
    queryFn: async () => {
      const { data, error } = await api.POST("/api/edits/estimate", { body: { project_id: pid, request: settled as unknown as Record<string, never> } });
      if (error || !data) throw new Error("estimate");
      return data as unknown as EditEstimate;
    },
  });

  const title = useMemo(() => (request ? defaultName(trip ?? "New edit", request) : ""), [trip, request]);
  const create = useMutation({
    mutationFn: async () => {
      // The name is the trip's only once the trip is known; else the backend names it.
      const body = { request, ...(trip ? { name: title } : {}) };
      const { data, error } = await api.POST("/api/projects/{pid}/edits", { params: { path: { pid } }, body: body as unknown as Record<string, never> });
      if (error || !data) throw new Error("create");
      return data as unknown as { edit_id: string; job_id: number };
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["edits", pid] });
      toast({ kind: "info", message: `Creating “${title}”. It shows on Edits as it's made.` });
      navigate(`/p/${pid}/edits`);
    },
    onError: () => toast({ kind: "error", message: "Couldn't start the edit. Try again." }),
  });

  if (!request) {
    return <div aria-label="Loading the edit to start from" className="m-8 h-[420px] flex-1 animate-pulse rounded-lg bg-surface-1" />;
  }
  return (
    <WizardView
      step={step}
      onStep={setStep}
      request={request}
      onChange={(patch) => setEdited((r) => ({ ...(r ?? request!), ...patch }))}
      title={title}
      presets={presets.data}
      collages={Object.fromEntries(featured.map((x, i) => [x.id, collages[i]?.isError ? [] : collages[i]?.data]))}
      estimate={estimate.data}
      estimateError={estimate.isError && !estimate.data}
      estimatePending={settled !== request || estimate.isPlaceholderData}
      creating={create.isPending}
      onCreate={() => !create.isPending && create.mutate()}
      onWait={() => navigate(`/p/${pid}/analysis`)}
    />
  );
}

function useDebounced<T>(value: T, ms: number): T {
  const [settled, setSettled] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setSettled(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return settled;
}
