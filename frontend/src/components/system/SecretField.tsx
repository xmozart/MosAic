import { useState } from "react";

import { Button } from "@/components/ui/Button";
import { TextField } from "@/components/ui/TextField";

export interface SecretFieldProps {
  label: string; // "Anthropic API key"
  where?: string; // "Stored in macOS Keychain · added Sep 29"
  last4?: string; // present when connected
  validating?: boolean;
  status?: "ok" | "invalid";
  onSave: (value: string) => Promise<void> | void;
  onValidate: () => void;
}

/**
 * Write-only key entry (COMPONENTS.md SecretField; invariant 11): the key is typed once,
 * sent, and the field is cleared. Only "••••last4" is ever shown; nothing is kept in
 * component state after saving, and nothing goes to browser storage.
 */
export function SecretField({ label, where, last4, validating, status, onSave, onValidate }: SecretFieldProps) {
  const [editing, setEditing] = useState(!last4);
  const [value, setValue] = useState("");
  const [failed, setFailed] = useState(false);
  const save = async () => {
    const v = value;
    setValue("");
    setFailed(false);
    try {
      await onSave(v);
      setEditing(false);
    } catch {
      setFailed(true); // the key is not kept for a retry; it is typed again
    }
  };
  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-baseline justify-between gap-4">
        <span className="text-body text-text">{label}</span>
        {where && <span className="text-caption font-normal text-text-faint">{where}</span>}
      </div>
      {editing ? (
        <form
          className="flex items-end gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            if (value) void save();
          }}
        >
          <TextField
            className="flex-1"
            aria-label={label}
            type="password"
            autoComplete="off"
            spellCheck={false}
            mono
            value={value}
            onChange={(e) => setValue(e.target.value)}
            placeholder="Paste your key"
            data-1p-ignore
            data-lpignore="true"
            error={failed ? "Key wasn't saved. Try again." : undefined}
          />
          <Button type="submit" variant="primary" disabled={!value}>
            Save key
          </Button>
          {last4 && (
            <Button variant="ghost" onClick={() => (setValue(""), setEditing(false))}>
              Cancel
            </Button>
          )}
        </form>
      ) : (
        <div className="flex items-center gap-3">
          <span className="text-small text-text">
            {status === "invalid" ? (
              <span className="text-reject">Key was rejected</span>
            ) : (
              <span className="text-use">Connected</span>
            )}{" "}
            · <span className="mono text-timecode">••••{last4}</span>
          </span>
          <Button size="sm" onClick={onValidate} disabled={validating}>
            {validating ? "Validating…" : "Validate"}
          </Button>
          <Button size="sm" variant="ghost" onClick={() => setEditing(true)}>
            Replace key
          </Button>
        </div>
      )}
    </div>
  );
}
