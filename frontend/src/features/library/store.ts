import { create } from "zustand";

import type { Filters, Grouping } from "./model";
import type { Density } from "@/lib/domain";

/** The library's view state for one project (S10): kept while moving between screens, not
 * across reloads (density is remembered per browser as a convenience). */
interface LibraryView {
  pid: string | null;
  group: Grouping;
  density: Density;
  filters: Filters;
  showRejected: boolean;
  selection: number[]; // asset ids, in selection order
  anchor: number | null; // Shift-click range anchor
  focus: number | null; // the tile the keys act on (and the inspector shows)
  inspector: boolean;
  collapsed: string[]; // group keys
  forProject: (pid: string) => void;
  set: (patch: Partial<Omit<LibraryView, "set" | "forProject">>) => void;
  setFilters: (patch: Partial<Filters>) => void;
  clearFilters: () => void;
}

const DENSITY_KEY = "mosaic.library.density";

function savedDensity(): Density {
  try {
    return localStorage.getItem(DENSITY_KEY) === "compact" ? "compact" : "comfortable";
  } catch {
    return "comfortable";
  }
}

export const useLibraryView = create<LibraryView>((set, get) => ({
  pid: null,
  group: "day",
  density: savedDensity(),
  filters: {},
  showRejected: false,
  selection: [],
  anchor: null,
  focus: null,
  inspector: true,
  collapsed: [],
  forProject: (pid) => {
    if (get().pid === pid) return;
    set({ pid, group: "day", filters: {}, showRejected: false, selection: [], anchor: null, focus: null, collapsed: [] });
  },
  set: (patch) => {
    if (patch.density) {
      try {
        localStorage.setItem(DENSITY_KEY, patch.density);
      } catch {
        // storage unavailable: the choice lasts for this visit
      }
    }
    set(patch);
  },
  clearFilters: () => set({ filters: {}, showRejected: false, selection: [], anchor: null }),
  setFilters: (patch) =>
    set((s) => {
      const filters = { ...s.filters, ...patch };
      for (const k of Object.keys(filters) as (keyof Filters)[]) if (filters[k] === undefined) delete filters[k];
      return { filters, selection: [], anchor: null };
    }),
}));
