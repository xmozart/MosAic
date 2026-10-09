import { Dialog } from "radix-ui";
import { useState } from "react";

import { Button } from "@/components/ui/Button";
import { TextField } from "@/components/ui/TextField";

/** Desktop folder choice in the browser UI until the native picker (Tauri, M3): the
 * folder's full path (ADR 0039). */
export function PathDialog(p: { open: boolean; error?: string | null; onPick: (path: string) => void; onCancel: () => void }) {
  const [path, setPath] = useState("");
  return (
    <Dialog.Root open={p.open} onOpenChange={(o) => !o && p.onCancel()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-scrim" />
        <Dialog.Content
          aria-describedby={undefined}
          className="fixed top-1/2 left-1/2 z-50 flex w-[560px] -translate-x-1/2 -translate-y-1/2 flex-col gap-4 rounded-lg border border-border bg-surface-1 p-6 shadow-[0_24px_64px_rgba(0,0,0,0.5)]"
        >
          <Dialog.Title className="text-heading text-text">Open footage folder</Dialog.Title>
          <form
            className="flex flex-col gap-4"
            onSubmit={(e) => {
              e.preventDefault();
              if (path.trim()) p.onPick(path.trim());
            }}
          >
            <TextField
              label="Folder"
              mono
              autoFocus
              placeholder="/Users/you/Movies/Costa_Rica_2026"
              value={path}
              onChange={(e) => setPath(e.target.value)}
              error={p.error ?? undefined}
              hint="Paste the folder's full path. Nothing in it will be moved or changed."
            />
            <div className="flex justify-end gap-2">
              <Button variant="ghost" onClick={p.onCancel}>
                Cancel
              </Button>
              <Button type="submit" variant="primary" disabled={!path.trim()}>
                Continue
              </Button>
            </div>
          </form>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
