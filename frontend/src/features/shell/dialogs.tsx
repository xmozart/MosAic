import { useState } from "react";

import { Banner } from "@/components/ui/Banner";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { TextField } from "@/components/ui/TextField";

/** The global dialogs of S0 (copy from docs/ui/reference/S0-Dialogs). */

export function OpenElsewhereDialog(p: {
  open: boolean;
  project: string;
  host: string;
  since: string; // display time, e.g. "13:40"
  onReadOnly: () => void;
  onTakeOver: () => void;
  onCancel: () => void;
}) {
  return (
    <ConfirmDialog
      open={p.open}
      onOpenChange={(o) => !o && p.onCancel()}
      title={`${p.project} is open on another computer`}
      body={`${p.host} has had this project open since ${p.since}. Taking over could lose unsaved changes there.`}
      actions={[
        { label: "Cancel", variant: "ghost", onClick: p.onCancel },
        { label: "Open read-only", onClick: p.onReadOnly },
        { label: "Take over", variant: "danger", onClick: p.onTakeOver },
      ]}
    />
  );
}

export function CostCeilingDialog(p: {
  open: boolean;
  limit: number; // dollars, display
  remaining?: string; // "About $2.40 more to finish."
  onRaise: (limit: number) => void;
  onKeepPaused: () => void;
}) {
  const [value, setValue] = useState(String(Math.ceil(p.limit * 2)));
  const n = Number(value.replace(/[$,]/g, ""));
  const valid = Number.isFinite(n) && n > p.limit;
  return (
    <ConfirmDialog
      open={p.open}
      onOpenChange={(o) => !o && p.onKeepPaused()}
      title={`Analysis paused at your $${p.limit} limit`}
      body={
        <div className="flex flex-col gap-3">
          <p>{p.remaining ? `${p.remaining} ` : ""}Everything done so far is kept.</p>
          <TextField
            label="New limit"
            mono
            value={value}
            onChange={(e) => setValue(e.target.value)}
            error={value && !valid ? `Enter more than $${p.limit}.` : undefined}
          />
        </div>
      }
      actions={[
        { label: "Keep paused", onClick: p.onKeepPaused },
        { label: "Raise limit", variant: "primary", disabled: !valid, onClick: () => p.onRaise(n) },
      ]}
    />
  );
}

export function FilesMovedDialog(p: {
  open: boolean;
  missing: number;
  found: number;
  where: string; // the folder they were found in (mono)
  onRelink: () => void;
  onChoose: () => void;
  onSkip: () => void;
}) {
  const left = p.missing - p.found;
  return (
    <ConfirmDialog
      open={p.open}
      onOpenChange={(o) => !o && p.onSkip()}
      title={`${p.missing} clips aren't where they used to be`}
      body={
        <>
          We found {p.found} of them in <span className="mono text-text">{p.where}</span>.
          {left > 0 && ` The last ${left === 1 ? "one is" : `${left} are`} still missing.`}
        </>
      }
      actions={[
        { label: "Skip", variant: "ghost", onClick: p.onSkip },
        { label: "Choose folder…", onClick: p.onChoose },
        { label: `Relink ${p.found}`, variant: "primary", disabled: p.found === 0, onClick: p.onRelink },
      ]}
    />
  );
}

export function UnsavedDraftDialog(p: {
  open: boolean;
  summary: string; // "You trimmed 3 shots and reordered the Wildlife beat."
  nextVersion: number;
  onSave: () => void;
  onDiscard: () => void;
  onCancel: () => void;
}) {
  return (
    <ConfirmDialog
      open={p.open}
      onOpenChange={(o) => !o && p.onCancel()}
      title="Save your changes?"
      body={`${p.summary} Save them as a new version before leaving?`}
      actions={[
        { label: "Cancel", variant: "ghost", onClick: p.onCancel },
        { label: "Discard", variant: "danger", onClick: p.onDiscard },
        { label: `Save as v${p.nextVersion}`, variant: "primary", onClick: p.onSave },
      ]}
    />
  );
}

export function LeaseLostDialog(p: {
  open: boolean;
  project: string;
  onReadOnly: () => void;
  onClose: () => void;
}) {
  return (
    <ConfirmDialog
      open={p.open}
      blocking
      title={`${p.project} was opened on another computer`}
      body="Changes here are no longer saved. Keep looking in read-only mode, or close the project."
      actions={[
        { label: "Close project", variant: "ghost", onClick: p.onClose },
        { label: "Continue read-only", variant: "primary", onClick: p.onReadOnly },
      ]}
    />
  );
}

export function ReadOnlyBanner({ reason }: { reason: string }) {
  return (
    <div className="border-b border-border px-6 py-2">
      <Banner kind="info">{reason}</Banner>
    </div>
  );
}
