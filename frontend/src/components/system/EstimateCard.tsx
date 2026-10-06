export interface EstimateCardProps {
  time: string; // "About 1 h 40 m"
  cost: string; // "$2–4"
  storage: string; // "18 GB"
  basis?: string; // "From this computer's benchmark"
}

/** Time · cost · storage (COMPONENTS.md EstimateCard). */
export function EstimateCard({ time, cost, storage, basis }: EstimateCardProps) {
  const cell = (label: string, value: string) => (
    <div className="flex flex-col gap-0.5">
      <span className="text-caption text-text-faint">{label}</span>
      <span className="mono text-timecode text-text">{value}</span>
    </div>
  );
  return (
    <div className="flex flex-col gap-3 rounded-lg border border-border bg-surface-1 p-4">
      <div className="grid grid-cols-3 gap-4">
        {cell("Time", time)}
        {cell("AI cost", cost)}
        {cell("Storage", storage)}
      </div>
      {basis && <p className="text-caption font-normal text-text-muted">{basis}</p>}
    </div>
  );
}
