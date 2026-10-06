import type { ReactNode } from "react";

import { Button } from "@/components/ui/Button";

export type SettingSource = "default" | "user" | "project" | "installation" | "admin";

const FROM: Record<SettingSource, string> = {
  default: "default",
  user: "your preference",
  project: "this project",
  installation: "this computer",
  admin: "your admin",
};

export interface SettingRowProps {
  label: string;
  description?: string;
  source: SettingSource;
  control: ReactNode; // shows the effective value
  onReset?: () => void; // shown unless the value is the default
}

/** Effective value, "From: …" and Reset (COMPONENTS.md SettingRow; the five config scopes). */
export function SettingRow({ label, description, source, control, onReset }: SettingRowProps) {
  return (
    <div className="flex items-center justify-between gap-6 border-b border-border py-3.5">
      <div className="flex min-w-0 flex-col gap-0.5">
        <span className="text-body text-text">{label}</span>
        {description && <span className="text-small text-text-muted">{description}</span>}
        <span className="text-caption font-normal text-text-faint" data-source={source}>
          From: {FROM[source]}
        </span>
      </div>
      <div className="flex shrink-0 items-center gap-2">
        {control}
        {source !== "default" && onReset && (
          <Button variant="ghost" size="sm" onClick={onReset}>
            Reset
          </Button>
        )}
      </div>
    </div>
  );
}
