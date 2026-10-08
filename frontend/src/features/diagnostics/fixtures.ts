import type { TaskDetail, TaskRow } from "./model";

function row(id: number, patch: Partial<TaskRow>): TaskRow {
  return {
    task_id: id,
    job_id: 7,
    job_kind: "analysis",
    project_id: "P1",
    kind: "media.probe",
    stage: "probe",
    input: null,
    status: "done",
    attempts: 1,
    max_attempts: 3,
    duration_ms: 400,
    created_at: "2026-07-26T14:02:10",
    finished_at: "2026-07-26T14:02:11",
    tool: "ffprobe",
    tokens_in: null,
    tokens_out: null,
    cost_usd: null,
    ...patch,
  };
}

export const ROWS: TaskRow[] = [
  row(6, { kind: "library.vision", input: "contact sheet 96", tool: "anthropic · claude-haiku-4-5", duration_ms: 4200, tokens_in: 1840, tokens_out: 610, cost_usd: 0.004 }),
  row(5, { kind: "media.proxy", input: "GX030211.MP4", tool: "ffmpeg", duration_ms: 38100 }),
  row(4, { kind: "audio.analyze", input: "IMG_4472.MOV", tool: "whisper", duration_ms: 2900 }),
  row(3, { kind: "media.probe", input: "GX050233.MP4", status: "failed", attempts: 2 }),
  row(2, { kind: "library.vision", input: "contact sheet 97", status: "leased", tool: "anthropic · claude-haiku-4-5", duration_ms: null }),
  row(1, { kind: "media.visual", input: "DJI_0188.MP4", status: "ready", tool: "frames · numpy", duration_ms: null }),
];

export const FAILED: TaskDetail = {
  ...ROWS[3]!,
  error: "[mov,mp4] moov atom not found\nDay_05/GX050233.MP4: Invalid data found when processing input",
  params: { asset_id: 233 },
  result: {},
  events: [
    { event: "leased", worker_id: "io-2", detail: null, at: "2026-07-26T14:02:11" },
    { event: "failed", worker_id: "io-2", detail: "moov atom not found", at: "2026-07-26T14:02:11" },
  ],
  started_at: "2026-07-26T14:02:11",
  worker: "io-2",
  can_retry: true,
  can_skip: true,
};

export const DONE_AI: TaskDetail = {
  ...ROWS[0]!,
  error: null,
  params: { segment_ids: [12, 13, 14], api_key: "[redacted]" },
  result: {},
  events: [],
  started_at: "2026-07-26T14:01:58",
  worker: "ai_api-1",
  can_retry: false,
  can_skip: false,
};

export const RUNNING: TaskDetail = { ...DONE_AI, ...ROWS[4]!, error: null, params: {}, result: {}, events: [], started_at: "2026-07-26T14:02:30", worker: "ai_api-2", can_retry: false, can_skip: false };
