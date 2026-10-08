/** COMPONENTS.md EditFacts: duration, target, shots, average shot, beats, days covered,
 * photos, AI cost — label over a mono value, four to a row. */
export function EditFacts({ rows }: { rows: [string, string][] }) {
  return (
    <section aria-label="Edit facts" className="flex flex-col gap-3 rounded-lg border border-border bg-surface-1 p-4">
      <h2 className="text-caption font-semibold text-text-faint">Edit facts</h2>
      <dl className="grid grid-cols-4 gap-3">
        {rows.map(([label, value]) => (
          <div key={label} className="flex flex-col gap-0.5">
            <dt className="text-micro font-normal text-text-faint">{label}</dt>
            <dd className="mono text-timecode text-text">{value}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}
