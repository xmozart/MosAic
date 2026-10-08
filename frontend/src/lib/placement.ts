import type { Placement } from "@/components/system/PlacementBadge";

/** The badge for a project's placement and its folder's storage class (ARCHITECTURE §4).
 * A split project on a local disk (a server that keeps live databases in its own data,
 * ADR 0055) is "stored separately", never "NAS". */
export function placementOf(r: { placement: string; fs_class: string }): Placement {
  if (r.placement === "split") {
    if (r.fs_class === "cloud_synced") return "split_icloud";
    if (r.fs_class === "network") return "split_nas";
    return "separate";
  }
  if (r.placement === "external") return "separate";
  return "in_folder";
}
