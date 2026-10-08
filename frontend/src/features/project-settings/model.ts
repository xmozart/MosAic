import type { Section } from "@/components/system/SectionNav";

export const SECTIONS: Section[] = [
  { id: "general", label: "General" },
  { id: "analysis", label: "Analysis" },
  { id: "devices", label: "Devices" },
  { id: "context", label: "Trip context" },
  { id: "storage", label: "Storage" },
  { id: "danger", label: "Danger zone", danger: true },
];

/** `GET /projects/{pid}/storage` (ADR 0051). */
export interface StorageData {
  folder: string;
  total_bytes: number;
  regenerable_bytes: number;
  groups: { id: string; label: string; bytes: number; regenerable: boolean }[];
  clearing_job_id: number | null;
}

export interface DeviceSummary {
  id: number;
  label: string | null;
  make: string | null;
  model: string | null;
  assets: number;
  clock_offset_ms: number;
  lut_path: string | null;
}

