import { CircleAlert, Info, TriangleAlert } from "lucide-react";
import type { ReactNode } from "react";

import { cn } from "@/lib/cn";

export type BannerKind = "danger" | "warning" | "info";

const KIND: Record<BannerKind, { icon: typeof Info; edge: string; tint: string }> = {
  danger: { icon: CircleAlert, edge: "shadow-[inset_3px_0_0_var(--reject)]", tint: "text-reject" },
  warning: { icon: TriangleAlert, edge: "shadow-[inset_3px_0_0_var(--maybe)]", tint: "text-maybe" },
  info: { icon: Info, edge: "shadow-[inset_3px_0_0_var(--info)]", tint: "text-info" },
};

/** Inline notice with a coloured edge (S2 wrong password, S10 preliminary banner). */
export function Banner({ kind, children, action }: { kind: BannerKind; children: ReactNode; action?: ReactNode }) {
  const k = KIND[kind];
  const Icon = k.icon;
  return (
    <div
      role={kind === "danger" ? "alert" : "status"}
      className={cn("flex items-center gap-3 rounded-md border border-border bg-surface-1 px-3.5 py-2.5", k.edge)}
    >
      <Icon aria-hidden className={cn("size-4 shrink-0", k.tint)} />
      <span className="flex-1 text-small text-text">{children}</span>
      {action}
    </div>
  );
}
