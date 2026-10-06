import { useInfiniteQuery } from "@tanstack/react-query";
import { Dialog } from "radix-ui";

import { api } from "@/api/client";
import { Button } from "@/components/ui/Button";
import { formatBytes } from "@/lib/format";

import type { Attention } from "./model";

interface Page {
  items: { id: number; path: string; bytes: number }[];
  next_after: number | null;
}

/** S5 "Show files": the files behind one Needs-attention row, relative to the project
 * folder (`GET /inventory/files`, ADR 0040). */
export function FilesDialog({ pid, row, title, onClose }: { pid: string; row: Attention | null; title: string; onClose: () => void }) {
  const files = useInfiniteQuery({
    queryKey: ["inventory-files", pid, row?.kind, row?.group],
    enabled: row !== null,
    initialPageParam: undefined as number | undefined,
    getNextPageParam: (last: Page) => last.next_after ?? undefined,
    queryFn: async ({ pageParam }) =>
      (
        await api.GET("/api/projects/{pid}/inventory/files", {
          params: { path: { pid }, query: { kind: row!.kind, group: row!.group, after: pageParam } },
        })
      ).data as unknown as Page,
  });
  const items = files.data?.pages.flatMap((p) => p.items) ?? [];
  return (
    <Dialog.Root open={row !== null} onOpenChange={(o) => !o && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-scrim" />
        <Dialog.Content
          aria-describedby={undefined}
          className="fixed top-1/2 left-1/2 z-50 flex w-[640px] -translate-x-1/2 -translate-y-1/2 flex-col gap-4 rounded-[16px] border border-border bg-surface-1 p-6 shadow-[0_24px_64px_rgba(0,0,0,0.5)]"
        >
          <Dialog.Title className="text-heading text-text">{title}</Dialog.Title>
          {row?.reason && <p className="text-small text-text-muted">{[row.reason, row.fix].filter(Boolean).join(" ")}</p>}
          <ul aria-label="Files" className="flex max-h-80 flex-col overflow-y-auto rounded-md border border-border">
            {files.isLoading && <li className="p-4 text-small text-text-muted">Looking…</li>}
            {items.map((f) => (
              <li key={f.id} className="flex items-center gap-3 border-b border-border px-4 py-2 last:border-b-0">
                <span className="mono min-w-0 flex-1 truncate text-timecode-sm text-text" title={f.path}>
                  {f.path}
                </span>
                <span className="mono text-timecode-sm text-text-muted">{formatBytes(f.bytes)}</span>
              </li>
            ))}
          </ul>
          <div className="flex items-center gap-2">
            {files.hasNextPage && (
              <Button variant="ghost" disabled={files.isFetchingNextPage} onClick={() => void files.fetchNextPage()}>
                Show more
              </Button>
            )}
            <Button className="ml-auto" onClick={onClose}>
              Close
            </Button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
