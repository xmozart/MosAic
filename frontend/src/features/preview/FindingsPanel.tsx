import { RefreshCw } from "lucide-react";
import { useEffect, useLayoutEffect, useRef, useState } from "react";

import { FindingCard } from "@/components/edit/FindingCard";
import { Button } from "@/components/ui/Button";

import { isIssue, timecode, type Finding, type TimelineTime } from "./model";

export interface FindingsPanelProps {
  /** Undefined while they load. */
  findings: Finding[] | undefined;
  error?: boolean;
  onRetry?: () => void;
  rate: string;
  /** Findings are applied to the latest version only. */
  latest: boolean;
  /** A change is on its way: Apply and Ignore wait. */
  busy?: boolean;
  onSeek: (t: TimelineTime) => void;
  onApply: (id: string) => void;
  onIgnore: (id: string) => void;
  onApplyAll: () => void;
  onIgnoreAll: () => void;
  onRegenerate: () => void;
}

/** S17's findings (M4; ADR 0081, 0089): what the checks and the AI review found, each
 * with Apply / Ignore, and Apply all, Ignore all and Regenerate with fixes. N / P jump to
 * the next / previous finding, A applies the focused one. */
export function FindingsPanel(p: FindingsPanelProps) {
  const items = p.findings;
  const open = items?.filter((f) => f.status === "open") ?? [];
  const [focusedId, setFocused] = useState<string | null>(null);
  const focused = items ? items.findIndex((f) => f.finding_id === focusedId) : -1; // -1: none
  const at = useRef<string | null>(null); // the focused finding's id, for the keys
  const cards = useRef(new Map<string, HTMLElement>());
  const latest = useRef(p);
  useLayoutEffect(() => {
    latest.current = p;
  });
  // A new list (another version, a fix applied) has nothing focused yet.
  useEffect(() => {
    at.current = null;
  }, [items]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.metaKey || e.ctrlKey || e.altKey || e.repeat) return;
      if (e.target instanceof Element && e.target.closest("input, textarea, select, [contenteditable=true], [role=dialog], [role=menu]")) return;
      const q = latest.current;
      const list = q.findings ?? [];
      if (!list.length) return;
      const key = e.key.toLowerCase();
      const i = list.findIndex((f) => f.finding_id === at.current);
      if (key === "n" || key === "p") {
        e.preventDefault();
        const next = i === -1 ? (key === "n" ? 0 : list.length - 1) : (i + (key === "n" ? 1 : -1) + list.length) % list.length;
        const f = list[next]!;
        at.current = f.finding_id;
        setFocused(f.finding_id);
        cards.current.get(f.finding_id)?.focus();
        q.onSeek({ frames: f.frame, rate: q.rate });
      } else if (key === "a" && i !== -1) {
        // Only the finding that has the focus now.
        const f = list[i]!;
        if (!cards.current.get(f.finding_id)?.contains(document.activeElement)) return;
        if (f.status === "open" && f.can_apply && q.latest && !q.busy) {
          e.preventDefault();
          q.onApply(f.finding_id);
        }
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const canApplyAll = p.latest && open.some((f) => f.can_apply);
  return (
    <section aria-label="Findings" className="flex min-h-0 flex-col gap-2.5">
      <div className="flex items-center gap-2">
        <h2 className="text-subhead font-semibold tracking-[-0.01em] text-text">Findings</h2>
        {items && (
          <span className="inline-flex items-center rounded-full border border-border bg-surface-2 px-[9px] py-[3px] text-micro font-medium text-text-muted">{open.length}</span>
        )}
        {open.length > 0 && (
          <span className="ml-auto flex gap-1.5">
            <Button size="sm" disabled={!canApplyAll || p.busy} onClick={p.onApplyAll}>
              Apply all
            </Button>
            <Button size="sm" variant="ghost" disabled={!p.latest || p.busy} onClick={p.onIgnoreAll}>
              Ignore all
            </Button>
          </span>
        )}
      </div>
      {!p.latest && open.length > 0 && <p className="text-caption font-normal text-text-faint">These are an older version's findings. Fixes apply to the latest version.</p>}
      {p.error ? (
        <div className="flex items-center gap-2 text-small text-text-muted">
          The findings couldn't be loaded.
          {p.onRetry && (
            <Button size="sm" variant="ghost" onClick={p.onRetry}>
              Try again
            </Button>
          )}
        </div>
      ) : !items ? (
        [0, 1, 2].map((i) => <div key={i} aria-hidden className="h-[118px] animate-pulse rounded-lg border border-border bg-surface-1" />)
      ) : items.length === 0 ? (
        <p className="rounded-lg border border-border bg-surface-1 p-3.5 text-body text-text">Looks good — no issues found</p>
      ) : (
        <div className="flex min-h-0 flex-col gap-2 overflow-y-auto">
          {items.map((f) => (
            <FindingCard
              key={f.finding_id}
              ref={(el) => {
                if (el) cards.current.set(f.finding_id, el);
                else cards.current.delete(f.finding_id);
              }}
              issue={isIssue(f)}
              ai={f.source === "ai"}
              timecode={timecode({ frames: f.frame, rate: p.rate })}
              text={f.text}
              fix={f.fix}
              canApply={f.can_apply}
              status={f.status}
              appliedIn={f.applied_in_version}
              disabled={!p.latest || p.busy}
              onFocus={() => {
                at.current = f.finding_id;
                setFocused(f.finding_id);
              }}
              onSeek={() => p.onSeek({ frames: f.frame, rate: p.rate })}
              onApply={() => p.onApply(f.finding_id)}
              onIgnore={() => p.onIgnore(f.finding_id)}
            />
          ))}
        </div>
      )}
      {open.length > 0 && (
        <Button variant="ghost" size="sm" className="self-start" disabled={!p.latest || p.busy} onClick={p.onRegenerate}>
          <RefreshCw /> Regenerate with fixes
        </Button>
      )}
      {focused !== -1 && <span className="sr-only" aria-live="polite">{`Finding ${focused + 1} of ${items?.length ?? 0}`}</span>}
    </section>
  );
}
