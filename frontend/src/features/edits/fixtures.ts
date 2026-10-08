import type { EditCardData, EditEstimate, Preset } from "./model";

export function card(i: number, patch: Partial<EditCardData> = {}): EditCardData {
  return {
    edit_id: `01JEDIT${String(i).padStart(19, "0")}`,
    display_id: `edt_${String(i).padStart(4, "0")}`,
    name: null,
    title: null,
    request: { duration_s: 300, story: "cinematic_journey", aspect: "16:9", resolution: "1080p" },
    aspect: "16:9",
    resolution: "1080p",
    latest_version: 1,
    versions: 1,
    duration: { frames: 9054, rate: "30000/1001" },
    cover_sample_id: i,
    status: "ready",
    pct: null,
    job_id: null,
    error: null,
    preliminary: false,
    created_at: "2026-07-26T14:20:00",
    ...patch,
  };
}

export const CARDS: EditCardData[] = [
  card(1, { name: "Costa Rica — 5 min cinematic", resolution: "4k", versions: 3, latest_version: 3, status: "final" }),
  card(2, {
    name: "Costa Rica — 60 s reel",
    aspect: "9:16",
    request: { duration_s: 60, story: "high_energy_montage", aspect: "9:16" },
    duration: { frames: 1768, rate: "30000/1001" },
    status: "preview",
  }),
  card(3, { name: "Wildlife cut", versions: 2, latest_version: 2, duration: { frames: 5335, rate: "30000/1001" }, status: "generating", pct: 64 }),
  card(4, {
    name: "Family highlights",
    duration: { frames: 5695, rate: "30000/1001" },
    status: "ready",
    preliminary: true,
    created_at: "2026-07-20T09:00:00",
  }),
];

const LABELS: [string, string, boolean][] = [
  ["cinematic_journey", "Cinematic journey", true],
  ["chronological_diary", "Chronological diary", true],
  ["adventure_highlights", "Adventure highlights", true],
  ["family_memories", "Family memories", true],
  ["wildlife", "Wildlife", true],
  ["funny_moments", "Funny moments", true],
  ["high_energy_montage", "High-energy montage", true],
  ["people_first", "People first", false],
  ["nature", "Nature", false],
  ["food_culture", "Food and culture", false],
  ["city", "City", false],
  ["road_trip", "Road trip", false],
  ["relaxed", "Relaxed", false],
  ["documentary", "Documentary", false],
  ["drone_showcase", "Drone showcase", false],
  ["event_recap", "Event recap", false],
];

export const PRESETS: Preset[] = LABELS.map(([id, label, featured]) => ({ id, label, featured, description: `${label} story.` }));

export const ESTIMATE: EditEstimate = {
  candidates: 214,
  target: { frames: 5395, rate: "30000/1001" },
  usable_seconds: 2410,
  enough_footage: true,
  reuses_plan: false,
  cost_usd: [0.25, 0.55],
  wall_seconds: [40, 240],
  preliminary: false,
  analysis_pct: null,
};
