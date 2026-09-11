export function EmptyState({ title = 'No cases need your attention right now.', subtitle = 'There are no active items in the current view.', actionLabel, onAction }: { title?: string; subtitle?: string; actionLabel?: string; onAction?: () => void }) {
  return <div className="state-panel"><div className="state-mark">✓</div><h2>{title}</h2><p>{subtitle}</p>{actionLabel && onAction ? <button className="button secondary" type="button" onClick={onAction}>{actionLabel}</button> : null}</div>
}
export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return <div className="state-panel error-panel"><div className="state-mark">!</div><h2>We couldn't load this view</h2><p>{message}</p>{onRetry ? <button className="button secondary" type="button" onClick={onRetry}>Try again</button> : null}</div>
}
export function LoadingSkeleton({ rows = 7 }: { rows?: number }) {
  return <div className="loading-table" aria-label="Loading"><div className="loading-title" />{Array.from({ length: rows }, (_, i) => <div key={i} className="loading-row"><i /><i /><i /><i /></div>)}</div>
}
