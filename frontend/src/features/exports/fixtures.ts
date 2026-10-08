import { renderRow } from "@/features/preview/fixtures";
import type { RenderRow } from "@/lib/renders";

export const ROWS: RenderRow[] = [
  renderRow(5, { kind: "final", label: "Web · 4K", width: 3840, height: 2160, status: "rendering", pct: 58, size_bytes: null, seconds: null, file: null, finished_at: null }),
  renderRow(4, {
    edit_name: "Costa Rica — 60 s reel",
    version: 1,
    kind: "final",
    label: "Web · 1080p vertical",
    width: 1080,
    height: 1920,
    status: "queued",
    size_bytes: null,
    seconds: null,
    file: null,
    finished_at: null,
  }),
  renderRow(3, { kind: "final", version: 2, label: "Web · 1080p", width: 1920, height: 1080, size_bytes: 17_600_000_000, seconds: 552 }),
  renderRow(2, { edit_name: "Wildlife cut", version: 1, kind: "final", label: "Web · 1080p", status: "failed", pct: 30, error: "encoder: h264_videotoolbox failed (-12902)", size_bytes: null, seconds: null, file: null }),
  renderRow(1, { edit_name: "Family highlights", version: 1, kind: "final", label: "Web · 1080p", size_bytes: 640_000_000, seconds: 280 }),
];
