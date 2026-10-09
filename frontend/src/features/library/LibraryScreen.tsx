import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, type KeyboardEvent, type MouseEvent } from "react";
import { useNavigate, useParams } from "react-router";

import { api } from "@/api/client";
import { Banner } from "@/components/ui/Banner";
import { Button } from "@/components/ui/Button";
import { useActivity } from "@/lib/activity";
import { formatDay } from "@/lib/format";
import { media } from "@/lib/media";
import { useToasts } from "@/lib/toasts";

import { ClipInspector } from "./ClipInspector";
import { useClipUpdates, useDecide, useLibrary } from "./hooks";
import { BulkBar, DayScrubber, KeyHints } from "./LibraryChrome";
import { LibraryGrid, type LibraryGridHandle } from "./LibraryGrid";
import { LibraryToolbar, type StatusView } from "./LibraryToolbar";
import { activeFilters, type ClipDetail, type DecisionChange, type LibraryPage } from "./model";
import { useLibraryView } from "./store";

const STARS = ["1", "2", "3", "4", "5"];
const DEEPEN_SELECTION_MAX = 50; // clips whose moments a selection deepen collects

/** S10 Library (`/p/:pid/library`): browse, filter and decide; the inspector shows the
 * focused clip. Decisions are optimistic and persist (ADR 0042). */
export function LibraryScreen() {
  const { pid = "" } = useParams();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const v = useLibraryView();
  const grid = useRef<LibraryGridHandle>(null);
  const search = useRef<HTMLInputElement>(null);
  useEffect(() => v.forProject(pid), [pid, v]);
  useClipUpdates(pid);

  const lib = useLibrary(pid, v.group, v.filters, v.showRejected);
  const pages = lib.data?.pages;
  const items = useMemo(() => (pages ?? []).flatMap((p) => p.items), [pages]);
  const groups = pages?.[0]?.groups ?? [];
  const hidden = pages?.[0]?.rejected_hidden ?? 0;
  const order = useMemo(() => items.map((i) => i.asset_id), [items]);
  const decide = useDecide(pid);
  const toast = useToasts((s) => s.push);

  // Day and camera choices for the filter chips (the unfiltered library's groups).
  const choices = (group: "day" | "camera") =>
    ({
      queryKey: ["library-groups", pid, group],
      queryFn: async () =>
        ((await api.GET("/api/projects/{pid}/library", { params: { path: { pid }, query: { group, limit: 1, show_rejected: true } } })).data as unknown as LibraryPage)
          .groups ?? [],
    }) as const;
  const days = useQuery(choices("day"));
  const cameras = useQuery(choices("camera"));
  const analyzing = useActivity((s) => Object.values(s.jobs).some((j) => j.projectId === pid && j.kind === "analysis" && j.state === "running"));

  const focus = v.focus;
  const clip = useQuery({
    queryKey: ["clip", pid, focus, v.showRejected],
    enabled: focus !== null && v.inspector && v.selection.length <= 1,
    queryFn: async () =>
      (await api.GET("/api/projects/{pid}/clips/{aid}", { params: { path: { pid, aid: focus! }, query: { show_rejected: v.showRejected } } })).data as unknown as ClipDetail,
  });

  const selection = useMemo(() => new Set(v.selection), [v.selection]);
  const targets = v.selection.length ? v.selection : focus !== null ? [focus] : [];
  const act = (change: DecisionChange, ids = targets) => ids.length && decide.mutate({ ids, change });

  const statusView: StatusView = v.filters.status ?? (v.showRejected ? "everything" : "default");
  const onStatusView = (sv: StatusView) => {
    if (sv === "default" || sv === "everything") {
      v.set({ showRejected: sv === "everything" });
      v.setFilters({ status: undefined });
    } else {
      v.setFilters({ status: sv });
    }
  };

  const onSelect = (e: MouseEvent, id: number) => {
    if (e.metaKey || e.ctrlKey) {
      const next = selection.has(id) ? v.selection.filter((x) => x !== id) : [...v.selection, id];
      v.set({ selection: next, focus: id, anchor: id });
    } else if (e.shiftKey && v.anchor !== null && order.includes(v.anchor)) {
      const [a, b] = [order.indexOf(v.anchor), order.indexOf(id)].sort((x, y) => x - y) as [number, number];
      v.set({ selection: order.slice(a, b + 1), focus: id });
    } else {
      v.set({ selection: [id], focus: id, anchor: id, inspector: true });
    }
  };

  const move = (delta: number, extend: boolean) => {
    if (!order.length) return;
    const at = focus === null ? -1 : order.indexOf(focus);
    const next = order[Math.min(order.length - 1, Math.max(0, at + delta))]!;
    if (extend && v.anchor !== null && order.includes(v.anchor)) {
      const [a, b] = [order.indexOf(v.anchor), order.indexOf(next)].sort((x, y) => x - y) as [number, number];
      v.set({ focus: next, selection: order.slice(a, b + 1) });
    } else {
      v.set({ focus: next, selection: [next], anchor: next });
    }
    moved.current = true;
    grid.current?.scrollToAsset(next);
  };

  /** Grid keys (S10): they act only when the key comes from the grid, never from a
   * button, field, menu or the player elsewhere on the screen. */
  const onGridKey = (e: KeyboardEvent) => {
    const el = e.target as HTMLElement;
    if (!el.closest("[data-testid=library-grid]") || el.closest("input, textarea, [role=menu], [role=rowheader]")) return;
    const cols = grid.current?.columns() ?? 1;
    const k = e.key;
    const mod = e.metaKey || e.ctrlKey;
    if (k === "ArrowRight") move(1, e.shiftKey);
    else if (k === "ArrowLeft") move(-1, e.shiftKey);
    else if (k === "ArrowDown") move(cols, e.shiftKey);
    else if (k === "ArrowUp") move(-cols, e.shiftKey);
    else if (k === " " && focus !== null) {
      const video = document.querySelector<HTMLVideoElement>("aside[aria-label=Clip] video");
      if (video) void (video.paused ? video.play() : video.pause());
    } else if (mod && k.toLowerCase() === "a" && focus !== null) {
      const g = items.find((i) => i.asset_id === focus)?.group;
      v.set({ selection: items.filter((i) => i.group === g).map((i) => i.asset_id) });
    } else if (mod) return;
    else if (STARS.includes(k)) act({ stars: Number(k) });
    else if (k === "0") act({ stars: null });
    else if (k === "u" || k === "U") act({ disposition: "USE" });
    else if (k === "m" || k === "M") act({ disposition: "MAYBE" });
    else if (k === "r" || k === "R") act({ disposition: "REJECT" });
    else if (k === "l" || k === "L") act({ include: "always" });
    else if (k === "x" || k === "X") act({ include: "never" });
    else return; // Enter: the tile itself opens its clip
    e.preventDefault();
  };

  // "/" and Esc work anywhere on the screen except while typing.
  useEffect(() => {
    const on = (e: globalThis.KeyboardEvent) => {
      const el = e.target as HTMLElement | null;
      if (e.defaultPrevented || el?.closest("input, textarea, [contenteditable=true], [role=dialog], [role=menu]")) return;
      if (e.key === "/") {
        e.preventDefault();
        search.current?.focus();
      } else if (e.key === "Escape") {
        useLibraryView.getState().set({ selection: [], anchor: null });
      }
    };
    window.addEventListener("keydown", on);
    return () => window.removeEventListener("keydown", on);
  }, []);

  // On arrival the first clip takes focus, so the keys work without a click.
  const first = items[0]?.asset_id;
  useEffect(() => {
    if (first === undefined || document.activeElement !== document.body) return;
    const t = setTimeout(() => document.querySelector<HTMLElement>(`[data-asset="${first}"] [role=button]`)?.focus({ preventScroll: true }), 0);
    return () => clearTimeout(t);
  }, [first]);

  // Keyboard moves keep DOM focus on the focused tile once its row is mounted.
  const moved = useRef(false);
  useEffect(() => {
    if (!moved.current || focus === null) return;
    moved.current = false;
    // The row mounts once the scroll lands: try for a moment, then give up quietly.
    let tries = 0;
    let t: ReturnType<typeof setTimeout>;
    const attempt = () => {
      const el = document.querySelector<HTMLElement>(`[data-asset="${focus}"] [role=button]`);
      if (el) el.focus({ preventScroll: true });
      else if (tries++ < 20) t = setTimeout(attempt, 25);
    };
    t = setTimeout(attempt, 0);
    return () => clearTimeout(t);
  }, [focus]);

  const deepen = async () => {
    const picked = v.selection.slice(0, DEEPEN_SELECTION_MAX);
    if (!picked.length) return navigate(`/p/${pid}/deepen`);
    try {
      const details = await Promise.all(
        picked.map((aid) =>
          qc.fetchQuery({
            queryKey: ["clip", pid, aid, v.showRejected],
            queryFn: async () => {
              const { data, error } = await api.GET("/api/projects/{pid}/clips/{aid}", {
                params: { path: { pid, aid }, query: { show_rejected: v.showRejected } },
              });
              if (error || !data) throw new Error("clip");
              return data as unknown as ClipDetail;
            },
          }),
        ),
      );
      navigate(`/p/${pid}/deepen`, { state: { segmentIds: details.flatMap((d) => d.moments.map((m) => m.segment_id)) } });
    } catch {
      toast({ kind: "error", message: "Couldn't read the selected clips. Try again." });
    }
  };

  const dayChoices = (days.data ?? []).filter((g) => g.date).map((g) => ({ value: g.key, label: `Day ${g.day} · ${g.place || formatDay(g.date!)}` }));
  const cameraChoices = (cameras.data ?? []).map((g) => ({ value: Number(g.key), label: g.label }));
  const filtered = activeFilters(v.filters) > 0 || statusView !== "default";
  const empty = lib.isSuccess && items.length === 0;

  return (
    <div className="relative flex min-h-0 flex-1" onKeyDown={onGridKey}>
      <div className="flex min-w-0 flex-1 flex-col">
        <LibraryToolbar
          ref={search}
          filters={v.filters}
          statusView={statusView}
          onStatusView={onStatusView}
          onFilters={v.setFilters}
          days={dayChoices}
          cameras={cameraChoices}
          group={v.group}
          onGroup={(group) => v.set({ group, selection: [], collapsed: [] })}
          density={v.density}
          onDensity={(density) => v.set({ density })}
          onSearch={(q) => navigate(`/p/${pid}/search?q=${encodeURIComponent(q)}`)}
          onDeepen={() => void deepen()}
          onCreateEdit={() => navigate(`/p/${pid}/edits/new`)}
        />
        {analyzing && (
          <div className="px-6 pt-3">
            <Banner
              kind="info"
              action={
                <Button size="sm" variant="ghost" onClick={() => navigate(`/p/${pid}/analysis`)}>
                  View progress
                </Button>
              }
            >
              Analysis is still running. Clips without a decision yet show no chip, and early edits are marked preliminary.</Banner>
          </div>
        )}
        {(hidden > 0 || v.showRejected) && !v.filters.status && (
          <div className="px-6 pt-3">
            <Button size="sm" variant="ghost" onClick={() => v.set({ showRejected: !v.showRejected })}>
              {v.showRejected ? "Hide rejected" : `Show rejected (${hidden.toLocaleString("en-US")})`}
            </Button>
          </div>
        )}
        {lib.isLoading ? (
          <div aria-label="Loading" className="m-6 h-40 animate-pulse rounded-lg bg-surface-2" />
        ) : empty ? (
          <div className="flex flex-1 flex-col items-center justify-center gap-3 text-center">
            {filtered ? (
              <>
                <p className="text-body text-text-muted">No clips match.</p>
                <Button onClick={v.clearFilters}>
                  Clear filters
                </Button>
              </>
            ) : (
              <p className="text-body text-text-muted">No clips yet. Analyze the trip to fill the library.</p>
            )}
          </div>
        ) : (
          <LibraryGrid
            ref={grid}
            pid={pid}
            groups={groups}
            items={items}
            density={v.density}
            collapsed={new Set(v.collapsed)}
            selection={selection}
            focus={focus}
            hasMore={Boolean(lib.hasNextPage)}
            loadingMore={lib.isFetchingNextPage}
            onEnd={() => void lib.fetchNextPage()}
            onToggleGroup={(key) => v.set({ collapsed: v.collapsed.includes(key) ? v.collapsed.filter((k) => k !== key) : [...v.collapsed, key] })}
            onSelect={onSelect}
            onOpen={(id) => navigate(`/p/${pid}/clips/${id}`)}
            onFocus={(id) => v.focus !== id && v.set({ focus: id })}
          />
        )}
        <KeyHints />
      </div>
      {v.group === "day" && (
        <DayScrubber
          days={groups.filter((g) => g.day).map((g) => ({ key: g.key, n: g.day! }))}
          current={items.find((i) => i.asset_id === focus)?.group}
          onJump={(key) => {
            if (!grid.current?.scrollToGroup(key)) v.setFilters({ day: key });
          }}
        />
      )}
      {v.inspector && clip.data && focus !== null && v.selection.length <= 1 && (
        <ClipInspector
          key={clip.data.asset_id}
          clip={clip.data}
          proxyUrl={clip.data.kind === "video" ? media.proxy(pid, clip.data.asset_id) : undefined}
          frameUrl={(sid) => media.frame(pid, sid)}
          onDecide={(change) => act(change, [clip.data!.asset_id])}
          onOpenFull={() => navigate(`/p/${pid}/clips/${clip.data!.asset_id}`)}
          onClose={() => v.set({ inspector: false })}
          onShowClip={(id) => {
            v.set({ focus: id, selection: [id], anchor: id });
            grid.current?.scrollToAsset(id);
          }}
        />
      )}
      {v.selection.length >= 2 && <BulkBar count={v.selection.length} onDecide={(c) => act(c)} onClear={() => v.set({ selection: [], anchor: null })} />}
    </div>
  );
}
