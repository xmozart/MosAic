import { Aperture, Camera, Drone, Image, Orbit, Smartphone } from "lucide-react";

import type { CameraKind } from "@/lib/domain";

const ICONS: Record<CameraKind, typeof Camera> = {
  phone: Smartphone,
  actioncam: Camera,
  "360": Orbit,
  drone: Drone,
  camera: Aperture,
  photo: Image,
};

/** Lucide icon plus short label, as drawn on tiles (dark backing over footage). */
export function CameraBadge({ kind, label }: { kind: CameraKind; label: string }) {
  const Icon = ICONS[kind];
  return (
    <span className="inline-flex items-center gap-1 rounded-sm bg-media-chip px-1.5 py-0.5 text-micro font-semibold text-on-media">
      <Icon aria-hidden className="size-3" strokeWidth={1.8} />
      {label}
    </span>
  );
}
