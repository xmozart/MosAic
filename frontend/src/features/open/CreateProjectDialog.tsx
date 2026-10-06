import { CircleCheck } from "lucide-react";
import { Dialog } from "radix-ui";
import { useState } from "react";

import { Button } from "@/components/ui/Button";
import { TextField } from "@/components/ui/TextField";
import { cn } from "@/lib/cn";
import { plural } from "@/lib/format";

export interface PreviewData {
  where: string; // the folder, as the user knows it (mono)
  name: string;
  placement: "in_folder" | "split" | "external";
  counts: { videos: number; photos: number; folders: number; complete: boolean };
}

const PLACEMENTS = [
  {
    key: "in_folder",
    title: "Local drive (this folder)",
    body: "Analysis files will be kept in a MosAic folder inside this folder.",
  },
  {
    key: "split",
    title: "If on a network drive or iCloud",
    body: "MosAic keeps working files on this computer and saves a compact copy into the folder.",
  },
  {
    key: "external",
    title: "If the folder is read-only",
    body: "MosAic can't write here, so it stores the project on this computer.",
  },
] as const;

/** S4b confirm (620 px): what was found, the name, where working files go, the promise. */
export function CreateProjectDialog(p: {
  open: boolean;
  preview: PreviewData;
  busy?: boolean;
  error?: string | null;
  onCreate: (name: string) => void;
  onCancel: () => void;
}) {
  const [name, setName] = useState(p.preview.name);
  const c = p.preview.counts;
  const found = [plural(c.videos, "video"), plural(c.photos, "photo")].join(" and ");
  const empty = c.videos === 0 && c.photos === 0;
  return (
    <Dialog.Root open={p.open} onOpenChange={(o) => !o && p.onCancel()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-scrim" />
        <Dialog.Content
          aria-describedby={undefined}
          className="fixed top-1/2 left-1/2 z-50 flex w-[620px] -translate-x-1/2 -translate-y-1/2 flex-col gap-5 rounded-[16px] border border-border bg-surface-1 p-6 shadow-[0_24px_64px_rgba(0,0,0,0.5)]"
        >
          <Dialog.Title className="text-heading text-text">Create project</Dialog.Title>
          <div className="flex flex-col gap-1">
            <p className="mono truncate text-timecode text-text">{p.preview.where}</p>
            <p className="text-small text-text-muted">
              {empty
                ? "No videos or photos here."
                : `Found ${found}${c.complete ? "" : "+"} in ${plural(Math.max(1, c.folders + 1), "folder")}`}
            </p>
          </div>
          {!empty && (
            <>
              <TextField label="Project name" value={name} onChange={(e) => setName(e.target.value)} />
              <div className="flex flex-col gap-2">
                <span className="text-caption text-text-muted">Where MosAic keeps its working files</span>
                {PLACEMENTS.map((pl) => {
                  const on = pl.key === p.preview.placement;
                  return (
                    <div
                      key={pl.key}
                      aria-current={on ? "true" : undefined}
                      className={cn(
                        "rounded-md border px-3.5 py-2.5",
                        on ? "border-accent bg-accent-soft" : "border-border opacity-70",
                      )}
                    >
                      <p className="text-small text-text">{pl.title}</p>
                      <p className="text-caption font-normal text-text-muted">{pl.body}</p>
                    </div>
                  );
                })}
              </div>
              <p className="flex items-center gap-2 rounded-md bg-use/10 px-3.5 py-2.5 text-small text-use">
                <CircleCheck aria-hidden className="size-4" />
                Original footage stays where it is and will not be modified.
              </p>
            </>
          )}
          {p.error && <p role="alert" className="text-small text-reject">{p.error}</p>}
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={p.onCancel}>
              {empty ? "Choose another" : "Cancel"}
            </Button>
            {!empty && (
              <Button variant="primary" disabled={p.busy || !name.trim()} onClick={() => p.onCreate(name.trim())}>
                Create project
              </Button>
            )}
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
