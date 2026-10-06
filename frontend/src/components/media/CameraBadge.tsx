import { CAMERA_ICONS } from "@/lib/cameraIcons";
import type { CameraKind } from "@/lib/domain";

/** Lucide icon plus short label, as drawn on tiles (dark backing over footage). */
export function CameraBadge({ kind, label }: { kind: CameraKind; label: string }) {
  const Icon = CAMERA_ICONS[kind];
  return (
    <span className="inline-flex items-center gap-1 rounded-sm bg-media-chip px-1.5 py-0.5 text-micro font-semibold text-on-media">
      <Icon aria-hidden className="size-3" strokeWidth={1.8} />
      {label}
    </span>
  );
}
