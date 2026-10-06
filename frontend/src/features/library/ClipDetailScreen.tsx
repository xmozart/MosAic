import { useQuery } from "@tanstack/react-query";
import { useEffect } from "react";
import { useNavigate, useParams } from "react-router";

import { api } from "@/api/client";
import { decodePeaks, media } from "@/lib/media";

import type { TranscriptLine } from "@/components/media/Transcript";

import { ClipDetailView } from "./ClipDetailView";
import { useClipUpdates, useDecide } from "./hooks";
import type { ClipDetail, DecisionChange } from "./model";
import { useLibraryView } from "./store";

const KEYS: Record<string, DecisionChange> = {
  u: { disposition: "USE" },
  m: { disposition: "MAYBE" },
  r: { disposition: "REJECT" },
  l: { include: "always" },
  x: { include: "never" },
  "0": { stars: null },
};

/** S11 Clip detail (`/p/:pid/clips/:aid`): the library's decision keys, plus [ and ] for
 * the previous and next clip in the library's order. */
export function ClipDetailScreen() {
  const { pid = "", aid = "" } = useParams();
  const id = Number(aid);
  const navigate = useNavigate();
  const showRejected = useLibraryView((s) => s.showRejected);
  const decide = useDecide(pid);
  useClipUpdates(pid);
  const clip = useQuery({
    queryKey: ["clip", pid, id, showRejected],
    queryFn: async () => {
      const { data, error, response } = await api.GET("/api/projects/{pid}/clips/{aid}", { params: { path: { pid, aid: id }, query: { show_rejected: showRejected } } });
      if (error || !data) throw new Error(response.status === 404 ? "missing" : "failed");
      return data as unknown as ClipDetail;
    },
  });
  const c = clip.data;
  const video = c?.kind === "video" && c.status !== "unsupported";
  const strip = useQuery({
    queryKey: ["filmstrip", pid, id, 12],
    enabled: Boolean(video),
    queryFn: async () => (await api.GET("/api/media/{pid}/filmstrip/{aid}", { params: { path: { pid, aid: id }, query: { n: 12 } } })).data as unknown as { frames: { sample_id: number; ticks: number }[] },
  });
  const wave = useQuery({
    queryKey: ["waveform", pid, id],
    enabled: Boolean(video),
    queryFn: async () => (await api.GET("/api/media/{pid}/waveform/{aid}", { params: { path: { pid, aid: id } } })).data as unknown as { silent: boolean; peaks: string },
  });
  const transcript = useQuery({
    queryKey: ["transcript", pid, id],
    enabled: Boolean(c && c.transcript.segments > 0),
    queryFn: async () =>
      (await api.GET("/api/projects/{pid}/clips/{aid}/transcript", { params: { path: { pid, aid: id } } })).data as unknown as { items: TranscriptLine[] },
  });

  const go = (to: number | null | undefined) => to && navigate(`/p/${pid}/clips/${to}`, { replace: true });
  useEffect(() => {
    const on = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement | null;
      if (!c || e.metaKey || e.ctrlKey || el?.closest("input, textarea, [role=menu], [role=dialog]")) return;
      const k = e.key.toLowerCase();
      if (k === "[") go(c.position?.prev);
      else if (k === "]") go(c.position?.next);
      else if (["1", "2", "3", "4", "5"].includes(k)) decide.mutate({ ids: [c.asset_id], change: { stars: Number(k) } });
      else if (KEYS[k] && !(el?.closest("[aria-label=Player]") && ["l"].includes(k))) decide.mutate({ ids: [c.asset_id], change: KEYS[k]! });
      else return;
      e.preventDefault();
    };
    window.addEventListener("keydown", on);
    return () => window.removeEventListener("keydown", on);
  });

  if (clip.isError && clip.error.message === "missing") return <p className="p-8 text-body text-text-muted">That clip isn't in this trip.</p>;
  if (clip.isError) {
    return (
      <div className="flex flex-col items-start gap-3 p-8">
        <p className="text-body text-text-muted">Couldn't load this clip.</p>
        <button type="button" className="text-small text-accent underline-offset-2 hover:underline" onClick={() => void clip.refetch()}>
          Try again
        </button>
      </div>
    );
  }
  if (!c)
    return (
      <div role="status" className="m-8 h-64 animate-pulse rounded-lg bg-surface-2">
        <span className="sr-only">Loading the clip</span>
      </div>
    );
  return (
    <ClipDetailView
      clip={c}
      proxyUrl={video ? media.proxy(pid, id) : undefined}
      frameUrl={(sid) => media.frame(pid, sid)}
      filmstrip={(strip.data?.frames ?? []).map((f) => media.frame(pid, f.sample_id))}
      filmstripTicks={(strip.data?.frames ?? []).map((f) => f.ticks)}
      peaks={wave.data && !wave.data.silent ? decodePeaks(wave.data.peaks) : null}
      transcript={transcript.data?.items ?? []}
      onDecide={(change) => decide.mutate({ ids: [c.asset_id], change })}
      onBack={() => navigate(`/p/${pid}/library`)}
      onPrev={c.position?.prev ? () => go(c.position!.prev) : undefined}
      onNext={c.position?.next ? () => go(c.position!.next) : undefined}
      onShowClip={(to) => navigate(`/p/${pid}/clips/${to}`)}
    />
  );
}
