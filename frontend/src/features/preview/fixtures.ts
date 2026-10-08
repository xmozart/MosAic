import type { RenderRow } from "@/lib/renders";

import type { Beat, EditVersionData, ReportData, TimelineEvent } from "./model";

const RATE = "30000/1001";
export const BEATS: Beat[] = [
  { beat_id: "b1", title: "Arrival" },
  { beat_id: "b2", title: "Into the jungle" },
  { beat_id: "b3", title: "Wildlife" },
  { beat_id: "b4", title: "Finale" },
];
const LENGTHS = [150, 120, 180, 90, 140, 160, 110, 200, 130, 150, 170, 200]; // 1,800 frames

export const EVENTS: TimelineEvent[] = (() => {
  let at = 0;
  return LENGTHS.map((n, i) => {
    const e: TimelineEvent = {
      event_id: `evt_${String(i + 1).padStart(4, "0")}`,
      asset_id: `ast_${String(i + 1).padStart(4, "0")}`,
      segment_id: `seg_${String(100 + i).padStart(6, "0")}`,
      beat_id: BEATS[Math.min(3, Math.floor(i / 3))]!.beat_id,
      role: ["opener", "establishing", "hero", "b_roll", "reaction", "dialogue"][i % 6]!,
      timeline_in: { frames: at, rate: RATE },
      timeline_out: { frames: at + n, rate: RATE },
    };
    at += n;
    return e;
  });
})();
const TOTAL = LENGTHS.reduce((a, b) => a + b, 0);

export function renderRow(id: number, patch: Partial<RenderRow> = {}): RenderRow {
  return {
    render_id: id,
    edit_id: "01JEDIT0000000000000000001",
    edit_name: "Costa Rica — 5 min cinematic",
    display_id: "edt_0001",
    version: 3,
    cover_sample_id: 1,
    kind: "preview",
    label: "Preview · 720p",
    width: 1280,
    height: 720,
    status: "done",
    pct: null,
    error: null,
    job_id: 10 + id,
    size_bytes: 84_000_000,
    seconds: 95,
    file: `v003-preview-r${String(id).padStart(4, "0")}.mp4`,
    created_at: "2026-07-26T14:20:00",
    finished_at: "2026-07-26T14:21:35",
    ...patch,
  };
}

export const EDIT: EditVersionData = {
  edit_id: "01JEDIT0000000000000000001",
  display_id: "edt_0001",
  name: "Costa Rica — 5 min cinematic",
  version: 3,
  request: { duration_s: 60, aspect: "16:9", resolution: "1080p" },
  rate: RATE,
  beats: BEATS,
  timeline: { duration: { frames: TOTAL, rate: RATE }, title: "Costa Rica", tracks: [{ events: EVENTS }] },
  facts: {
    duration: { frames: TOTAL, rate: RATE },
    target: { frames: 1800, rate: RATE },
    tolerance: { frames: 90, rate: RATE },
    shots: EVENTS.length,
    photos: 2,
    beats: BEATS.length,
    days_used: 9,
    days_available: 11,
    ai_cost_usd: 0.38,
  },
  renders: [renderRow(2)],
};

export const REPORT: ReportData = {
  version: 3,
  events: EVENTS.map((e, i) => ({
    event_id: e.event_id,
    beat_id: e.beat_id,
    role: e.role,
    segment_id: e.segment_id,
    source_file: `DCIM/100APPLE/IMG_${4470 + i}.MOV`,
    timeline_in: e.timeline_in,
    timeline_out: e.timeline_out,
    reason: ["Strong opener: wide shot of the bay at sunrise.", "Shows the trail into the forest.", "The clearest look at the sloth.", "Kids laughing at the waterfall."][i % 4]!,
    description: i % 2 ? "Waterfall with mist, two people in the foreground" : null,
  })),
  not_used: [
    { selection_ref: "sel_0020", segment_id: "seg_000300", beat_id: "b3", reason: "Alternative to evt_0007: the toucan is further away" },
  ],
  rejected: {
    total: 3,
    offset: 0,
    items: [
      { segment_id: "seg_000400", asset_id: "ast_0040", source: "user", whole_clip: true, words: ["You rejected the whole clip"], source_file: "GOPRO/GX010231.MP4", camera: "GoPro HERO12 Black" },
      { segment_id: "seg_000401", asset_id: "ast_0041", source: "ai", whole_clip: false, words: ["Very shaky", "Lens covered"], source_file: "GOPRO/GX010232.MP4", camera: "GoPro HERO12 Black" },
    ],
  },
};
