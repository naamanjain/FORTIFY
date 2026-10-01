import { Icon } from './Icon'
export type Trend = 'RISING' | 'STABLE' | 'IMPROVING'
export function TrendIndicator({ trend }: { trend: Trend | null }) {
  // A trend the backend has not computed is shown as unknown, not as a
  // fabricated "no major change" verdict.
  const map = trend === null ? null : {
    RISING: { label: 'Getting worse', icon: 'arrowUp' as const, className: 'rising' },
    STABLE: { label: 'No major change', icon: 'arrowRight' as const, className: 'stable' },
    IMPROVING: { label: 'Improving', icon: 'arrowDown' as const, className: 'improving' },
  }[trend]
  if (!map) return <span className="trend-indicator stable"><Icon name="arrowRight" size={14} />Trend unknown</span>
  return <span className={`trend-indicator ${map.className}`}><Icon name={map.icon} size={14} />{map.label}</span>
}
