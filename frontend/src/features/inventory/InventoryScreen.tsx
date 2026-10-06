import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router";

import { api } from "@/api/client";
import { useActivity } from "@/lib/activity";
import { plural } from "@/lib/format";
import { media } from "@/lib/media";
import { useToasts } from "@/lib/toasts";

import { ClockCheckDialog } from "./ClockCheckDialog";
import { FilesDialog } from "./FilesDialog";
import { InventoryView } from "./InventoryView";
import { attentionKey, type Attention, type Inventory } from "./model";

const hiddenKey = (pid: string) => `mosaic.inventory.hidden.${pid}`;

/** Rows the user chose to Ignore or Skip, remembered in this browser only: a display
 * convenience, since unreadable and cloud-only files are already left out of analysis. */
function loadHidden(pid: string): Set<string> {
  try {
    return new Set(JSON.parse(localStorage.getItem(hiddenKey(pid)) ?? "[]") as string[]);
  } catch {
    return new Set();
  }
}

function saveHidden(pid: string, keys: Set<string>) {
  try {
    localStorage.setItem(hiddenKey(pid), JSON.stringify([...keys]));
  } catch {
    // storage unavailable: the choice lasts for this visit
  }
}

/** S5 Inventory (`/p/:pid/inventory`); keyed by project so per-project state resets. */
export function InventoryScreen() {
  const { pid = "" } = useParams();
  return <InventoryPage key={pid} pid={pid} />;
}

function InventoryPage({ pid }: { pid: string }) {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const toast = useToasts((s) => s.push);
  const jobs = useActivity((s) => s.jobs);
  const scanJob = useMemo(() => Object.values(jobs).find((j) => j.projectId === pid && j.kind === "scan" && j.state === "running"), [jobs, pid]);
  const [downloadJob, setDownloadJob] = useState<number | null>(null);
  const download = downloadJob !== null ? jobs[downloadJob] : undefined;
  const scanning = Boolean(scanJob) && scanJob?.jobId !== downloadJob;
  const inv = useQuery({
    queryKey: ["inventory", pid],
    queryFn: async () => (await api.GET("/api/projects/{pid}/inventory", { params: { path: { pid } } })).data as Inventory | undefined,
    refetchInterval: scanJob ? 2000 : false,
  });
  const [hidden, setHidden] = useState(() => loadHidden(pid));
  const [files, setFiles] = useState<Attention | null>(null);
  const [clocks, setClocks] = useState(false);

  const downloading = downloadJob !== null && !(download && ["done", "failed", "cancelled"].includes(download.state));
  // Refresh when a scan or download ends; say so when a download stops early.
  const seen = useRef<{ scan: boolean; download: number | null }>({ scan: false, download: null });
  useEffect(() => {
    const was = seen.current;
    if ((was.scan && !scanJob) || (was.download !== null && !downloading)) {
      void qc.invalidateQueries({ queryKey: ["inventory", pid] });
      if (was.download !== null && !downloading && download && download.state !== "done") {
        toast({ kind: "error", message: "The download stopped. Try again." });
      }
    }
    seen.current = { scan: Boolean(scanJob), download: downloading ? downloadJob : null };
  }, [scanJob, downloading, downloadJob, download, pid, qc, toast]);

  return (
    <>
      <InventoryView
        inv={inv.data}
        scanning={scanning || inv.isLoading}
        frameUrl={(sid) => media.frame(pid, sid)}
        hidden={hidden}
        downloadPct={downloading ? Math.round(download?.pct ?? 0) : null}
        onShowFiles={setFiles}
        onHide={(a) => {
          const next = new Set(hidden).add(attentionKey(a));
          setHidden(next);
          saveHidden(pid, next);
        }}
        onDownload={async () => {
          const { data, error } = await api.POST("/api/projects/{pid}/cloud-files/download", { params: { path: { pid } } });
          if (error || !data) toast({ kind: "error", message: "Couldn't start the download. Try again." });
          else setDownloadJob((data as { job_id: number }).job_id);
        }}
        onReviewClocks={() => setClocks(true)}
        onContinue={() => navigate(`/p/${pid}/context`)}
      />
      <FilesDialog
        pid={pid}
        row={files}
        title={files ? (files.kind === "limited" ? `Files of ${plural(files.count, "360° clip")}` : `${plural(files.count, "file")} can't be read`) : ""}
        onClose={() => setFiles(null)}
      />
      <ClockCheckDialog pid={pid} open={clocks} onOpenChange={setClocks} />
    </>
  );
}
