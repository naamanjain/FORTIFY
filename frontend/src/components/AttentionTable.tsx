import type { WorkflowItem } from '../types/workflow'
import { StatusBadge } from './StatusBadge'
import { TrendIndicator, type Trend } from './TrendIndicator'

type Row = WorkflowItem & { unit_id?: string | null; trend?: Trend }
function concern(item: Row) {
  if (item.risk_band === 'HIGH') return ['Needs attention', 'high'] as const
  if (item.risk_band === 'MODERATE') return ['Worth checking', 'moderate'] as const
  return ['No current concern', 'low'] as const
}
function status(value: WorkflowItem['workflow_state']) { const labels: Record<WorkflowItem['workflow_state'], string> = { NEW:'New', ACKNOWLEDGED:'Acknowledged', IN_REVIEW:'Being reviewed', SUPPORT_PLANNED:'Support planned', SUPPORT_COMPLETED:'Support completed', FOLLOW_UP_SCHEDULED:'Follow-up scheduled', FOLLOW_UP_DUE:'Follow-up due', FOLLOW_UP_COMPLETED:'Follow-up completed', CLOSED:'Closed', COMPLETED:'Completed', DEFERRED:'Deferred', DISMISSED:'Dismissed' }; return labels[value] }
export function AttentionTable({ rows, onOpen }: { rows: Row[]; onOpen: (personId: string) => void }) {
  return <div className="data-table-wrap">
    <div className="table-scroll">
      <table className="data-table">
        <thead><tr><th>PERSON</th><th>UNIT</th><th>WELFARE CONCERN</th><th>CHANGE</th><th>WHAT CHANGED</th><th>REVIEW STATUS</th><th>ACTION</th></tr></thead>
        <tbody>{rows.map((row) => { const [label, tone] = concern(row); return <tr key={row.workflow_item_id} tabIndex={0} className="attention-click-row" role="link" aria-label={`Open ${row.person_id}`} onClick={() => onOpen(row.person_id)} onKeyDown={(event) => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); onOpen(row.person_id) } }}>
          <td><button className="table-person" type="button" onClick={(event) => { event.stopPropagation(); onOpen(row.person_id) }}><strong>{row.person_id}</strong><small>{row.date}</small></button></td>
          <td className="mono muted">{row.unit_id ?? '—'}</td>
          <td><StatusBadge label={label} tone={tone} /></td>
          <td><TrendIndicator trend={row.trend ?? 'STABLE'} /></td>
          <td className="indicator-copy">{row.rationale?.split(';')[0] || 'Operational summary not available for this day.'}</td>
          <td className="muted">{status(row.workflow_state)}</td>
          <td><button className="button table-action" type="button" onClick={(event) => { event.stopPropagation(); onOpen(row.person_id) }}>{row.workflow_state === 'NEW' ? 'Review Case' : 'Open'}</button></td>
        </tr>})}</tbody>
      </table>
    </div>
    <div className="table-footer"><span>{rows.length} active cases shown</span><span>Latest available day</span></div>
  </div>
}
