import { Aperture, Camera, Drone, Image, Orbit, Smartphone } from "lucide-react";

import type { CameraKind } from "@/lib/domain";

/** The Lucide icon for each kind of camera (tiles, S5 camera cards). */
export const CAMERA_ICONS: Record<CameraKind, typeof Camera> = {
  phone: Smartphone,
  actioncam: Camera,
  "360": Orbit,
  drone: Drone,
  camera: Aperture,
  photo: Image,
};
