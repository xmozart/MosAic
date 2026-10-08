import type { Settings } from "@/features/analysis/model";
import type { TripContext } from "@/features/context/model";

import type { DeviceSummary, StorageData } from "./model";

export const SETTINGS: Settings = {
  "analysis.mode": { value: "balanced", source: "project" },
  "analysis.cost_limit_usd": { value: 10, source: "user" },
  "ai.send_gps": { value: false, source: "default" },
};

export const DEVICES: DeviceSummary[] = [
  { id: 1, label: "iPhone 16 Pro", make: "Apple", model: "iPhone 16 Pro", assets: 412, clock_offset_ms: 0, lut_path: null },
  { id: 2, label: "GoPro HERO12 Black", make: "GoPro", model: "HERO12 Black", assets: 188, clock_offset_ms: 3_600_000, lut_path: null },
  { id: 3, label: "DJI Mini 4 Pro", make: "DJI", model: "Mini 4 Pro", assets: 64, clock_offset_ms: -120_000, lut_path: "/luts/DJI_D-Log_M_to_Rec709.cube" },
];

export const CONTEXT: TripContext = {
  trip_name: "Costa Rica 2026",
  days: [
    { date: "2026-07-14", place: "San José", notes: "" },
    { date: "2026-07-24", place: "Manuel Antonio", notes: "" },
  ],
  people: [{ label: "Leo", description: "our son" }],
  must_include: ["toucan", "zipline"],
  avoid: [],
  free_notes: "",
};

const GB = 1_000_000_000;
export const STORAGE: StorageData = {
  folder: "Costa_Rica_2026/MosAic",
  total_bytes: 18.9 * GB,
  regenerable_bytes: 14.6 * GB,
  groups: [
    { id: "previews", label: "Previews", bytes: 14.2 * GB, regenerable: true },
    { id: "render_cache", label: "Render cache", bytes: 0.4 * GB, regenerable: true },
    { id: "frames", label: "Frames & contact sheets", bytes: 1.1 * GB, regenerable: false },
    { id: "renders", label: "Renders", bytes: 3.02 * GB, regenerable: false },
    { id: "analysis", label: "Analysis", bytes: 0.18 * GB, regenerable: false },
  ],
  clearing_job_id: null,
};
