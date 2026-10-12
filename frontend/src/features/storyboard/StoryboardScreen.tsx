import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router";

import { api } from "@/api/client";
import { Player } from "@/components/media/Player";
import { media } from "@/lib/media";
import { useToasts } from "@/lib/toasts";

import type { Alternative, DraftOp, DraftState, ShotMedia } from "./model";
import { StoryboardView } from "./StoryboardView";

const POLL_MS = 1500;

/** The API's reason for a refused change, in its own words (409/422 `detail`). */
function reason(error: unknown, fallback: string): string {
  const detail = (error as { detail?: unknown } | undefined)?.detail;
  return typeof detail === "string" && detail ? detail : fallback;
}

class Refused extends Error {}

function without(w: Record<string, string>, key: string): Record<string, string> {
  const out = { ...w };
  delete out[key];
  return out;
}

/** S16 Storyboard (`/p/:pid/edits/:eid/storyboard`): the edit's draft, changed op by op
 * (each undoable), saved as a version, regenerated a beat or the story at a time with the
 * locks kept (ADR 0067, 0069, 0088). */
export function StoryboardScreen() {
  const { pid = "", eid = "" } = useParams();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const toast = useToasts((s) => s.push);
  const key = ["draft", eid];
  const [warnings, setWarnings] = useState<Record<string, string>>({});
  const [openShot, setOpenShot] = useState<string | null>(null);

  const draft = useQuery({
    queryKey: key,
    queryFn: async () => {
      const { data, error } = await api.GET("/api/edits/{eid}/draft", { params: { path: { eid } } });
      if (error || !data) throw new Error("draft");
      return data as unknown as DraftState;
    },
    // While a beat or the story regenerates, follow it (the others stay editable).
    refetchInterval: (q) => (q.state.data && (q.state.data.regenerating.length || q.state.data.regenerating_scope) ? POLL_MS : false),
  });
  const d = draft.data;

  // A regeneration that finished made a new version: S13 and S17 show it.
  const busy = Boolean(d && (d.regenerating.length || d.regenerating_scope));
  const wasBusy = useRef(false);
  useEffect(() => {
    if (wasBusy.current && !busy) {
      void qc.invalidateQueries({ queryKey: ["edits", pid] });
      void qc.invalidateQueries({ queryKey: ["edit", eid] });
    }
    wasBusy.current = busy;
  }, [busy, pid, eid, qc]);

  // Changes go to the server one at a time, in the order they were made; each is queued
  // the moment it is made, so a save or a regenerate after it waits for it. A change made
  // before the previous one's answer is built from the board as shown (a quick second L
  // sends the same lock again: harmless).
  const queue = useRef<Promise<unknown>>(Promise.resolve());
  const [sending, setSending] = useState(0);
  const enqueue = (run: () => Promise<DraftState>) => {
    setSending((n) => n + 1);
    queue.current = queue.current
      .then(run)
      .then(
        async (state) => {
          // A poll started before this change must not land after it with an older board.
          await qc.cancelQueries({ queryKey: key });
          qc.setQueryData(key, (old: DraftState | undefined) => ({ ...state, regenerating: old?.regenerating ?? [], regenerating_scope: old?.regenerating_scope ?? null }));
          void qc.invalidateQueries({ queryKey: ["edit", eid] });
        },
        (e: unknown) => {
          if (!(e instanceof Refused)) toast({ kind: "error", message: "That change couldn't be made. Try again." });
          void draft.refetch();
        },
      )
      .finally(() => setSending((n) => n - 1));
  };
  const post = async (path: "/api/edits/{eid}/draft/ops" | "/api/edits/{eid}/draft/undo" | "/api/edits/{eid}/draft/redo", op?: DraftOp, beat?: string) => {
    const { data, error, response } = await api.POST(path, { params: { path: { eid } }, body: (op ? { op } : undefined) as never });
    if (error || !data) {
      if (response.status === 409 || response.status === 422) {
        const text = reason(error, "That change couldn't be made.");
        if (beat) setWarnings((w) => ({ ...w, [beat]: text }));
        else toast({ kind: "error", message: text });
        throw new Refused(text);
      }
      throw new Error("draft");
    }
    return data as unknown as DraftState;
  };
  const onOp = (op: DraftOp) => {
    const beat = op.kind === "pace_beat" ? op.beat_id : undefined;
    if (beat) setWarnings((w) => without(w, beat));
    enqueue(() => post("/api/edits/{eid}/draft/ops", op, beat));
  };

  const save = useMutation({
    mutationFn: async () => {
      await queue.current;
      const { data, error } = await api.POST("/api/edits/{eid}/versions", { params: { path: { eid } } });
      if (error || !data) throw new Error("save");
      return (data as unknown as { version: number }).version;
    },
    onSuccess: (v) => {
      toast({ kind: "info", message: `Saved as version ${v}.` });
      void draft.refetch();
      void qc.invalidateQueries({ queryKey: ["edits", pid] });
      void qc.invalidateQueries({ queryKey: ["edit", eid] });
    },
    onError: () => toast({ kind: "error", message: "The version couldn't be saved. Try again." }),
  });

  const regenerate = useMutation({
    mutationFn: async (beat: string | null) => {
      await queue.current;
      const res = beat
        ? await api.POST("/api/edits/{eid}/beats/{bid}/regenerate", { params: { path: { eid, bid: beat } } })
        : await api.POST("/api/edits/{eid}/regenerate", { params: { path: { eid }, query: { scope: "story" } } });
      if (res.error) {
        const text = reason(res.error, beat ? "This beat can't be regenerated." : "The story can't be regenerated.");
        if (beat && (res.response.status === 409 || res.response.status === 422)) setWarnings((w) => ({ ...w, [beat]: text }));
        else toast({ kind: "error", message: text });
        throw new Refused(text);
      }
    },
    onMutate: (beat) => {
      if (beat) setWarnings((w) => without(w, beat));
    },
    onSettled: () => void draft.refetch(),
  });

  const alternatives = useQuery({
    queryKey: ["alternatives", eid, openShot, d?.base_version, d?.ops],
    enabled: openShot !== null,
    queryFn: async () => {
      const { data, error } = await api.GET("/api/edits/{eid}/shots/{shot}/alternatives", { params: { path: { eid, shot: openShot! } } });
      if (error || !data) return [] as Alternative[];
      return (data as unknown as { items: Alternative[] }).items;
    },
  });

  const preview = async () => {
    await queue.current; // a change still on its way counts
    if (qc.getQueryData<DraftState>(key)?.dirty) {
      try {
        await save.mutateAsync();
      } catch {
        return;
      }
    }
    navigate(`/p/${pid}/edits/${eid}`);
  };

  return (
    <StoryboardView
      draft={d}
      error={draft.isError}
      onRetry={() => void draft.refetch()}
      frame={(sid) => media.frame(pid, sid)}
      alternatives={(ref) => (ref === openShot && !alternatives.isFetching ? alternatives.data : undefined)}
      player={(ref) => {
        const shot = d?.board.beats.flatMap((b) => b.shots).find((s) => s.ref === ref);
        const m = shot ? d?.media[shot.segment_id] : undefined;
        return m ? <ShotPlayer pid={pid} media={m} poster={m.sample_id != null ? media.frame(pid, m.sample_id) : undefined} /> : null;
      }}
      warnings={warnings}
      saving={save.isPending || sending > 0}
      onOp={onOp}
      onUndo={() => enqueue(() => post("/api/edits/{eid}/draft/undo"))}
      onRedo={() => enqueue(() => post("/api/edits/{eid}/draft/redo"))}
      onSave={() => !save.isPending && save.mutate()}
      onRegenerateBeat={(b) => regenerate.mutate(b)}
      onRegenerateStory={() => regenerate.mutate(null)}
      onPreview={() => void preview()}
      onChangeSettings={() => navigate(`/p/${pid}/edits/new?from=${encodeURIComponent(eid)}`)}
      onOpenShot={setOpenShot}
    />
  );
}

/** The shot's usable range from its proxy (a photo shows its frame). */
function ShotPlayer({ pid, media: m, poster }: { pid: string; media: ShotMedia; poster?: string }) {
  const clip = useQuery({
    queryKey: ["clip", pid, m.asset],
    enabled: !m.photo,
    queryFn: async () => (await api.GET("/api/projects/{pid}/clips/{aid}", { params: { path: { pid, aid: m.asset } } })).data as unknown as { proxy_rate: string | null; rate: string | null },
  });
  const rate = clip.data?.proxy_rate ?? clip.data?.rate;
  if (m.photo || !rate) {
    return (
      <div className="aspect-video overflow-hidden rounded-sm bg-surface-3">
        {poster && <img src={poster} alt="" className="size-full object-cover" />}
      </div>
    );
  }
  return <Player src={media.proxy(pid, m.asset)} poster={poster} rate={rate} range={m.range} />;
}
