import { useEffect, useState, type FormEvent } from "react";

import { Wordmark } from "@/components/brand/Wordmark";
import { Banner } from "@/components/ui/Banner";
import { Button } from "@/components/ui/Button";
import { TextField } from "@/components/ui/TextField";

export interface SignInProps {
  setup: boolean; // first-time variant: no account yet
  host: string;
  submit: (password: string) => Promise<{ ok: true } | { ok: false; message: string; retryAfter?: number }>;
}

/** S2 Sign in (server mode). Enter submits; five failures show a countdown. */
export function SignIn({ setup, host, submit }: SignInProps) {
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [wait, setWait] = useState(0);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (wait <= 0) return;
    const t = setTimeout(() => setWait((w) => w - 1), 1000);
    return () => clearTimeout(t);
  }, [wait]);

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (setup && password !== confirm) {
      setError("The passwords don't match.");
      return;
    }
    setBusy(true);
    setError(null);
    const r = await submit(password);
    setBusy(false);
    if (!r.ok) {
      setError(r.message);
      setPassword("");
      setConfirm("");
      if (r.retryAfter) setWait(r.retryAfter);
    }
  };

  return (
    <main className="flex min-h-full items-center justify-center bg-bg p-6">
      <form
        onSubmit={onSubmit}
        className="flex w-[400px] flex-col gap-[18px] rounded-[18px] border border-border bg-surface-1 p-8"
      >
        <Wordmark />
        <div className="flex flex-col gap-1.5">
          <h1 className="text-[22px] leading-7 font-semibold text-text">
            {setup ? "Set an admin password" : "Sign in to MosAic"}
          </h1>
          <p className="text-small text-text-muted">
            {setup
              ? "This server has no account yet. You'll use this password to sign in from any browser."
              : `Home server · ${host}`}
          </p>
        </div>
        <TextField
          label="Password"
          type="password"
          autoComplete={setup ? "new-password" : "current-password"}
          autoFocus
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          hint={setup ? "At least 12 characters." : undefined}
        />
        {setup && (
          <TextField
            label="Confirm password"
            type="password"
            autoComplete="new-password"
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
          />
        )}
        {wait > 0 ? (
          <Banner kind="danger">
            Too many attempts. Try again in <span className="mono">{wait} s</span>.
          </Banner>
        ) : (
          error && <Banner kind="danger">{error}</Banner>
        )}
        <Button type="submit" variant="primary" size="lg" className="w-full" disabled={busy || wait > 0 || !password}>
          {setup ? "Create account" : "Sign in"}
        </Button>
      </form>
    </main>
  );
}
