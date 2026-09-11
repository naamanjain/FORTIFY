export function LoadingSkeleton({ rows = 7 }: { rows?: number }) {
  return <div className="queue-panel loading-skeleton" aria-label="Loading cases">{Array.from({ length: rows }, (_, index) => <div key={index} className="skeleton-row" />)}</div>
}
