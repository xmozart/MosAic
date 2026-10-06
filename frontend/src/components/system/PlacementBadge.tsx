import { Archive, Cloud, Folder, HardDrive, Server } from "lucide-react";

export type Placement = "in_folder" | "split_nas" | "split_icloud" | "separate" | "external_drive";

const LABEL: Record<Placement, [string, typeof Folder]> = {
  in_folder: ["In folder", Folder],
  split_nas: ["Split · NAS", Server],
  split_icloud: ["Split · iCloud", Cloud],
  separate: ["Stored separately", Archive], // not Lock: locks mean user decisions here
  external_drive: ["External drive", HardDrive],
};

/** Where the project's data lives (COMPONENTS.md PlacementBadge; ADR 0022). */
export function PlacementBadge({ placement }: { placement: Placement }) {
  const [label, Icon] = LABEL[placement];
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full border border-border px-2 py-0.5 text-caption text-text-muted">
      <Icon aria-hidden className="size-3.5" />
      {label}
    </span>
  );
}
