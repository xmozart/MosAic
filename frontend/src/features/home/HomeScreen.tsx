import { useQuery, useQueryClient } from "@tanstack/react-query";
import { FolderOpen } from "lucide-react";
import { useRef, useState, type KeyboardEvent } from "react";
import { useNavigate } from "react-router";

import { api } from "@/api/client";
import { Button } from "@/components/ui/Button";
import { CreateProjectDialog, type PreviewData } from "@/features/open/CreateProjectDialog";
import { FolderBrowserDialog, type FolderPick } from "@/features/open/FolderBrowserDialog";
import { PathDialog } from "@/features/open/PathDialog";
import { cn } from "@/lib/cn";
import { formatOpened } from "@/lib/format";
import { media } from "@/lib/media";
import { useMode } from "@/lib/mode";
import { useToasts } from "@/lib/toasts";
import { placementOf } from "@/lib/placement";

import { ProjectCard, type ProjectCardData } from "./ProjectCard";

interface Row {
  id: string;
  name: string;
  placement: string;
  fs_class: string;
  missing: boolean | null;
  last_opened_at: string;
  card: {
    clips: number;
    photos: number;
    footage_seconds: number;
    first_date: string | null;
    last_date: string | null;
    cover: number[];
    latest_edit: string | null;
  } | null;
  status: { state: string; pct?: number; mode?: string | null };
}

type FolderRef = { path: string } | FolderPick;

function cardData(r: Row): ProjectCardData {
  return {
    name: r.name,
    placement: placementOf(r),
    cover: (r.card?.cover ?? []).map((sid) => media.frame(r.id, sid)),
    firstDate: r.card?.first_date ?? null,
    lastDate: r.card?.last_date ?? null,
    footageSeconds: r.card?.footage_seconds ?? 0,
    clips: r.card?.clips ?? 0,
    photos: r.card?.photos ?? 0,
    status: r.status,
    latestEdit: r.card?.latest_edit ?? null,
    opened: formatOpened(r.last_opened_at),
    missing: r.missing,
  };
}

function errorText(error: unknown, fallback: string): string {
  const d = (error as { detail?: unknown } | undefined)?.detail;
  return typeof d === "string" ? d : fallback;
}

/** S3 with trips: the heading and the two ways to open one. */
export function HomeHeader({ onOpenFolder, onOpenProject }: { onOpenFolder: () => void; onOpenProject: () => void }) {
  return (
    <div className="flex items-end justify-between gap-6">
      <div className="flex flex-col gap-1">
        <h1 className="text-display text-text">Your trips</h1>
        <p className="text-body text-text-muted">MosAic works with your footage where it lives. Nothing is moved or changed.</p>
      </div>
      <div className="flex gap-3">
        <Button size="lg" onClick={onOpenProject}>
          Open existing project
        </Button>
        <Button variant="primary" size="lg" onClick={onOpenFolder}>
          <FolderOpen /> Open footage folder
        </Button>
      </div>
    </div>
  );
}

/** S3b: no projects yet. A dashed drop area with a mini collage (neutral tiles). */
export function HomeEmpty({ onOpenFolder, onOpenProject }: { onOpenFolder: () => void; onOpenProject: () => void }) {
  return (
    <div className="m-auto flex w-[760px] flex-col items-center gap-5 rounded-lg border-[1.5px] border-dashed border-border bg-surface-1 p-14 text-center">
      <div aria-hidden className="grid grid-cols-[repeat(3,64px)] gap-1.5">
        {["opacity-90", "opacity-60", "opacity-80", "opacity-50", "opacity-90", "opacity-60"].map((o, i) => (
          <div key={i} className={cn("h-9 w-16 rounded-sm bg-surface-3", o)} />
        ))}
      </div>
      <h1 className="text-title text-text">Pick a folder of trip footage</h1>
      <p className="max-w-[520px] text-body text-text-muted">
        MosAic works with your files where they are — nothing gets moved or changed. Point it at a folder
        with videos and photos from any camera.
      </p>
      <div className="flex gap-3">
        <Button variant="primary" size="lg" onClick={onOpenFolder}>
          <FolderOpen /> Open footage folder
        </Button>
        <Button onClick={onOpenProject}>Open existing project</Button>
      </div>
      <p className="text-caption font-normal text-text-faint">
        iPhone · GoPro · Insta360 · Nikon · DJI · most other cameras
      </p>
    </div>
  );
}

/** S3 Home: recent trips, and opening a footage folder (S4). */
export function HomeScreen() {
  const mode = useMode();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const toast = useToasts((s) => s.push);
  const [choosing, setChoosing] = useState<null | { relink?: string }>(null);
  const [pathError, setPathError] = useState<string | null>(null);
  const [confirm, setConfirm] = useState<{ ref: FolderRef; preview: PreviewData } | null>(null);
  const [busy, setBusy] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);
  const grid = useRef<HTMLDivElement>(null);
  const projects = useQuery({
    queryKey: ["projects"],
    queryFn: async () => (await api.GET("/api/projects")).data as { items: Row[] } | undefined,
    refetchInterval: 5000,
  });
  const rows = projects.data?.items ?? [];

  /** Creates (or opens an existing) project. Errors show in the confirm dialog when it is
   * open, otherwise as a toast. */
  const create = async (ref: FolderRef, name?: string) => {
    setBusy(true);
    const result = await api
      .POST("/api/projects", { body: { ...ref, name } })
      .catch(() => undefined)
      .finally(() => setBusy(false));
    const data = result?.data;
    if (!data) {
      const message = errorText(result?.error, "Couldn't open that folder. Try again.");
      if (confirm) setCreateError(message);
      else toast({ kind: "error", message });
      return;
    }
    setConfirm(null);
    await qc.invalidateQueries({ queryKey: ["projects"] });
    const id = (data as { id: string }).id;
    qc.removeQueries({ queryKey: ["moving", id] }); // a move may have just started (ADR 0055)
    navigate(`/p/${id}`);
  };

  const picked = async (ref: FolderRef) => {
    const relink = choosing?.relink;
    if (relink) {
      const body = "root" in ref ? { root: ref.root, path: ref.path } : { choose_folder: ref.path };
      const { error } = await api.POST("/api/projects/{pid}/relink", {
        params: { path: { pid: relink } },
        body,
      });
      if (error) {
        setPathError(errorText(error, "That folder doesn't hold this trip's footage."));
        return;
      }
      setChoosing(null);
      toast({ kind: "success", message: "Reconnected. Looking through the folder again." });
      void qc.invalidateQueries({ queryKey: ["projects"] });
      return;
    }
    const { data, error } = await api.POST("/api/projects/preview", { body: ref });
    if (error || !data) {
      setPathError(errorText(error, "That folder can't be opened."));
      return;
    }
    setPathError(null);
    setChoosing(null);
    const pv = data as { name: string; placement: PreviewData["placement"]; counts: PreviewData["counts"]; project_id: string | null };
    if (pv.project_id) {
      void create(ref); // already a project: open it, no confirmation (S4)
      return;
    }
    setCreateError(null);
    setConfirm({
      ref,
      preview: { where: "root" in ref ? ref.path || "Media root" : ref.path, name: pv.name, placement: pv.placement, counts: pv.counts },
    });
  };

  const remove = async (pid: string) => {
    const { error } = await api.DELETE("/api/projects/{pid}/recent", { params: { path: { pid } } });
    if (error) toast({ kind: "error", message: "Couldn't remove it from the list. Try again." });
    void qc.invalidateQueries({ queryKey: ["projects"] });
  };

  const onGridKey = (e: KeyboardEvent<HTMLDivElement>) => {
    const cards = Array.from(grid.current?.querySelectorAll<HTMLElement>("[data-card] > button") ?? []);
    const i = cards.indexOf(document.activeElement as HTMLElement);
    if (i < 0) return;
    const step = { ArrowRight: 1, ArrowLeft: -1, ArrowDown: 3, ArrowUp: -3 }[e.key];
    if (step === undefined) return;
    e.preventDefault();
    cards[Math.min(cards.length - 1, Math.max(0, i + step))]?.focus();
  };


  return (
    <div className="flex flex-1 flex-col gap-8 overflow-y-auto p-8">
      {projects.isSuccess && rows.length === 0 ? (
        <HomeEmpty onOpenFolder={() => setChoosing({})} onOpenProject={() => setChoosing({})} />
      ) : (
        <>
          <HomeHeader onOpenProject={() => setChoosing({})} onOpenFolder={() => setChoosing({})} />
          <div ref={grid} onKeyDown={onGridKey} className="grid grid-cols-3 gap-6">
            {rows.map((r) => (
              <div key={r.id} data-card>
                <ProjectCard
                  data={cardData(r)}
                  onOpen={() => navigate(`/p/${r.id}`)}
                  onReconnect={() => setChoosing({ relink: r.id })}
                  onRemove={() => void remove(r.id)}
                />
              </div>
            ))}
          </div>
        </>
      )}
      {mode === "server" ? (
        <FolderBrowserDialog
          open={choosing !== null}
          error={pathError}
          onOpenChange={(o) => {
            if (!o) {
              setChoosing(null);
              setPathError(null);
            }
          }}
          onPick={(p) => void picked(p)}
        />
      ) : (
        <PathDialog
          open={choosing !== null}
          error={pathError}
          onPick={(path) => void picked({ path })}
          onCancel={() => {
            setChoosing(null);
            setPathError(null);
          }}
        />
      )}
      {confirm && (
        <CreateProjectDialog
          open
          preview={confirm.preview}
          busy={busy}
          error={createError}
          onCreate={(name) => void create(confirm.ref, name)}
          onCancel={() => {
            setConfirm(null);
            if (confirm.preview.counts.videos + confirm.preview.counts.photos === 0) setChoosing({});
          }}
        />
      )}
    </div>
  );
}
