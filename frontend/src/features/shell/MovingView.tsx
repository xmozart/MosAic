/** S0: a trip's data is moving to MosAic's storage (ADR 0055). The move reports no
 * progress, so the bar is indeterminate. */
export function MovingView() {
  return (
    <div role="status" className="flex flex-1 flex-col items-center justify-center gap-3 p-8 text-center">
      <h1 className="text-heading text-text">Moving this trip's data to MosAic's storage</h1>
      <p className="max-w-[520px] text-body text-text-muted">
        Its database can't stay in the footage folder here, so MosAic is moving its analysis and previews. Your footage isn't touched. This happens once.
      </p>
      <span aria-hidden className="h-1.5 w-72 overflow-hidden rounded-full bg-surface-3">
        <span className="block h-full w-full animate-pulse rounded-full bg-accent" />
      </span>
    </div>
  );
}
