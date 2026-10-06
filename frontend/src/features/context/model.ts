/** The trip context as `/projects/{pid}/trip-context` stores it (PRODUCT.md §3; S7). */
export interface Day {
  date: string; // YYYY-MM-DD
  place: string;
  timezone?: string | null;
  notes: string;
}

export interface Person {
  label: string;
  description: string;
}

export interface TripContext {
  trip_name: string;
  home_timezone?: string | null;
  days: Day[];
  people: Person[];
  must_include: string[];
  avoid: string[];
  free_notes: string;
}

export const EMPTY: TripContext = { trip_name: "", days: [], people: [], must_include: [], avoid: [], free_notes: "" };

/** Keys of values a parse added or changed, so S7 can tint them. */
export type Highlights = ReadonlySet<string>;

/** Merges a parsed proposal into what the user has (invariant 10): empty fields are filled,
 * a different parsed note is appended, and nothing the user typed or saved is replaced.
 * Returns the merged context and what changed. */
export function mergeProposal(cur: TripContext, prop: TripContext): { value: TripContext; changed: Set<string> } {
  const changed = new Set<string>();
  const value: TripContext = structuredClone(cur);
  if (prop.trip_name && !cur.trip_name.trim()) {
    value.trip_name = prop.trip_name;
    changed.add("trip_name");
  }
  for (const d of prop.days) {
    const mine = value.days.find((x) => x.date === d.date);
    if (!mine) {
      value.days.push({ ...d });
      changed.add(`day:${d.date}`);
      continue;
    }
    if (d.place && !mine.place.trim()) {
      mine.place = d.place;
      changed.add(`day:${d.date}`);
    }
    if (d.notes && !mine.notes.includes(d.notes)) {
      mine.notes = (mine.notes.trim() ? `${mine.notes}; ${d.notes}` : d.notes).slice(0, 500); // the API's limit
      changed.add(`day:${d.date}`);
    }
    if (d.timezone && !mine.timezone) mine.timezone = d.timezone;
  }
  value.days.sort((a, b) => a.date.localeCompare(b.date));
  for (const p of prop.people) {
    if (!value.people.some((x) => x.label.toLowerCase() === p.label.toLowerCase())) {
      value.people.push({ ...p });
      changed.add(`person:${p.label}`);
    }
  }
  for (const f of ["must_include", "avoid"] as const) {
    for (const t of prop[f]) {
      if (!value[f].some((x) => x.toLowerCase() === t.toLowerCase())) {
        value[f].push(t);
        changed.add(`${f}:${t}`);
      }
    }
  }
  if (prop.free_notes && !cur.free_notes.includes(prop.free_notes)) {
    value.free_notes = (cur.free_notes ? `${cur.free_notes}\n${prop.free_notes}` : prop.free_notes).slice(0, 4000);
    changed.add("free_notes");
  }
  if (prop.home_timezone && !cur.home_timezone) value.home_timezone = prop.home_timezone;
  return { value, changed };
}

/** What is saved: days the user left blank are not stored. */
export function forSave(v: TripContext): TripContext {
  return {
    ...v,
    trip_name: v.trip_name.trim(),
    days: v.days.filter((d) => d.place.trim() || d.notes.trim() || d.timezone),
    free_notes: v.free_notes.trim(),
  };
}
