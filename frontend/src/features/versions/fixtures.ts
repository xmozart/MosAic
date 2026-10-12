import type { CompareData, VersionRow } from "./model";

const RATE = "30000/1001";
const f = (s: number) => Math.round((s * 30000) / 1001);

export const VERSIONS: VersionRow[] = [
  { version: 1, created_at: "2026-07-26T13:41:00", duration: { frames: f(298), rate: RATE }, creator: "ai", reason: "First edit from the wizard", parent_version: null },
  { version: 2, created_at: "2026-07-26T13:58:00", duration: { frames: f(304), rate: RATE }, creator: "ai", reason: "Regenerated “Wildlife”", parent_version: 1 },
  { version: 3, created_at: "2026-07-26T14:12:00", duration: { frames: f(302), rate: RATE }, creator: "user", reason: "Applied: repetition", parent_version: 2 },
];

const change = (c: Partial<CompareData["changes"][number]>): CompareData["changes"][number] => ({
  kind: "replaced",
  ref: "b3#1",
  event_a: "evt_0009",
  event_b: "evt_0009",
  frame: f(43),
  in_version: 3,
  moved: false,
  file_a: null,
  file_b: null,
  frames_a: f(5),
  frames_b: f(5),
  beat_a: "Waterfalls",
  beat_b: "Waterfalls",
  ...c,
});

export const COMPARE: CompareData = {
  a: 2,
  b: 3,
  duration_a: { frames: f(304), rate: RATE },
  duration_b: { frames: f(302), rate: RATE },
  same: false,
  changes: [
    change({ file_a: "IMG_4390.MOV", file_b: "DSC_0932.MOV" }),
    change({ kind: "trimmed", ref: "b3#4", frame: f(88), file_a: "IMG_4472.MOV", file_b: "IMG_4472.MOV", frames_a: f(4), frames_b: f(5.2) }),
    change({ kind: "moved", ref: "b6#3", frame: f(280), moved: true, file_a: "IMG_4512.HEIC", file_b: "IMG_4512.HEIC", beat_a: "The coast", beat_b: "Finale" }),
    change({ kind: "removed", ref: "b5#2", frame: f(130), in_version: 2, event_b: null, file_a: "GX030214.MP4", frames_b: null, beat_b: null }),
  ],
};
