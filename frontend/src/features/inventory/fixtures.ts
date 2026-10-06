import type { DeviceRow } from "./ClockCheckDialog";
import type { Inventory } from "./model";

/** The S5 reference trip (stories and tests). */
export const COSTA_RICA: Inventory = {
  summary: { footage_seconds: 22320, clips: 412, photos: 1180, first_date: "2026-07-14", last_date: "2026-07-24", cameras: 5 },
  cameras: [
    { key: "d1", label: "iPhone 16 Pro", kind: "phone", device_id: 1, clips: 188, photos: 1020, limited: 0, files: 1208, footage_seconds: 7080, badges: ["HDR", "Live Photo"], sample_id: 1, clock: null },
    { key: "d2", label: "GoPro HERO12 Black", kind: "actioncam", device_id: 2, clips: 96, photos: 0, limited: 0, files: 131, footage_seconds: 8460, badges: ["Telemetry"], sample_id: 2, clock: { offset_ms: -18_000_000, words: "5 h 00 m ahead" } },
    { key: "d3", label: "Insta360 X4", kind: "360", device_id: 3, clips: 41, photos: 0, limited: 14, files: 41, footage_seconds: 2280, badges: ["360", "Telemetry"], sample_id: 3, clock: { offset_ms: 86_400_000, words: "1 day behind" } },
    { key: "d4", label: "Nikon Z6III", kind: "camera", device_id: 4, clips: 52, photos: 160, limited: 0, files: 212, footage_seconds: 2640, badges: ["Log"], sample_id: 4, clock: null },
    { key: "d5", label: "DJI Mini 4 Pro", kind: "drone", device_id: 5, clips: 35, photos: 0, limited: 0, files: 35, footage_seconds: 1860, badges: [], sample_id: null, clock: null },
  ],
  days: [
    [1, 30, 0, 20, 0], [100, 140, 60, 40, 80], [180, 80, 40, 60, 20], [120, 200, 120, 30, 0], [140, 60, 0, 100, 50],
    [60, 20, 0, 0, 0], [140, 40, 20, 20, 0], [40, 20, 0, 0, 0], [200, 120, 50, 80, 60], [120, 160, 40, 0, 40], [40, 0, 0, 0, 0],
  ].map((mins, i) => ({
    date: `2026-07-${String(14 + i).padStart(2, "0")}`,
    by_camera: Object.fromEntries(mins.map((m, j) => [`d${j + 1}`, m * 60]).filter(([, v]) => (v as number) > 0)),
  })),
  attention: [
    { kind: "unreadable", group: 7, count: 3, reason: "Nikon N-RAW video can't be read.", fix: "Export them as MP4 from NX Studio, then rescan.", example: null },
    { kind: "limited", count: 14, reason: "MosAic will analyze them but can't edit 360 video yet.", fix: "Export flat versions from Insta360 Studio." },
    { kind: "cloud", count: 22, bytes: 48_000_000_000, reason: "They're not on this computer yet.", fix: null },
    { kind: "unreadable", group: 9, count: 1, reason: "It looks damaged.", fix: null, example: "GX050233.MP4" },
  ],
  notes: { chaptered_recordings: 38, live_photos: 96, bursts: 42 },
};

const ev = (dt: string, rt: string) => [{ device_time: dt, reference_time: rt, device_sample: 2, reference_sample: 1 }];

export const DEVICES: DeviceRow[] = [
  { id: 1, label: "iPhone 16 Pro", make: "Apple", model: "iPhone 16 Pro", assets: 1208, clock_offset_ms: 0, suggestion: null },
  {
    id: 2, label: "GoPro HERO12 Black", make: "GoPro", model: "HERO12 Black", assets: 96, clock_offset_ms: 0,
    suggestion: { offset_ms: -18_000_000, verdict: "5 h 00 m ahead", applied: false, reference_device_id: 1, pairs: 6, evidence: ev("2026-07-15T15:43:00", "2026-07-15T10:42:00-06:00") },
  },
  {
    id: 3, label: "Insta360 X4", make: "Insta360", model: "X4", assets: 41, clock_offset_ms: 0,
    suggestion: { offset_ms: 86_400_000, verdict: "24 h 00 m behind", applied: false, reference_device_id: 1, pairs: 4, evidence: ev("2026-07-16T10:13:00", "2026-07-17T10:12:00-06:00") },
  },
  { id: 4, label: "Nikon Z6III", make: "NIKON", model: "Z6III", assets: 212, clock_offset_ms: 0, suggestion: { offset_ms: 20_000, verdict: "on time", applied: true, reference_device_id: 1, pairs: 5, evidence: [] } },
  { id: 5, label: "DJI Mini 4 Pro", make: "DJI", model: "Mini 4 Pro", assets: 35, clock_offset_ms: 0, suggestion: { offset_ms: 0, verdict: "on time", applied: true, reference_device_id: 1, pairs: 3, evidence: [] } },
];
