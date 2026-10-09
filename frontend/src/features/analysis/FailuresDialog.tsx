import { Dialog } from "radix-ui";

import { Button } from "@/components/ui/Button";
import { plural } from "@/lib/format";

import type { Progress } from "./model";

/** S9 "Details": the clips that couldn't be processed, with a short reason each. */
export function FailuresDialog({ open, failures, onClose }: { open: boolean; failures: Progress["failures"]; onClose: () => void }) {
  return (
    <Dialog.Root open={open} onOpenChange={(o) => !o && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-scrim" />
        <Dialog.Content
          aria-describedby={undefined}
          className="fixed top-1/2 left-1/2 z-50 flex w-[560px] -translate-x-1/2 -translate-y-1/2 flex-col gap-4 rounded-lg border border-border bg-surface-1 p-6 shadow-[0_24px_64px_rgba(0,0,0,0.5)]"
        >
          <Dialog.Title className="text-heading text-text">{plural(failures.count, "clip")} couldn't be processed</Dialog.Title>
          <ul aria-label="Clips" className="flex max-h-80 flex-col overflow-y-auto rounded-md border border-border">
            {failures.items.map((f, i) => (
              <li key={`${f.asset_id ?? "x"}-${i}`} className="flex items-center gap-3 border-b border-border px-4 py-2 last:border-b-0">
                <span className="mono min-w-0 flex-1 truncate text-timecode-sm text-text">{f.file ?? "Unknown file"}</span>
                <span className="text-small text-text-muted">{f.reason}</span>
              </li>
            ))}
          </ul>
          {failures.count > failures.items.length && (
            <p className="text-caption font-normal text-text-muted">And {plural(failures.count - failures.items.length, "more clip")}.</p>
          )}
          <div className="flex justify-end">
            <Button onClick={onClose}>Close</Button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
