import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo } from "react";
import { Outlet, useOutletContext, useParams } from "react-router";

import { api } from "@/api/client";
import type { Placement } from "@/components/system/PlacementBadge";
import { ProjectHeader, type ProjectStatus } from "@/components/shell/ProjectHeader";
import { useActivity } from "@/lib/activity";
import { useToasts } from "@/lib/toasts";

import { ReadOnlyBanner } from "./dialogs";

interface Row {
  id: string;
  name: string;
  placement: string;
  fs_class: string;
  status: ProjectStatus;
}

function placementBadge(row: Row): Placement {
  if (row.placement === "split") return row.fs_class === "cloud_synced" ? "split_icloud" : "split_nas";
  if (row.placement === "external") return "separate";
  return "in_folder";
}

/** Project screens: the S0 header (name, placement, status, ⌘K) above the screen. */
export function ProjectLayout() {
  const { pid } = useParams();
  const { openPalette } = useOutletContext<{ openPalette: () => void }>();
  const jobMap = useActivity((s) => s.jobs);
  const live = useMemo(
    () =>
      Object.values(jobMap).find(
        (j) => j.projectId === pid && ["analysis", "scan", "deepen"].includes(j.kind),
      ),
    [jobMap, pid],
  );
  const readOnly = useActivity((s) => (pid ? s.lost.includes(pid) || s.readOnly.includes(pid) : false));
  const qc = useQueryClient();
  const pushToast = useToasts((s) => s.push);
  const projects = useQuery({
    queryKey: ["projects"],
    queryFn: async () => (await api.GET("/api/projects")).data as { items: Row[] } | undefined,
  });
  const row = projects.data?.items.find((p) => p.id === pid);
  if (!row) {
    return (
      <div className="flex flex-1 flex-col gap-2 p-8">
        {projects.isLoading ? (
          <div aria-label="Loading" className="h-14 animate-pulse rounded-md bg-surface-2" />
        ) : (
          <p className="text-body text-text-muted">We can't find that trip. It may have been removed from this computer.</p>
        )}
      </div>
    );
  }
  const status: ProjectStatus = live
    ? { state: live.kind === "scan" ? "scanning" : "analyzing", pct: live.pct }
    : row.status;
  return (
    <>
      <ProjectHeader
        name={row.name}
        placement={placementBadge(row)}
        status={status}
        aiCost={live && live.cost > 0 ? `AI $${live.cost.toFixed(2)}` : undefined}
        readOnly={readOnly}
        onSearch={openPalette}
        onRename={(name) => {
          qc.setQueryData<{ items: Row[] }>(["projects"], (old) => old && { ...old, items: old.items.map((x) => (x.id === row.id ? { ...x, name } : x)) });
          void api.PATCH("/api/projects/{pid}", { params: { path: { pid: row.id } }, body: { name } }).then(({ error }) => {
            if (error) pushToast({ kind: "error", message: "Couldn't rename the trip. Try again." });
            void qc.invalidateQueries({ queryKey: ["projects"] });
          });
        }}
      />
      {readOnly && (
        <ReadOnlyBanner reason="This project is open on another computer. You can look, but changes are off." />
      )}
      <Outlet context={{ openPalette, readOnly }} />
    </>
  );
}
