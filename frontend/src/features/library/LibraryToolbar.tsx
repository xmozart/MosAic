import { ChevronDown, Search, Sparkles } from "lucide-react";
import { DropdownMenu } from "radix-ui";
import { forwardRef, useState, type KeyboardEvent } from "react";

import { Button } from "@/components/ui/Button";
import { Segmented } from "@/components/ui/Segmented";
import { cn } from "@/lib/cn";
import type { Density } from "@/lib/domain";

import { SHOT_TYPES, type Filters, type Grouping, type StatusFilter } from "./model";

export interface Option<T> {
  value: T;
  label: string;
}

function Chip<T>(p: { label: string; active: boolean; options: Option<T | undefined>[]; value: T | undefined; onChange: (v: T | undefined) => void }) {
  const current = p.options.find((o) => o.value === p.value);
  return (
    <DropdownMenu.Root>
      <DropdownMenu.Trigger asChild>
        <button
          type="button"
          className={cn(
            "inline-flex items-center gap-1.5 rounded-full border px-[11px] py-1.5 text-caption focus-visible:outline-2 focus-visible:outline-accent",
            p.active ? "border-accent bg-accent-soft text-text" : "border-border bg-surface-1 text-text-muted hover:text-text",
          )}
        >
          {p.active && current && current.value !== undefined ? current.label : p.label}
          <ChevronDown aria-hidden className="size-3.5" />
        </button>
      </DropdownMenu.Trigger>
      <DropdownMenu.Portal>
        <DropdownMenu.Content
          align="start"
          sideOffset={6}
          className="z-50 flex max-h-80 min-w-44 flex-col overflow-y-auto rounded-md border border-border bg-surface-2 p-1 shadow-[0_12px_32px_rgba(0,0,0,0.4)]"
        >
          <DropdownMenu.RadioGroup
            value={String(p.options.findIndex((o) => o.value === p.value))}
            onValueChange={(i) => p.onChange(p.options[Number(i)]?.value)}
          >
            {p.options.map((o, i) => (
              <DropdownMenu.RadioItem
                key={i}
                value={String(i)}
                className="cursor-pointer rounded-sm px-2.5 py-1.5 text-small text-text outline-none data-[highlighted]:bg-surface-3 data-[state=checked]:font-semibold"
              >
                {o.label}
              </DropdownMenu.RadioItem>
            ))}
          </DropdownMenu.RadioGroup>
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  );
}

export type StatusView = "default" | "everything" | StatusFilter;

const STATUS: Option<StatusView | undefined>[] = [
  { value: "default", label: "USE · MAYBE" },
  { value: "everything", label: "Everything, rejected too" },
  { value: "USE", label: "USE only" },
  { value: "MAYBE", label: "MAYBE only" },
  { value: "REJECT", label: "REJECT only" },
  { value: "none", label: "Not analyzed" },
];

export interface LibraryToolbarProps {
  filters: Filters;
  statusView: StatusView;
  onStatusView: (v: StatusView) => void;
  onFilters: (patch: Partial<Filters>) => void;
  days: Option<string>[];
  cameras: Option<number>[];
  group: Grouping;
  onGroup: (g: Grouping) => void;
  density: Density;
  onDensity: (d: Density) => void;
  onSearch: (q: string) => void;
  onDeepen: () => void;
  onCreateEdit: () => void;
}

/** S10 toolbar (COMPONENTS.md LibraryToolbar): search, filter chips, group, density. */
export const LibraryToolbar = forwardRef<HTMLInputElement, LibraryToolbarProps>(function LibraryToolbar(p, searchRef) {
  const [q, setQ] = useState("");
  const f = p.filters;
  const onKey = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter" && q.trim()) p.onSearch(q.trim());
    if (e.key === "Escape") {
      setQ("");
      e.currentTarget.blur();
    }
  };
  return (
    <div className="flex flex-col gap-3 border-b border-border px-6 py-4">
      <div className="flex items-center gap-3">
        <label className="relative min-w-0 flex-1">
          <Search aria-hidden className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-text-faint" />
          <input
            ref={searchRef}
            aria-label="Search footage"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            onKeyDown={onKey}
            placeholder="Search: “monkeys in trees”, “people laughing”"
            className="h-[38px] w-full rounded-md border border-border bg-surface-3 pr-3 pl-9 text-body text-text placeholder:text-text-faint focus-visible:outline-2 focus-visible:outline-accent"
          />
        </label>
        <Button variant="ghost" onClick={p.onDeepen}>
          Deepen analysis…
        </Button>
        <Button variant="primary" onClick={p.onCreateEdit}>
          <Sparkles /> Create edit
        </Button>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <Chip label="Day" active={f.day !== undefined} options={[{ value: undefined, label: "Every day" }, ...p.days]} value={f.day} onChange={(day) => p.onFilters({ day })} />
        <Chip label="Camera" active={f.camera !== undefined} options={[{ value: undefined, label: "Every camera" }, ...p.cameras]} value={f.camera} onChange={(camera) => p.onFilters({ camera })} />
        <Chip
          label="Type"
          active={f.kind !== undefined}
          options={[
            { value: undefined, label: "Videos and photos" },
            { value: "video" as const, label: "Videos" },
            { value: "photo" as const, label: "Photos" },
          ]}
          value={f.kind}
          onChange={(kind) => p.onFilters({ kind })}
        />
        <Chip label="USE · MAYBE" active options={STATUS} value={p.statusView} onChange={(v) => p.onStatusView(v ?? "default")} />
        <Chip
          label="Rating"
          active={f.min_stars !== undefined}
          options={[{ value: undefined, label: "Any rating" }, ...[1, 2, 3, 4, 5].map((n) => ({ value: n, label: `${"★".repeat(n)}${n < 5 ? " or more" : ""}` }))]}
          value={f.min_stars}
          onChange={(min_stars) => p.onFilters({ min_stars })}
        />
        <Chip label="Shot type" active={f.shot_type !== undefined} options={[{ value: undefined, label: "Any shot" }, ...SHOT_TYPES]} value={f.shot_type} onChange={(shot_type) => p.onFilters({ shot_type })} />
        <Chip
          label="Has speech"
          active={f.has_speech !== undefined}
          options={[
            { value: undefined, label: "With or without speech" },
            { value: true, label: "Has speech" },
            { value: false, label: "No speech" },
          ]}
          value={f.has_speech}
          onChange={(has_speech) => p.onFilters({ has_speech })}
        />
        <Chip
          label="More"
          active={f.include !== undefined}
          options={[
            { value: undefined, label: "Any include rule" },
            { value: "always" as const, label: "Always included" },
            { value: "never" as const, label: "Never included" },
          ]}
          value={f.include}
          onChange={(include) => p.onFilters({ include })}
        />
        <span className="ml-auto flex items-center gap-3">
          <span className="text-caption text-text-muted">Group</span>
          <Segmented
            label="Group"
            value={p.group}
            onChange={p.onGroup}
            options={[
              { value: "day", label: "Day" },
              { value: "camera", label: "Camera" },
              { value: "similar", label: "Similar" },
            ]}
          />
          <Segmented
            label="Density"
            value={p.density}
            onChange={p.onDensity}
            options={[
              { value: "comfortable", label: "Comfortable" },
              { value: "compact", label: "Compact" },
            ]}
          />
        </span>
      </div>
    </div>
  );
});
