export interface StoragePart {
  label: string; // "Previews"
  bytes: number;
  size: string; // display: "12.4 GB"
  regenerable: boolean;
}

// Reference order (S21), then neutrals. Never `user` (reserved for the user's decisions)
// or the disposition colours other than `use`, which the reference draws (ADR 0033).
const SHADES = ["bg-info", "bg-accent", "bg-use", "bg-text-muted", "bg-text-faint"];

/** Stacked bar with Regenerable / Kept tags (COMPONENTS.md StorageBreakdown; S21). */
export function StorageBreakdown({ parts }: { parts: StoragePart[] }) {
  const total = parts.reduce((s, p) => s + p.bytes, 0) || 1;
  return (
    <div className="flex flex-col gap-3">
      <div className="flex h-2.5 overflow-hidden rounded-full bg-surface-3" role="img" aria-label="Storage by kind">
        {parts.map((p, i) => (
          <span key={p.label} className={SHADES[i % SHADES.length]} style={{ width: `${(p.bytes / total) * 100}%` }} />
        ))}
      </div>
      <ul className="flex flex-col gap-1.5">
        {parts.map((p, i) => (
          <li key={p.label} className="flex items-center gap-2.5 text-small">
            <span className={`size-2.5 rounded-full ${SHADES[i % SHADES.length]}`} />
            <span className="text-text">{p.label}</span>
            <span className="rounded-full border border-border px-1.5 text-micro text-text-muted">
              {p.regenerable ? "Regenerable" : "Kept"}
            </span>
            <span className="mono ml-auto text-timecode text-text-muted">{p.size}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
