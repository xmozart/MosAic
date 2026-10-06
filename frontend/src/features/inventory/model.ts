import type { CameraKind } from "@/lib/domain";

/** `GET /projects/{pid}/inventory` (API_MAP; ADR 0038). */
export interface Inventory {
  summary: {
    footage_seconds: number;
    clips: number;
    photos: number;
    first_date: string | null;
    last_date: string | null;
    cameras: number;
  };
  cameras: Camera[];
  days: { date: string; by_camera: Record<string, number> }[];
  attention: Attention[];
  notes: { chaptered_recordings: number; live_photos: number; bursts: number };
}

export interface Camera {
  key: string;
  label: string;
  kind: CameraKind;
  device_id: number | null;
  clips: number;
  photos: number;
  limited: number;
  files: number;
  footage_seconds: number;
  badges: string[];
  sample_id: number | null;
  clock: { offset_ms: number; words: string } | null;
}

export interface Attention {
  kind: "unreadable" | "limited" | "cloud";
  count: number;
  reason: string | null;
  fix: string | null;
  group?: number;
  example?: string | null;
  bytes?: number;
}

/** A stable id for a Needs-attention row (Ignore / Skip remember it). */
export function attentionKey(a: Attention): string {
  return a.kind === "unreadable" ? `unreadable:${a.group ?? ""}` : a.kind;
}
