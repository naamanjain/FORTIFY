import type { WorkflowItem } from '../types/workflow'
import { StatusBadge } from './StatusBadge'
import { TrendIndicator, type Trend } from './TrendIndicator'

type Row = WorkflowItem & { unit_id?: string | null; trend?: Trend }
function concern(item: Row) {
  if (item.risk_band === 'HIGH') return ['Needs attention', 'high'] as const
  if (item.risk_band === 'MODERATE') return ['Worth checking', 'moderate'] as const
  return ['No current concern', 'low'] as const
}
function status(value: WorkflowItem['workflow_state']) { return ({ NEW:'New', ACKNOWLEDGED:'Acknowledged', IN_REVIEW:'Being reviewed', SUPPORT_PLANNED:'Support planned', COMPLETED:'Completed', DEFERRED:'Deferred', DISMISSED:'Dismissed' })[value] }
export function AttentionTable({ rows, onOpen }: { rows: Row[]; onOpen: (personId: string) => void }) {
  return <div className="data-table-wrap">
    <div className="table-scroll">
      <table className="data-table">
        <thead><tr><th>PERSON</th><th>UNIT</th><th>WELFARE CONCERN</th><th>CHANGE</th><th>WHAT CHANGED</th><th>REVIEW STATUS</th><th>ACTION</th></tr></thead>
        <tbody>{rows.map((row) => { const [label, tone] = concern(row); return <tr key={row.workflow_item_id} tabIndex={0} className="attention-click-row" role="link" aria-label={`Open ${row.person_id}`} onClick={() => onOpen(row.person_id)} onKeyDown={(event) => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); onOpen(row.person_id) } }}>
          <td><button className="table-person" type="button" onClick={(event) => { event.stopPropagation(); onOpen(row.person_id) }}><strong>{row.person_id}</strong><small>{row.date}</small></button></td>
          <td className="mono muted">{row.unit_id ?? '—'}</td>
          <td><StatusBadge label={label} tone={tone} /></td>
          <td><TrendIndicator trend={row.trend ?? (row.risk_band === 'HIGH' ? 'RISING' : 'STABLE')} /></td>
          <td className="indicator-copy">{row.rationale?.split(';')[0] || 'Multiple operational indicators are being reviewed.'}</td>
          <td className="muted">{status(row.workflow_state)}</td>
          <td><button className="button table-action" type="button" onClick={(event) => { event.stopPropagation(); onOpen(row.person_id) }}>{row.workflow_state === 'NEW' ? 'Review Case' : 'Open'}</button></td>
        </tr>})}</tbody>
      </table>
    </div>
    <div className="table-footer"><span>Showing 1–{rows.length} active cases</span><span>Latest available day</span></div>
  </div>
}
