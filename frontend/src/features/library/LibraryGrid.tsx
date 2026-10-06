import { useQuery } from "@tanstack/react-query";
import { useVirtualizer } from "@tanstack/react-virtual";
import { ChevronDown } from "lucide-react";
import { forwardRef, useCallback, useEffect, useImperativeHandle, useLayoutEffect, useMemo, useRef, useState, type MouseEvent } from "react";

import { api } from "@/api/client";
import { ClipTile } from "@/components/media/ClipTile";
import { cn } from "@/lib/cn";
import type { Density } from "@/lib/domain";
import { media } from "@/lib/media";

import { buildRows, GAP, gridLayout, HEADER, headerText, OVERSCAN, wantsMoreAt } from "./layout";
import { clipLength, type LibraryGroup, type LibraryItem } from "./model";

const SCRUB_FRAMES = 8;

function Tile(p: {
  pid: string;
  frameUrl: (sampleId: number) => string;
  item: LibraryItem;
  selected: boolean;
  focused: boolean;
  tabbable: boolean;
  density: Density;
  onSelect: (e: MouseEvent, id: number) => void;
  onOpen: (id: number) => void;
  onFocus: (id: number) => void;
  onUnmountFocused: () => void;
}) {
  const [hovered, setHovered] = useState(false);
  const cell = useRef<HTMLDivElement>(null);
  const { onUnmountFocused } = p;
  // A focused tile that scrolls out of the virtual window hands focus to the grid, so the
  // keys keep working (S10: keyboard navigation, M2 acceptance 5).
  useLayoutEffect(() => {
    const el = cell.current;
    return () => {
      if (el?.contains(document.activeElement)) setTimeout(onUnmountFocused, 0);
    };
  }, [onUnmountFocused]);
  const it = p.item;
  // Hover-scrub uses sample frames, never video decode (S10 acceptance).
  const strip = useQuery({
    queryKey: ["filmstrip", p.pid, it.asset_id, SCRUB_FRAMES],
    enabled: hovered && it.kind === "video",
    staleTime: Infinity,
    queryFn: async () =>
      (await api.GET("/api/media/{pid}/filmstrip/{aid}", { params: { path: { pid: p.pid, aid: it.asset_id }, query: { n: SCRUB_FRAMES } } }))
        .data as unknown as { frames: { sample_id: number }[] },
  });
  return (
    <div
      ref={cell}
      role="gridcell"
      aria-selected={p.selected}
      data-asset={it.asset_id}
      data-focused={p.focused || undefined}
      onMouseEnter={() => setHovered(true)}
      className={cn("min-w-0 rounded-md", p.focused && !p.selected && "ring-1 ring-accent/50")}
    >
      <ClipTile
        asset={{
          name: it.name?.split("/").at(-1) ?? `Clip ${it.asset_id}`,
          duration: clipLength(it.duration),
          camera: it.camera,
          thumbnail: it.sample_id ? p.frameUrl(it.sample_id) : undefined,
          frames: strip.data?.frames.map((f) => p.frameUrl(f.sample_id)),
          livePhoto: it.kind === "live_photo",
          offline: it.offline,
        }}
        disposition={it.status_shown ?? undefined}
        decidedBy={it.decided_by ?? "ai"}
        stars={it.decision.stars ?? 0}
        hasSpeech={it.has_speech}
        similarCount={it.similar_count}
        selected={p.selected}
        density={p.density}
        caption={p.density === "comfortable" ? (it.caption ?? undefined) : undefined}
        onSelect={(e) => p.onSelect(e, it.asset_id)}
        onOpen={() => p.onOpen(it.asset_id)}
        tabIndex={p.tabbable ? 0 : -1}
        onFocus={() => p.onFocus(it.asset_id)}
      />
    </div>
  );
}

export interface LibraryGridHandle {
  scrollToGroup: (key: string) => boolean;
  scrollToAsset: (id: number) => void;
  columns: () => number;
}

export interface LibraryGridProps {
  pid: string;
  frameUrl?: (sampleId: number) => string;
  groups: LibraryGroup[];
  items: LibraryItem[];
  density: Density;
  collapsed: ReadonlySet<string>;
  selection: ReadonlySet<number>;
  focus: number | null;
  hasMore: boolean;
  loadingMore: boolean;
  onEnd: () => void;
  onToggleGroup: (key: string) => void;
  onSelect: (e: MouseEvent, id: number) => void;
  onOpen: (id: number) => void;
  onFocus: (id: number) => void;
}

/** S10 VirtualGrid (COMPONENTS.md): tiles at least 220 px (comfortable) or 160 px
 * (compact) wide, grouped, with only the visible rows mounted (≤ about 60 tiles). */
export const LibraryGrid = forwardRef<LibraryGridHandle, LibraryGridProps>(function LibraryGrid(p, ref) {
  const scroller = useRef<HTMLDivElement>(null);
  const [box, setBox] = useState({ width: 1000, height: 800 });
  useLayoutEffect(() => {
    const el = scroller.current;
    if (!el) return;
    const ro = new ResizeObserver(([entry]) => entry && setBox({ width: entry.contentRect.width, height: entry.contentRect.height }));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  // Fixed row heights from the layout (no per-row measuring); at most 60 tiles mounted.
  const { cols, rowH } = gridLayout(Math.max(160, box.width - 48), box.height, p.density);
  const rows = useMemo(() => buildRows(p.groups, p.items, cols, p.collapsed), [p.groups, p.items, cols, p.collapsed]);
  // TanStack Virtual's API is not memoizable by the React Compiler; this component opts out.
  // oxlint-disable-next-line react/incompatible-library
  const virtual = useVirtualizer({
    count: rows.length,
    getScrollElement: () => scroller.current,
    estimateSize: (i) => (rows[i]?.kind === "header" ? HEADER : rowH),
    overscan: OVERSCAN,
  });
  const focusGrid = useCallback(() => scroller.current?.focus({ preventScroll: true }), []);
  const visible = virtual.getVirtualItems();
  const last = visible.at(-1)?.index ?? 0;
  const { hasMore, loadingMore, onEnd } = p;
  // The next page loads when an expanded group with clips still to load comes into view.
  const trigger = wantsMoreAt(rows, p.collapsed);
  useEffect(() => {
    if (hasMore && !loadingMore && trigger !== null && last >= trigger - 2) onEnd();
  }, [last, trigger, hasMore, loadingMore, onEnd]);
  useImperativeHandle(
    ref,
    () => ({
      scrollToGroup: (key) => {
        const i = rows.findIndex((r) => r.kind === "header" && r.group.key === key);
        if (i < 0) return false;
        virtual.scrollToIndex(i, { align: "start" });
        return true;
      },
      scrollToAsset: (id) => {
        const i = rows.findIndex((r) => r.kind === "tiles" && r.items.some((it) => it.asset_id === id));
        if (i >= 0) virtual.scrollToIndex(i, { align: "auto" });
      },
      columns: () => cols,
    }),
    [rows, virtual, cols],
  );
  return (
    <div ref={scroller} tabIndex={-1} role="grid" aria-label="Clips" aria-multiselectable className="min-h-0 flex-1 overflow-y-auto px-6" data-testid="library-grid">
      <div className="relative w-full" style={{ height: virtual.getTotalSize() }}>
        {visible.map((v) => {
          const row = rows[v.index]!;
          return (
            <div key={v.key} data-index={v.index} className="absolute top-0 left-0 w-full overflow-hidden" style={{ height: v.size, transform: `translateY(${v.start}px)` }}>
              {row.kind === "header" ? (
                <div role="row">
                  <div role="rowheader">
                    <GroupHeader group={row.group} collapsed={p.collapsed.has(row.group.key)} onToggle={() => p.onToggleGroup(row.group.key)} />
                  </div>
                </div>
              ) : (
                <div role="row" className="grid" style={{ gridTemplateColumns: `repeat(${cols}, minmax(0, 1fr))`, columnGap: GAP }}>
                  {row.items.map((it) => (
                    <Tile
                      key={it.asset_id}
                      pid={p.pid}
                      frameUrl={p.frameUrl ?? ((sid) => media.frame(p.pid, sid))}
                      item={it}
                      density={p.density}
                      selected={p.selection.has(it.asset_id)}
                      focused={p.focus === it.asset_id}
                      tabbable={p.focus === it.asset_id || (p.focus === null && it === p.items[0])}
                      onSelect={p.onSelect}
                      onOpen={p.onOpen}
                      onFocus={p.onFocus}
                      onUnmountFocused={focusGrid}
                    />
                  ))}
                </div>
              )}
            </div>
          );
        })}
      </div>
      {p.loadingMore && <p className="py-4 text-center text-small text-text-muted">Loading more clips…</p>}
    </div>
  );
});

/** COMPONENTS.md GroupHeader: collapsible title with its clip, duration and photo counts. */
export function GroupHeader({ group, collapsed, onToggle }: { group: LibraryGroup; collapsed: boolean; onToggle: () => void }) {
  const { title, facts } = headerText(group);
  return (
    <button
      type="button"
      aria-expanded={!collapsed}
      onClick={onToggle}
      className="flex w-full items-baseline gap-3 rounded-sm pt-4 pb-3 text-left focus-visible:outline-2 focus-visible:outline-accent"
    >
      <ChevronDown aria-hidden className={cn("size-4 shrink-0 self-center text-text-muted transition-transform", collapsed && "-rotate-90")} />
      <h2 className="text-subhead font-semibold text-text">{title}</h2>
      <span className="text-caption font-normal text-text-muted">{facts}</span>
    </button>
  );
}
