import { cn } from "@/lib/cn";

export interface Section {
  id: string;
  label: string;
  /** The Danger zone reads in the reject color. */
  danger?: boolean;
}

/** The settings screens' left nav (S21, S22): one entry per section; the active one is
 * raised. Selecting one scrolls to it (the screen does the scrolling). */
export function SectionNav({ title, sections, active, onSelect }: { title: string; sections: Section[]; active: string; onSelect: (id: string) => void }) {
  return (
    <nav aria-label={title} className="flex w-[220px] shrink-0 flex-col gap-0.5 border-r border-border px-3.5 py-6">
      <span className="px-3 pb-2 text-caption font-semibold text-text-faint">{title}</span>
      {sections.map((s) => (
        <a
          key={s.id}
          href={`#section-${s.id}`}
          aria-current={s.id === active ? "location" : undefined}
          onClick={(e) => {
            e.preventDefault();
            onSelect(s.id);
          }}
          className={cn(
            "rounded-[8px] px-3 py-[9px] text-body focus-visible:outline-2 focus-visible:outline-accent",
            s.id === active ? "bg-surface-2 text-text" : "text-text-muted hover:text-text",
            s.danger && "text-reject hover:text-reject",
          )}
        >
          {s.label}
        </a>
      ))}
    </nav>
  );
}
