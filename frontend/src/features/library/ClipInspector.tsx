import { Maximize2, X } from "lucide-react";

import { Player } from "@/components/media/Player";
import { Button } from "@/components/ui/Button";

import { ClipFacts } from "./ClipFacts";
import { clock, usableRange, type ClipDetail, type DecisionChange } from "./model";

export interface ClipInspectorProps {
  clip: ClipDetail;
  proxyUrl: string | undefined;
  frameUrl: (sampleId: number) => string;
  onDecide: (change: DecisionChange) => void;
  onOpenFull: () => void;
  onClose: () => void;
  onShowClip: (id: number) => void;
}

/** COMPONENTS.md ClipInspector: a 400 px sheet; section order is fixed (player, usable
 * range, title line, disposition, AI-vs-you, include, Why, Moments, Quality, Similar,
 * Tags, Note, Used in edits). Presentational. */
export function ClipInspector(p: ClipInspectorProps) {
  const c = p.clip;
  const usable = usableRange(c);
  const poster = c.moments.find((m) => m.sample_id)?.sample_id;
  return (
    <aside aria-label="Clip" className="flex w-[400px] shrink-0 flex-col overflow-y-auto border-l border-border bg-surface-1">
      <header className="flex items-center gap-2 px-4 pt-3 pb-2">
        <span className="text-caption text-text-muted">Clip</span>
        <Button variant="secondary" size="icon" aria-label="Open full view" className="ml-auto size-[30px]" onClick={p.onOpenFull}>
          <Maximize2 />
        </Button>
        <Button variant="secondary" size="icon" aria-label="Close inspector" className="size-[30px]" onClick={p.onClose}>
          <X />
        </Button>
      </header>
      <div className="flex flex-col gap-4 px-4 pb-6">
        {c.status === "unsupported" ? (
          <div className="flex aspect-video flex-col items-center justify-center gap-1 rounded-md bg-surface-2 p-4 text-center">
            <p className="text-small text-text">{c.reason}</p>
            {c.fix && <p className="text-caption font-normal text-text-muted">{c.fix}</p>}
          </div>
        ) : c.kind === "video" && c.rate ? (
          <Player
            src={p.proxyUrl}
            poster={poster ? p.frameUrl(poster) : undefined}
            rate={c.proxy_rate ?? c.rate}
            usableRange={usable}
            markers={c.moments.filter((m) => m.description).map((m) => ({ at: m.usable_start, label: m.description!, kind: "moment" as const }))}
          />
        ) : (
          <div className="aspect-video overflow-hidden rounded-md bg-surface-3">
            {poster && <img src={p.frameUrl(poster)} alt="" className="size-full object-cover" />}
          </div>
        )}
        {usable && (
          <p className="mono text-timecode-sm text-text-muted">
            Usable range {clock(usable.start)} – {clock(usable.end)}
          </p>
        )}
        <ClipFacts clip={c} frameUrl={p.frameUrl} onDecide={p.onDecide} onShowClip={p.onShowClip} />
      </div>
    </aside>
  );
}
