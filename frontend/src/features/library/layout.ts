import { formatDay, formatDuration, plural } from "@/lib/format";

import type { LibraryGroup, LibraryItem } from "./model";

export type Row = { kind: "header"; group: LibraryGroup; loaded: number } | { kind: "tiles"; group: string; items: LibraryItem[] };

/** Rows for the virtualizer: a header per group, then its tiles in rows of ``cols``. Only
 * loaded clips are laid out; the next page loads as the end comes into view. */
export function buildRows(groups: LibraryGroup[], items: LibraryItem[], cols: number, collapsed: ReadonlySet<string>): Row[] {
  const by = new Map<string, LibraryItem[]>();
  for (const it of items) {
    const list = by.get(it.group);
    if (list) list.push(it);
    else by.set(it.group, [it]);
  }
  const rows: Row[] = [];
  // Every group has its header from the first page on (the page lists them all with their
  // counts); tiles follow as their pages load.
  for (const g of groups) {
    const list = by.get(g.key) ?? [];
    rows.push({ kind: "header", group: g, loaded: list.length });
    if (collapsed.has(g.key)) continue;
    for (let i = 0; i < list.length; i += cols) rows.push({ kind: "tiles", group: g.key, items: list.slice(i, i + cols) });
  }
  return rows;
}

/** The row whose coming into view should load the next page: the header of the first
 * expanded group that still has clips to load. Collapsed groups never ask for more, so
 * collapsing everything cannot page through the whole library (invariant 13). Pages come
 * in group order, so reaching an expanded group may first page through a collapsed one. */
export function wantsMoreAt(rows: Row[], collapsed: ReadonlySet<string>): number | null {
  for (let i = 0; i < rows.length; i++) {
    const r = rows[i]!;
    if (r.kind !== "header" || collapsed.has(r.group.key) || r.loaded >= r.group.count) continue;
    // Its last loaded row (or the header itself when nothing is loaded yet).
    let j = i;
    while (rows[j + 1]?.kind === "tiles") j++;
    return j;
  }
  return null;
}

/** "Day 2 · Arenal / La Fortuna waterfall"; "38 clips · 41 m · 64 photos". */
export function headerText(g: LibraryGroup): { title: string; facts: string } {
  const title = g.day ? `Day ${g.day} · ${g.place || (g.date ? formatDay(g.date) : "")}` : g.label;
  const facts = [
    g.clips ? plural(g.clips, "clip") : null,
    g.footage_seconds ? formatDuration(g.footage_seconds) : null,
    g.photos ? plural(g.photos, "photo") : null,
  ]
    .filter(Boolean)
    .join(" · ");
  return { title, facts };
}

export const GAP = 16;
export const HEADER = 52;
export const CAPTION = 22; // the caption line under a comfortable tile, with its gap
export const MIN_TILE = { comfortable: 220, compact: 160 } as const;
export const MAX_TILES = 60; // S10 / M2 acceptance 4: at most 60 tiles mounted
export const OVERSCAN = 1; // rows beyond each edge of the viewport

export interface GridLayout {
  cols: number;
  tileW: number;
  rowH: number; // a row of tiles, with the gap below it
  mountedTiles: number; // the most tiles the virtualizer can mount at once
}

/** Columns for a grid ``width`` × ``height``: as many as the density's minimum tile width
 * allows, then fewer (larger tiles) until a viewport's worth of rows plus overscan mounts
 * at most ``MAX_TILES`` tiles (ADR 0044). */
export function gridLayout(width: number, height: number, density: keyof typeof MIN_TILE): GridLayout {
  const min = MIN_TILE[density];
  const caption = density === "comfortable" ? CAPTION : 0;
  const measure = (cols: number): GridLayout => {
    const tileW = (width - GAP * (cols - 1)) / cols;
    const rowH = Math.ceil((tileW * 9) / 16 + caption + GAP);
    const rows = Math.ceil(height / rowH) + 1 + 2 * OVERSCAN;
    return { cols, tileW, rowH, mountedTiles: rows * cols };
  };
  let cols = Math.max(1, Math.floor((Math.max(width, min) + GAP) / (min + GAP)));
  let best = measure(cols);
  while (cols > 1 && best.mountedTiles > MAX_TILES) {
    cols -= 1;
    best = measure(cols);
  }
  return best;
}
