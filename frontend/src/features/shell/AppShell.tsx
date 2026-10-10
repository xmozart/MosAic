import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { Link, Outlet, useLocation, useNavigate, useParams } from "react-router";

import { api } from "@/api/client";
import { ActivityPopover } from "@/components/shell/ActivityPopover";
import { AppRail, type RailItem } from "@/components/shell/AppRail";
import { CommandPalette, type Command } from "@/components/shell/CommandPalette";
import { Toaster } from "@/components/ui/Toast";
import { anyRunning, connectActivity, overall, useActivity } from "@/lib/activity";
import { useTheme } from "@/lib/theme";
import { useToasts } from "@/lib/toasts";

import { CostCeilingDialog, LeaseLostDialog } from "./dialogs";

interface ProjectRow {
  id: string;
  name: string;
}

function railItem(path: string): RailItem {
  if (path.includes("/library") || path.includes("/search")) return "library";
  if (path.includes("/edits")) return "edits";
  if (path.startsWith("/exports") || path.endsWith("/exports")) return "exports";
  if (path.startsWith("/settings") || path.endsWith("/settings") || path.startsWith("/diagnostics")) return "settings";
  return "home";
}

/** S0: rail, content, global dialogs, ⌘K palette and toasts around every screen. */
export function AppShell() {
  const { pid } = useParams();
  const location = useLocation();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const theme = useTheme();
  const [palette, setPalette] = useState(false);
  const toast = useToasts((s) => s.push);
  const [raise, setRaise] = useState<{ jobId: number; limit: number; spent: number } | null>(null);
  const jobMap = useActivity((s) => s.jobs);
  const jobs = useMemo(() => Object.values(jobMap), [jobMap]);
  const lost = useActivity((s) => s.lost);
  const ackLost = useActivity((s) => s.ackLost);
  const projects = useQuery({
    queryKey: ["projects"],
    queryFn: async () => (await api.GET("/api/projects")).data as { items: ProjectRow[] } | undefined,
  });
  const names = useMemo(
    // App-level jobs (model downloads; ADR 0058) belong to MosAic, not to a trip.
    (): Record<string, string> => ({ _app: "MosAic", ...Object.fromEntries((projects.data?.items ?? []).map((p) => [p.id, p.name])) }),
    [projects.data],
  );

  useEffect(() => connectActivity(), []);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setPalette(true);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const darkNow =
    theme.choice === "dark" ||
    (theme.choice === "system" && !window.matchMedia?.("(prefers-color-scheme: light)").matches);
  const links: Partial<Record<RailItem, string>> = {
    home: "/",
    exports: pid ? `/p/${pid}/exports` : "/exports",
    settings: "/settings",
    ...(pid ? { library: `/p/${pid}/library`, edits: `/p/${pid}/edits` } : {}),
  };
  const commands: Command[] = [
    { id: "home", label: "Go to Home", kind: "Action", run: () => navigate("/") },
    { id: "diagnostics", label: "Diagnostics", kind: "Action", run: () => navigate("/diagnostics") },
    ...(pid
      ? [
          { id: "lib", label: "Open library", kind: "Action" as const, run: () => navigate(`/p/${pid}/library`) },
          { id: "edit", label: "Create edit", kind: "Action" as const, run: () => navigate(`/p/${pid}/edits/new`) },
          { id: "deepen", label: "Deepen analysis…", kind: "Action" as const, run: () => navigate(`/p/${pid}/deepen`) },
          { id: "project-settings", label: "Project settings", kind: "Action" as const, run: () => navigate(`/p/${pid}/settings`) },
        ]
      : []),
    ...(projects.data?.items ?? []).map((p) => ({
      id: `p-${p.id}`,
      label: p.name,
      kind: "Project" as const,
      run: () => navigate(`/p/${p.id}`),
    })),
  ];
  const lostHere = pid && lost.includes(pid) ? pid : null;
  const jobCall = (action: "pause" | "resume" | "cancel") => (jobId: number) =>
    void api.POST("/api/jobs/{job_id}/{action}", { params: { path: { job_id: jobId, action } } });

  return (
    <div className="flex h-full min-h-[800px] min-w-[1280px] bg-bg text-text">
      <AppRail
        active={railItem(location.pathname)}
        activityPct={overall(jobs)}
        running={anyRunning(jobs)}
        links={links}
        renderLink={(href, children, className, label) => (
          <Link to={href} className={className} aria-label={label}>
            {children}
          </Link>
        )}
        theme={darkNow ? "dark" : "light"}
        onToggleTheme={() => theme.set(darkNow ? "light" : "dark")}
        renderActivity={(button) => (
          <ActivityPopover
            jobs={jobs}
            projectNames={names}
            onPause={jobCall("pause")}
            onResume={jobCall("resume")}
            onCancel={jobCall("cancel")}
            onRaiseLimit={async (jobId) => {
              const { data } = await api.GET("/api/jobs/{job_id}", { params: { path: { job_id: jobId } } });
              const job = data as { cost_limit_usd?: number | null; cost_usd?: number } | undefined;
              const spent = job?.cost_usd ?? 0;
              setRaise({ jobId, limit: job?.cost_limit_usd ?? spent, spent });
            }}
          >
            {button}
          </ActivityPopover>
        )}
      />
      <main className="flex min-w-0 flex-1 flex-col">
        <Outlet context={{ openPalette: () => setPalette(true) }} />
      </main>
      <CommandPalette
        open={palette}
        onOpenChange={setPalette}
        commands={commands}
        onSearch={pid ? (q) => navigate(`/p/${pid}/search?q=${encodeURIComponent(q)}`) : undefined}
      />
      <LeaseLostDialog
        open={Boolean(lostHere)}
        project={lostHere ? (names[lostHere] ?? "This project") : ""}
        onReadOnly={() => {
          if (!lostHere) return;
          ackLost(lostHere);
          void qc.invalidateQueries({ queryKey: ["project", lostHere] });
        }}
        onClose={() => {
          if (!lostHere) return;
          ackLost(lostHere);
          navigate("/");
        }}
      />
      {raise && (
        <CostCeilingDialog
          open
          limit={raise.limit}
          spent={raise.spent}
          onKeepPaused={() => setRaise(null)}
          onRaise={async (limit) => {
            const jobId = raise.jobId;
            setRaise(null);
            const { error } = await api.POST("/api/jobs/{job_id}/{action}", {
              params: { path: { job_id: jobId, action: "resume" } },
              body: { cost_limit_usd: limit },
            });
            if (error) toast({ kind: "error", message: "Couldn't resume the analysis. Try again." });
          }}
        />
      )}
      <Toaster />
    </div>
  );
}

export function Placeholder({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="flex flex-1 flex-col gap-2 p-8">
      <h1 className="text-title text-text">{title}</h1>
      {children}
    </div>
  );
}
