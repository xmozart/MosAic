import { useQuery } from "@tanstack/react-query";
import { ChevronRight, Folder } from "lucide-react";
import { Dialog } from "radix-ui";
import { useEffect, useId, useState, type KeyboardEvent } from "react";

import { api } from "@/api/client";
import { Button } from "@/components/ui/Button";
import { cn } from "@/lib/cn";
import { plural } from "@/lib/format";

export interface FolderPick {
  root: number;
  path: string; // relative to the root ("" is the root itself)
}

interface Counts {
  videos: number;
  photos: number;
  complete: boolean;
}
interface Entry {
  name: string;
  path: string;
  counts: Counts | null;
  has_project: boolean;
}
interface Listing {
  root: { id: number; label: string };
  path: string;
  crumbs: { name: string; path: string }[];
  items: Entry[];
}

function countLine(c: Counts | null): string {
  if (!c) return "";
  const parts = [c.videos ? plural(c.videos, "video") : null, c.photos ? plural(c.photos, "photo") : null].filter(Boolean);
  const text = parts.join(" · ") || "No videos or photos";
  return c.complete ? text : `${text}+`;
}

export interface FolderBrowserViewProps {
  roots: { id: number; label: string }[];
  root: number | null;
  listing: Listing | undefined;
  selected: string | null;
  loading?: boolean;
  onRoot: (id: number) => void;
  onEnter: (path: string) => void;
  onSelect: (path: string | null) => void;
  onOpen: () => void;
  onCancel: () => void;
}

/** S4 server folder browser: media-root pill, breadcrumbs, folder rows (counts, project
 * badge). ↑/↓ select · → enter · ← up · Enter open. Presentational (stories, tests). */
export function FolderBrowserView(p: FolderBrowserViewProps) {
  const items = p.listing?.items ?? [];
  const index = items.findIndex((i) => i.path === p.selected);
  const idBase = useId();
  const optionId = (i: number) => `${idBase}-o${i}`;
  useEffect(() => {
    if (index >= 0) document.getElementById(`${idBase}-o${index}`)?.scrollIntoView?.({ block: "nearest" });
  }, [idBase, index]);
  const onKey = (e: KeyboardEvent) => {
    if (!p.listing) return;
    if (e.key === "ArrowDown") p.onSelect(items[Math.min(items.length - 1, index + 1)]?.path ?? null);
    else if (e.key === "ArrowUp") p.onSelect(items[Math.max(0, index - 1)]?.path ?? null);
    else if (e.key === "ArrowRight" && p.selected !== null) p.onEnter(p.selected);
    else if (e.key === "ArrowLeft") {
      const crumbs = p.listing.crumbs;
      if (crumbs.length > 1) p.onEnter(crumbs[crumbs.length - 2]!.path);
    } else if (e.key === "Enter") p.onOpen();
    else return;
    e.preventDefault();
  };
  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-2">
        {p.roots.map((r) => (
          <button
            key={r.id}
            type="button"
            onClick={() => p.onRoot(r.id)}
            aria-pressed={r.id === p.root}
            className={cn(
              "rounded-full border px-3 py-1 text-caption focus-visible:outline-2 focus-visible:outline-accent",
              r.id === p.root ? "border-accent bg-accent-soft text-accent" : "border-border text-text-muted hover:text-text",
            )}
          >
            Media root: {r.label}
          </button>
        ))}
      </div>
      {p.listing && (
        <nav aria-label="Folder path" className="flex flex-wrap items-center gap-1 text-small text-text-muted">
          {p.listing.crumbs.map((c, i) => (
            <span key={c.path} className="inline-flex items-center gap-1">
              {i > 0 && <ChevronRight aria-hidden className="size-3.5 text-text-faint" />}
              <button type="button" onClick={() => p.onEnter(c.path)} className="rounded-sm hover:text-text focus-visible:outline-2 focus-visible:outline-accent">
                {c.name}
              </button>
            </span>
          ))}
        </nav>
      )}
      <ul
        role="listbox"
        aria-label="Folders"
        tabIndex={0}
        onKeyDown={onKey}
        aria-activedescendant={index >= 0 ? optionId(index) : undefined}
        className="flex max-h-80 min-h-40 flex-col overflow-y-auto rounded-md border border-border focus-visible:outline-2 focus-visible:outline-accent">
        {p.loading && <li role="presentation" className="p-4 text-small text-text-muted">Looking…</li>}
        {!p.loading && p.listing && items.length === 0 && (
          <li role="presentation" className="p-4 text-small text-text-muted">No folders here.</li>
        )}
        {items.map((it, i) => (
          <li
            key={it.path}
            id={optionId(i)}
            role="option"
            aria-selected={it.path === p.selected}
            onClick={() => p.onSelect(it.path)}
            onDoubleClick={() => p.onEnter(it.path)}
            className={cn(
              "flex cursor-pointer items-center gap-3 border-b border-border px-4 py-2.5 last:border-b-0",
              it.path === p.selected ? "bg-surface-2" : "hover:bg-surface-2",
            )}
          >
            <Folder aria-hidden className="size-4 shrink-0 text-text-muted" />
            <span className="min-w-0 flex-1">
              <span className="block truncate text-body text-text">{it.name}</span>
              <span className="mono text-timecode-sm text-text-muted">{countLine(it.counts)}</span>
            </span>
            {it.has_project && (
              <span className="rounded-full border border-border px-2 py-0.5 text-caption text-text-muted">MosAic project</span>
            )}
          </li>
        ))}
      </ul>
      <p className="text-caption font-normal text-text-faint">
        Only folders inside media roots your administrator set up are shown.
      </p>
      <div className="flex justify-end gap-2">
        <Button variant="ghost" onClick={p.onCancel}>
          Cancel
        </Button>
        <Button variant="primary" onClick={p.onOpen} disabled={!p.listing}>
          Open this folder
        </Button>
      </div>
    </div>
  );
}

/** The dialog with data (GET /fs/browse). */
export function FolderBrowserDialog({
  open,
  onOpenChange,
  onPick,
  error,
}: {
  open: boolean;
  onOpenChange: (o: boolean) => void;
  onPick: (pick: FolderPick) => void;
  error?: string | null;
}) {
  const [root, setRoot] = useState<number | null>(null);
  const [path, setPath] = useState("");
  const [selected, setSelected] = useState<string | null>(null);
  const roots = useQuery({
    queryKey: ["fs", "roots"],
    enabled: open,
    queryFn: async () => (await api.GET("/api/fs/browse")).data as { roots: { id: number; label: string }[] } | undefined,
  });
  const current = root ?? roots.data?.roots[0]?.id ?? null;
  const listing = useQuery({
    queryKey: ["fs", "browse", current, path],
    enabled: open && current !== null,
    queryFn: async () =>
      (await api.GET("/api/fs/browse", { params: { query: { root: current!, path } } })).data as Listing | undefined,
  });
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-scrim" />
        <Dialog.Content
          aria-describedby={undefined}
          className="fixed top-1/2 left-1/2 z-50 flex w-[720px] -translate-x-1/2 -translate-y-1/2 flex-col gap-4 rounded-[16px] border border-border bg-surface-1 p-6 shadow-[0_24px_64px_rgba(0,0,0,0.5)]"
        >
          <Dialog.Title className="text-heading text-text">Open footage folder</Dialog.Title>
          {error && (
            <p role="alert" className="text-small text-reject">
              {error}
            </p>
          )}
          {roots.data && roots.data.roots.length === 0 ? (
            <p className="text-small text-text-muted">
              No media roots yet. An administrator adds them in Settings → Media roots.
            </p>
          ) : (
            <FolderBrowserView
              roots={roots.data?.roots ?? []}
              root={current}
              listing={listing.data}
              loading={listing.isLoading}
              selected={selected}
              onRoot={(id) => {
                setRoot(id);
                setPath("");
                setSelected(null);
              }}
              onEnter={(p) => {
                setPath(p);
                setSelected(null);
              }}
              onSelect={setSelected}
              onOpen={() => current !== null && onPick({ root: current, path: selected ?? path })}
              onCancel={() => onOpenChange(false)}
            />
          )}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
