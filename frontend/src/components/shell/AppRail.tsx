import { CircleHelp, Clapperboard, Download, House, Library, Moon, Settings, Sun } from "lucide-react";
import type { ReactNode } from "react";

import mark from "@/assets/brand/mosaic-mark.svg";
import { cn } from "@/lib/cn";

export type RailItem = "home" | "library" | "edits" | "exports" | "settings";

const ITEMS: { key: RailItem; label: string; icon: typeof House }[] = [
  { key: "home", label: "Home", icon: House },
  { key: "library", label: "Library", icon: Library },
  { key: "edits", label: "Edits", icon: Clapperboard },
  { key: "exports", label: "Exports", icon: Download },
  { key: "settings", label: "Settings", icon: Settings },
];

export interface AppRailProps {
  active: RailItem;
  /** Overall percent of running jobs (null: nothing running). */
  activityPct: number | null;
  /** A job is running now (the ring pulses only then; not when all are paused). */
  running?: boolean;
  /** Links per item; items without a link (no project open) are disabled. */
  links: Partial<Record<RailItem, string>>;
  renderLink: (href: string, children: ReactNode, className: string, label: string) => ReactNode;
  theme: "dark" | "light";
  onToggleTheme: () => void;
  onActivity?: () => void;
  /** Wraps the activity button (e.g. as a popover trigger). */
  renderActivity?: (button: ReactNode) => ReactNode;
  onHelp?: () => void;
}

function Ring({ pct, pulse }: { pct: number; pulse: boolean }) {
  const r = 18;
  const c = 2 * Math.PI * r;
  return (
    <svg viewBox="0 0 44 44" className={cn("size-11 -rotate-90", pulse && "motion-pulse animate-pulse")} aria-hidden>
      <circle cx="22" cy="22" r={r} fill="none" strokeWidth="3" className="stroke-surface-3" />
      <circle
        cx="22"
        cy="22"
        r={r}
        fill="none"
        strokeWidth="3"
        strokeLinecap="round"
        className="stroke-accent"
        strokeDasharray={c}
        strokeDashoffset={c * (1 - pct / 100)}
      />
    </svg>
  );
}

/** 72 px rail (COMPONENTS.md AppRail): logo, the five places, activity ring, theme, help. */
export function AppRail(p: AppRailProps) {
  const activity = (
    <button
      type="button"
      onClick={p.onActivity}
      aria-label={p.activityPct === null ? "Background activity: idle" : `Background activity: ${p.activityPct}%`}
      className="relative flex size-11 items-center justify-center rounded-full focus-visible:outline-2 focus-visible:outline-accent"
    >
      {p.activityPct === null ? (
        <span className="block size-2 rounded-full bg-surface-3" />
      ) : (
        <>
          <Ring pct={p.activityPct} pulse={Boolean(p.running)} />
          <span className="mono absolute text-[9px] text-text">{p.activityPct}</span>
        </>
      )}
    </button>
  );
  return (
    <nav aria-label="Main" className="flex w-[72px] shrink-0 flex-col items-center gap-1.5 border-r border-border bg-bg py-3.5">
      <img src={mark} alt="MosAic" width={32} height={32} className="mb-3.5 rounded-md" />
      {ITEMS.map(({ key, label, icon: Icon }) => {
        const href = p.links[key];
        const cls = cn(
          "flex w-14 flex-col items-center gap-1 rounded-md py-2 text-text-muted transition-colors duration-150 focus-visible:outline-2 focus-visible:outline-accent",
          key === p.active ? "bg-accent-soft text-accent" : "hover:bg-surface-2 hover:text-text",
          !href && "pointer-events-none opacity-40",
        );
        const body = (
          <>
            <Icon aria-hidden className="size-5" strokeWidth={1.8} />
            <span className="text-tag font-medium">{label}</span>
          </>
        );
        return href ? (
          <span key={key} aria-current={key === p.active ? "page" : undefined}>
            {p.renderLink(href, body, cls, label)}
          </span>
        ) : (
          <span key={key} className={cls} aria-disabled>
            {body}
          </span>
        );
      })}
      <div className="flex-1" />
      {(p.renderActivity ?? ((b: ReactNode) => b))(activity)}
      <button
        type="button"
        aria-label="Toggle theme"
        onClick={p.onToggleTheme}
        className="flex size-10 items-center justify-center rounded-md text-text-muted hover:text-text focus-visible:outline-2 focus-visible:outline-accent"
      >
        {p.theme === "dark" ? <Sun className="size-[18px]" /> : <Moon className="size-[18px]" />}
      </button>
      <button
        type="button"
        aria-label="Help"
        onClick={p.onHelp}
        className="flex size-10 items-center justify-center rounded-md text-text-muted hover:text-text focus-visible:outline-2 focus-visible:outline-accent"
      >
        <CircleHelp className="size-[18px]" />
      </button>
    </nav>
  );
}
