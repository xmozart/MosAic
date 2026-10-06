import type { ClipDetail, LibraryGroup, LibraryItem, LibraryPage } from "./model";

const CAMS = [
  { label: "DJI Mini 4 Pro", kind: "drone" as const },
  { label: "GoPro HERO12 Black", kind: "actioncam" as const },
  { label: "iPhone 16 Pro", kind: "phone" as const },
  { label: "Nikon Z6III", kind: "camera" as const },
];

export function item(i: number, patch: Partial<LibraryItem> = {}): LibraryItem {
  const day = i < 8 ? "2026-07-15" : "2026-07-16";
  return {
    asset_id: i + 1,
    kind: "video",
    status: "ok",
    name: `DCIM/CLIP_${String(i + 1).padStart(4, "0")}.MP4`,
    group: day,
    capture_time: `${day}T${String(9 + (i % 8)).padStart(2, "0")}:00:00-06:00`,
    duration: { ticks: (10 + i * 7) * 90000, tb: "1/90000" },
    segments: 3,
    status_shown: (["USE", "MAYBE", null] as const)[i % 3] ?? null,
    decided_by: i % 3 === 2 ? null : "ai",
    decision: { disposition: null, stars: null, include: null, note: null, live_motion: null, tags: [] },
    sample_id: i + 1,
    caption: ["Drone pushes toward the waterfall", "Hiking down wet stone steps", "Kids splashing in the pool"][i % 3]!,
    shot_type: "wide",
    has_speech: i % 4 === 2,
    similar_count: i % 5 === 0 ? 3 : 0,
    offline: false,
    camera: CAMS[i % CAMS.length]!,
    ...patch,
  };
}

export const GROUPS: LibraryGroup[] = [
  { key: "2026-07-15", label: "Day 2 · 2026-07-15", day: 2, date: "2026-07-15", place: "Arenal / La Fortuna waterfall", count: 8, clips: 8, photos: 0, footage_seconds: 2460 },
  { key: "2026-07-16", label: "Day 3 · 2026-07-16", day: 3, date: "2026-07-16", place: null, count: 4, clips: 4, photos: 0, footage_seconds: 3120 },
];

export function page(n = 12, patch: Partial<LibraryPage> = {}): LibraryPage {
  return { items: Array.from({ length: n }, (_, i) => item(i)), next_cursor: null, groups: GROUPS, rejected_hidden: 2, ...patch };
}

export const DETAIL: ClipDetail = {
  asset_id: 1,
  kind: "video",
  status: "ok",
  name: "DJI_0142.MP4",
  files: 1,
  reason: null,
  fix: null,
  camera: "DJI Mini 4 Pro",
  capture_time: "2026-07-15T10:38:00-06:00",
  duration: { ticks: 48 * 90000, tb: "1/90000" },
  rate: "30000/1001",
  proxy_rate: "30000/1001",
  width: 3840,
  height: 2160,
  badges: ["Log", "4K 30"],
  analysis_only: false,
  position: { day: 2, date: "2026-07-15", index: 1, count: 8, prev: null, next: 2 },
  status_shown: "USE",
  decided_by: "ai",
  ai_status: "USE",
  decision: { disposition: null, stars: null, include: null, note: null, live_motion: null, tags: ["waterfall"] },
  why: { description: "Drone pushes toward the waterfall through dense jungle.", reasons: [] },
  moments: [
    {
      segment_id: 11,
      start: { ticks: 0, tb: "1/90000" },
      end: { ticks: 20 * 90000, tb: "1/90000" },
      usable_start: { ticks: 261000, tb: "1/90000" },
      usable_end: { ticks: 20 * 90000, tb: "1/90000" },
      status: "USE",
      decided_by: "ai",
      ai_status: "USE",
      description: "Falls revealed through the trees",
      interest: "high",
      reasons: [],
      has_speech: false,
      sample_id: 1,
    },
  ],
  quality: { sharpness: "Good", steadiness: "Excellent", exposure: "Good", audio: null },
  transcript: { segments: 0, language: null },
  used_in: [{ edit_id: "E1", name: "5 min cinematic", version: 3 }],
  similar: [{ asset_id: 4, sample_id: 4 }],
  burst: null,
};

export const TRANSCRIPT = [
  {
    id: 1,
    start: { ticks: 108000, tb: "1/90000" },
    end: { ticks: 270000, tb: "1/90000" },
    text: "It's right there! Look!",
    words: [
      { start: { ticks: 108000, tb: "1/90000" }, end: { ticks: 140000, tb: "1/90000" }, word: "It's" },
      { start: { ticks: 140000, tb: "1/90000" }, end: { ticks: 171000, tb: "1/90000" }, word: "right" },
      { start: { ticks: 171000, tb: "1/90000" }, end: { ticks: 220000, tb: "1/90000" }, word: "there!" },
      { start: { ticks: 236250, tb: "1/90000" }, end: { ticks: 270000, tb: "1/90000" }, word: "Look!" },
    ],
  },
];

export const PHOTO: ClipDetail = {
  ...DETAIL,
  asset_id: 7,
  kind: "live_photo",
  name: "IMG_4907.HEIC",
  duration: null,
  rate: null,
  badges: ["Live Photo"],
  moments: [{ ...DETAIL.moments[0]!, sample_id: 7, description: null }],
  burst: {
    items: [1, 2, 3, 4, 5, 6].map((n) => ({ asset_id: 6 + n, sample_id: 6 + n, best: n === 3 })),
  },
};

export const UNSUPPORTED: ClipDetail = {
  ...DETAIL,
  asset_id: 9,
  kind: "unsupported",
  status: "unsupported",
  name: "DSC_0877.NEV",
  reason: "This Nikon N-RAW clip can't be read by MosAic.",
  fix: "Export it as MP4 or MOV from NX Studio (or your editor) into the same folder, then rescan.",
  rate: null,
  moments: [],
  position: null,
  status_shown: null,
  decided_by: null,
  ai_status: null,
};

export const THREE_SIXTY: ClipDetail = { ...DETAIL, asset_id: 10, name: "VID_20260717_101244.insv", analysis_only: true, badges: ["360"] };
