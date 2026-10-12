import type { Alternative, BoardBeat, DraftState, ShotMedia, TimelineEvent } from "./model";

// S16's mockup trip: seven beats, a locked one (Wildlife) and one regenerating.
const RATE = "30000/1001";
const BEATS: [string, string, [string, number][]][] = [
  ["Arrival", "Land, the long drive, first glimpse of Arenal", [["arrival", 3], ["journey", 5], ["texture", 4], ["reveal", 6], ["establishing", 5], ["journey", 4], ["detail", 5]]],
  ["Into the jungle", "Establish the rainforest and the family's excitement", [["establishing", 7], ["detail", 4], ["journey", 5], ["reaction", 4], ["texture", 5], ["hero", 6], ["detail", 4], ["reaction", 5], ["journey", 8]]],
  ["Waterfalls", "La Fortuna falls and Río Celeste", [["hero", 6], ["hero", 5], ["detail", 4], ["reaction", 5], ["texture", 6], ["establishing", 8], ["detail", 5], ["reaction", 5]]],
  ["Wildlife", "Toucan, sloth, monkeys, tarantula", [["hero", 4], ["reaction", 4], ["detail", 5], ["action", 3], ["hero", 6], ["detail", 5]]],
  ["Up in the canopy", "Hanging bridges and Maya's first zipline", [["establishing", 6], ["action", 5], ["reaction", 4], ["pov", 7]]],
  ["The coast", "Beach, catamaran, dolphins", [["establishing", 6], ["hero", 4], ["action", 5], ["photo", 4], ["texture", 5], ["reaction", 4]]],
  ["Finale", "Sunset, family photo, drone pull-away", [["hero", 6], ["photo", 4], ["ending", 8]]],
];
const REASONS = [
  "Three-toed sloth slowly turning its head — sharp telephoto detail that slows the pace after the toucan reaction.",
  "The first wide view of the volcano through the windscreen: it tells you where you are.",
  "Maya laughing on the bridge; the reaction the beat is about.",
];

const fps = 30000 / 1001;
let seg = 1000;
const beats: BoardBeat[] = [];
const events: TimelineEvent[] = [];
const media: Record<string, ShotMedia> = {};
BEATS.forEach(([title, intent, shots], bi) => {
  const beat_id = `b${bi + 1}`;
  beats.push({
    beat_id,
    title,
    intent,
    share_percent: 14,
    shots: shots.map(([role, s], si) => {
      const ref = `${beat_id}#${si}`;
      const segment_id = `seg_${String(++seg).padStart(6, "0")}`;
      media[segment_id] = {
        sample_id: seg,
        file: role === "photo" ? `IMG_${seg}.HEIC` : `DSC_${seg}.MOV`,
        day: Math.min(12, 1 + Math.floor((bi * 12) / BEATS.length)),
        photo: role === "photo",
        asset: seg,
        range: { start: { ticks: 0, tb: "1/90000" }, end: { ticks: s * 90000, tb: "1/90000" } },
      };
      // The last shot of the Arrival beat was dropped to fit the length.
      if (!(bi === 0 && si === shots.length - 1)) {
        events.push({
          event_id: `evt_${String(events.length).padStart(4, "0")}`,
          kind: role === "photo" ? "still" : "video",
          beat_id,
          duration: { frames: Math.round(s * fps), rate: RATE },
          origin: { selection_ref: ref },
        });
      }
      return { ref, segment_id, role, length: "medium", reason: REASONS[(bi + si) % REASONS.length]!, locked: bi === 3, absorbed_by: null };
    }),
  });
});
const total = events.reduce((n, e) => n + e.duration.frames, 0);

export const DRAFT: DraftState = {
  base_version: 2,
  dirty: false,
  ops: 0,
  can_undo: false,
  can_redo: false,
  board: { title: "Costa Rica 2026", beats },
  duration: { frames: total, rate: RATE },
  target: { frames: Math.round(total * 0.98), rate: RATE },
  tolerance: { frames: Math.round(15 * fps), rate: RATE },
  timeline: { tracks: [{ events }] },
  metrics: { locks: { over_frames: 0, frames: 0, shots: 6 } },
  media,
  regenerating: [],
  regenerating_scope: null,
};

export const ALTERNATIVES: Alternative[] = [
  { segment_id: "seg_002001", sample_id: 3, file: "DSC_1046.MOV", day: 9, photo: false, why_not: "Softer focus on the face", line: "" },
  { segment_id: "seg_002002", sample_id: 5, file: "DSC_0899.MOV", day: 9, photo: false, why_not: "Howler monkey — similar pace, less rare", line: "" },
];
