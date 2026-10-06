import type { Estimate } from "@/lib/estimate";

import type { JobInfo, Progress, Settings } from "./model";

const est = (mode: string, wall: [number, number], cost: [number, number], gb: number): Estimate => ({
  mode,
  preset: mode,
  scope: "project",
  videos: 412,
  photos: 1180,
  video_seconds: 22320,
  segments: 2380,
  l2_calls: 210,
  l3_calls: [0, 0],
  cost_usd: cost,
  storage_bytes: gb * 1e9,
  wall_seconds: wall,
  basis: "benchmark",
});

export const ESTIMATES = {
  quick: est("quick", [1800, 2400], [0.8, 1.5], 6),
  balanced: est("balanced", [5400, 6600], [2, 4], 18),
  thorough: est("thorough", [14400, 18000], [6, 10], 19),
};

export const SETTINGS: Settings = {
  "analysis.mode": { value: "balanced", source: "default" },
  "analysis.cost_limit_usd": { value: 10, source: "project" },
  "ai.send_gps": { value: false, source: "default" },
  "analysis.sample_interval": { value: "3", source: "mode" },
  "analysis.tiles": { value: [4, 4], source: "mode" },
  "analysis.forced_max_shot": { value: "60", source: "mode" },
  "analysis.proxy": { value: "720", source: "mode" },
  "analysis.stt_model": { value: null, source: "mode" },
};

const step = (key: string, label: string, state: Progress["steps"][number]["state"], note: string | null, pct = 0) => ({
  key,
  label,
  state,
  done: 0,
  failed: 0,
  total: 1,
  pct,
  note,
});

export const PROGRESS: Progress = {
  job_id: 7,
  kind: "analysis",
  mode: "balanced",
  deepen: null,
  steps: [
    step("look", "Looking through your footage", "done", "412 clips · 1,180 photos"),
    step("previews", "Making previews", "done", "412 of 412"),
    step("shots", "Finding shots", "done", "2,380 shots"),
    step("frames", "Picking frames", "done", "7,440 frames → 4,120 kept"),
    step("speech", "Listening", "done", "3 h 10 m of speech"),
    step("quality", "Measuring quality", "done", null),
    step("scenes", "Understanding scenes", "running", "sheet 96 of 214", 45),
    step("similar", "Grouping similar shots", "pending", null),
    step("library", "Building your library", "pending", null),
  ],
  ready_to_browse: true,
  live: {
    mosaic_id: 3,
    tiles: 16,
    cols: 4,
    rows: 4,
    description: "Helmet cam zipline run over the forest canopy — fast, exciting, some wind noise.",
    file: "GX030211.MP4",
    day: 4,
  },
  failures: {
    count: 2,
    items: [
      { asset_id: 9, file: "GX050233.MP4", stage: "proxy", reason: "couldn't be read" },
      { asset_id: 12, file: "IMG_4488.MOV", stage: "audio", reason: "timed out" },
    ],
  },
  clips: { done: 173, total: 412 },
};

export const JOB: JobInfo = {
  job_id: 7,
  state: "running",
  cost_usd: 1.34,
  cost_limit_usd: 10,
  progress: { pct: 42, eta: { ms: 58 * 60_000, display: "0:58:00" } },
};
