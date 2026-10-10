import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, type ReactNode } from "react";

import { api, onSignedOut } from "@/api/client";
import { startDesktopSession } from "@/lib/desktop";

import { Banner } from "@/components/ui/Banner";
import { Button } from "@/components/ui/Button";

import { SignIn } from "./SignIn";

/** Server mode: the app behind sign-in (S2). Desktop: the shell's token opens a session. */
export function AuthGate({ children }: { children: ReactNode }) {
  const qc = useQueryClient();
  const status = useQuery({
    queryKey: ["auth", "status"],
    queryFn: async () => {
      const read = async () => {
        const { data, error } = await api.GET("/api/auth/status");
        if (error || !data) throw new Error("status unavailable");
        return data as { mode: string; setup_required: boolean; signed_in: boolean };
      };
      const first = await read();
      // Desktop: trade the shell's per-launch token for this origin's session (ADR 0057).
      if (first.mode === "desktop" && !first.signed_in && (await startDesktopSession())) return read();
      return first;
    },
  });

  useEffect(() => {
    onSignedOut.handler = () => void qc.invalidateQueries({ queryKey: ["auth"] });
  }, [qc]);

  if (status.isError) {
    return (
      <main className="flex min-h-full items-center justify-center bg-bg p-6">
        <div className="flex w-[400px] flex-col gap-3">
          <Banner kind="danger" action={<Button size="sm" onClick={() => void status.refetch()}>Try again</Button>}>
            Couldn't reach MosAic. Check that it's running.
          </Banner>
        </div>
      </main>
    );
  }
  if (!status.data) return null;
  const s = status.data;
  if (s.signed_in) return <>{children}</>;
  if (s.mode === "desktop") {
    return (
      <main className="flex min-h-full items-center justify-center bg-bg p-6">
        <div className="flex w-[400px] flex-col gap-3">
          <Banner kind="danger">This page can't reach MosAic. Open MosAic from the app.</Banner>
        </div>
      </main>
    );
  }

  const submit = async (password: string) => {
    const call = s.setup_required ? api.POST("/api/auth/setup", { body: { password } }) : api.POST("/api/auth/login", { body: { password } });
    const { response, error } = await call;
    if (response.ok) {
      await qc.invalidateQueries();
      return { ok: true as const };
    }
    const body = (error ?? {}) as { detail?: unknown; retry_after?: number };
    const message = typeof body.detail === "string" ? body.detail : "Couldn't sign in. Try again.";
    return { ok: false as const, message, retryAfter: body.retry_after };
  };

  return <SignIn setup={s.setup_required} host={window.location.hostname} submit={submit} />;
}
