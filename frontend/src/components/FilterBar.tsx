type Concern = 'all' | 'HIGH' | 'MODERATE' | 'LOW'
type Change = 'all' | 'RISING' | 'STABLE' | 'IMPROVING'
type Status = 'all' | 'NEW' | 'ACKNOWLEDGED' | 'IN_REVIEW' | 'SUPPORT_PLANNED' | 'DEFERRED'
export function FilterBar({ concern, change, status, unit, units, onConcern, onChange, onStatus, onUnit, onClear }: {
  concern: Concern; change: Change; status: Status; unit: string; units: string[]
  onConcern: (value: Concern) => void; onChange: (value: Change) => void; onStatus: (value: Status) => void; onUnit: (value: string) => void; onClear: () => void
}) {
  const active = concern !== 'all' || change !== 'all' || status !== 'all' || unit !== 'all'
  return <div className="filter-row" aria-label="Attention filters">
    <button className={`filter-chip ${!active ? 'active' : ''}`} type="button" onClick={onClear}>All</button>
    <label><span>Unit</span><select value={unit} onChange={(e) => onUnit(e.target.value)}><option value="all">All units</option>{units.map((x) => <option key={x} value={x}>{x}</option>)}</select></label>
    <label><span>Concern</span><select value={concern} onChange={(e) => onConcern(e.target.value as Concern)}><option value="all">All</option><option value="HIGH">Needs attention</option><option value="MODERATE">Worth checking</option><option value="LOW">No current concern</option></select></label>
    <label><span>Change</span><select value={change} onChange={(e) => onChange(e.target.value as Change)}><option value="all">All</option><option value="RISING">Getting worse</option><option value="STABLE">No major change</option><option value="IMPROVING">Improving</option></select></label>
    <label><span>Status</span><select value={status} onChange={(e) => onStatus(e.target.value as Status)}><option value="all">All</option><option value="NEW">New</option><option value="ACKNOWLEDGED">Acknowledged</option><option value="IN_REVIEW">Being reviewed</option><option value="SUPPORT_PLANNED">Support planned</option><option value="DEFERRED">Deferred</option></select></label>
    <button className="link-button" type="button" onClick={onClear} disabled={!active}>Clear</button>
  </div>
}
