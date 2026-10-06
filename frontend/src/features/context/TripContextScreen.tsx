import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router";

import { api } from "@/api/client";
import { useToasts } from "@/lib/toasts";

import { EMPTY, forSave, mergeProposal, type TripContext } from "./model";
import { TripContextView, type ContextTab } from "./TripContextView";

interface ParseJob {
  state: string;
  error: string | null;
  result: { proposal?: TripContext } | null;
}

const PARSE_FAILED = "Couldn't read those notes. Check your AI provider in Settings, or fill in the details yourself.";

/** S7 Trip context (`/p/:pid/context`): edit, or paste and parse (an AI job), then save. */
export function TripContextScreen() {
  const { pid = "" } = useParams();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const toast = useToasts((s) => s.push);
  const stored = useQuery({
    queryKey: ["trip-context", pid],
    queryFn: async () =>
      (await api.GET("/api/projects/{pid}/trip-context", { params: { path: { pid } } })).data as unknown as TripContext & { revision: number },
  });
  const inventory = useQuery({
    queryKey: ["inventory", pid],
    queryFn: async () => (await api.GET("/api/projects/{pid}/inventory", { params: { path: { pid } } })).data as { days: { date: string }[] } | undefined,
  });
  const [draft, setDraft] = useState<TripContext | null>(null);
  const value = draft ?? (stored.data ? { ...EMPTY, ...stored.data } : EMPTY);
  const [tab, setTab] = useState<ContextTab>("details");
  const [paste, setPaste] = useState("");
  const [highlights, setHighlights] = useState<Set<string>>(new Set());
  const [parsing, setParsing] = useState(false);
  const [parseError, setParseError] = useState<string | null>(null);

  const alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);
  const latest = useRef(value);
  useEffect(() => {
    latest.current = value;
  });

  /** Starts the parse job and polls it (`GET /jobs/{id}`) until it ends, then merges the
   * proposal into what is on screen at that moment. */
  const parse = async () => {
    setParseError(null);
    const { data, error } = await api.POST("/api/projects/{pid}/trip-context/parse", { params: { path: { pid } }, body: { text: paste } });
    if (error || !data) {
      setParseError(PARSE_FAILED);
      return;
    }
    const jobId = (data as { job_id: number }).job_id;
    setParsing(true);
    let job: ParseJob | undefined;
    while (alive.current) {
      await new Promise((r) => setTimeout(r, 1000));
      job = (await api.GET("/api/jobs/{job_id}", { params: { path: { job_id: jobId } } }).catch(() => ({ data: undefined }))).data as unknown as
        | ParseJob
        | undefined;
      if (job && ["done", "failed", "cancelled"].includes(job.state)) break;
    }
    if (!alive.current) return;
    setParsing(false);
    const proposal = job?.state === "done" ? job.result?.proposal : undefined;
    if (!proposal) {
      setParseError(PARSE_FAILED);
      return;
    }
    const merged = mergeProposal(latest.current, { ...EMPTY, ...proposal });
    setDraft(merged.value);
    setHighlights(merged.changed);
    setTab("details");
  };

  const save = useMutation({
    mutationFn: async () => {
      const { data, error } = await api.PUT("/api/projects/{pid}/trip-context", {
        params: { path: { pid } },
        body: forSave(value) as unknown as Record<string, unknown>,
      });
      if (error || !data) throw new Error("not saved");
      return data;
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["trip-context", pid] });
      toast({ kind: "success", message: "Trip details saved. Summaries will update; the analysis won't re-run." });
      navigate(`/p/${pid}/analyze`);
    },
    onError: () => toast({ kind: "error", message: "Couldn't save the trip details. Check the highlighted fields and try again." }),
  });

  if (stored.isLoading) return <div aria-label="Loading" className="m-8 h-40 animate-pulse rounded-lg bg-surface-2" />;
  return (
    <TripContextView
      value={value}
      onChange={setDraft}
      footageDays={inventory.data?.days.map((d) => d.date) ?? []}
      highlights={highlights}
      tab={tab}
      onTab={setTab}
      paste={paste}
      onPaste={setPaste}
      parsing={parsing}
      parseError={parseError}
      onParse={() => void parse()}
      saving={save.isPending}
      onSave={() => save.mutate()}
      onSkip={() => navigate(`/p/${pid}/analyze`)}
    />
  );
}
