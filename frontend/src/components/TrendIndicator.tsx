import { Icon } from './Icon'
export type Trend = 'RISING' | 'STABLE' | 'IMPROVING'
export function TrendIndicator({ trend }: { trend: Trend }) {
  const map = {
    RISING: { label: 'Getting worse', icon: 'arrowUp' as const, className: 'rising' },
    STABLE: { label: 'No major change', icon: 'arrowRight' as const, className: 'stable' },
    IMPROVING: { label: 'Improving', icon: 'arrowDown' as const, className: 'improving' },
  }[trend]
  return <span className={`trend-indicator ${map.className}`}><Icon name={map.icon} size={14} />{map.label}</span>
}
