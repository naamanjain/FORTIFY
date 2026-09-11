import { useEffect, useMemo, useState } from 'react'
import { AppShell } from '../components/AppShell'
import { AttentionTable } from '../components/AttentionTable'
import { EmptyState, ErrorState } from '../components/StatePanels'
import { FilterBar } from '../components/FilterBar'
import { LoadingSkeleton } from '../components/LoadingSkeleton'
import { getDashboardOverview, getPendingWorkflow, getPersonnel, getWorkflowItem, searchDashboard } from '../services/api'
import type { DashboardOverview } from '../types/dashboard'
import type { WorkflowItem } from '../types/workflow'

type NavItem = { id: 'attention' | 'personnel' | 'units' | 'trends' | 'data' | 'reviews'; label: string; enabled: boolean }
type HumanConcern = 'all' | 'high' | 'moderate' | 'low'
type HumanChange = 'all' | 'rising' | 'stable'
type HumanStatus = 'all' | 'new' | 'acknowledged' | 'in_review' | 'support_planned' | 'deferred'

type SearchResult = { type: 'PERSONNEL' | 'UNIT'; key: string; title: string; detail: string }
type AttentionRow = WorkflowItem & { unit_id: string; change: { key: 'rising' | 'stable'; label: string } }

function humanize(value: string) { return value.replaceAll('_', ' ').toLowerCase().replace(/(^|\s)\S/g, (s) => s.toUpperCase()) }
function formatConcern(band: WorkflowItem['risk_band']) { return band === 'HIGH' ? 'Needs attention' : band === 'MODERATE' ? 'Worth checking' : 'No current concern' }
function changeFor(item: WorkflowItem): AttentionRow['change'] {
  if (item.risk_band === 'HIGH' || item.priority === 'HIGH' || item.feasibility_status === 'NOT_FEASIBLE') return { key: 'rising', label: 'Getting worse' }
  if (item.constraint_flags && item.constraint_flags !== 'NONE') return { key: 'rising', label: 'Needs review' }
  return { key: 'stable', label: 'No major change' }
}

export default function Dashboard() {
  const [overview, setOverview] = useState<DashboardOverview | null>(null)
  const [workflow, setWorkflow] = useState<WorkflowItem[]>([])
  const [personnelMap, setPersonnelMap] = useState<Record<string, string>>({})
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [query, setQuery] = useState('')
  const [searchOpen, setSearchOpen] = useState(false)
  const [searchResults, setSearchResults] = useState<SearchResult[]>([])
  const [selected, setSelected] = useState<WorkflowItem | null>(null)
  const [concern, setConcern] = useState<HumanConcern>('all')
  const [change, setChange] = useState<HumanChange>('all')
  const [status, setStatus] = useState<HumanStatus>('all')
  const [unit, setUnit] = useState('all')

  const load = async () => {
    setLoading(true); setError(null)
    try {
      const [overviewResponse, workflowResponse, personnelResponse] = await Promise.all([getDashboardOverview(), getPendingWorkflow(90), getPersonnel()])
      setOverview(overviewResponse)
      setWorkflow(workflowResponse.items)
      setPersonnelMap(Object.fromEntries(personnelResponse.items.map((row) => [row.person_id, row.unit_id])))
    } catch (err) {
      setError(err instanceof Error ? err.message : "We couldn't load today's cases.")
    } finally { setLoading(false) }
  }

  useEffect(() => { void load() }, [])

  useEffect(() => {
    const value = query.trim()
    if (!value) { setSearchResults([]); return }
    const timer = window.setTimeout(() => {
      void searchDashboard(value)
        .then((response) => setSearchResults(response.results.slice(0, 6).map((result) => ({ type: result.type, key: result.key, title: result.title, detail: result.detail }))))
        .catch(() => setSearchResults([]))
    }, 180)
    return () => window.clearTimeout(timer)
  }, [query])

  const activeRows = useMemo<AttentionRow[]>(() => workflow.filter((item) => !['COMPLETED', 'DISMISSED'].includes(item.workflow_state)).map((item) => ({ ...item, unit_id: personnelMap[item.person_id] ?? '—', change: changeFor(item) })), [personnelMap, workflow])
  const unitOptions = useMemo(() => Array.from(new Set(activeRows.map((row) => row.unit_id).filter((value) => value !== '—'))).sort(), [activeRows])
  const filteredRows = useMemo(() => {
    return activeRows.filter((row) => {
      const concernMatch = concern === 'all' || row.risk_band.toLowerCase() === concern
      const changeMatch = change === 'all' || row.change.key === change
      const statusMatch = status === 'all' || row.workflow_state.toLowerCase() === status
      const unitMatch = unit === 'all' || row.unit_id === unit
      return concernMatch && changeMatch && statusMatch && unitMatch
    })
  }, [activeRows, change, concern, status, unit])

  const highOpen = activeRows.filter((item) => item.risk_band === 'HIGH').length
  const worsening = activeRows.filter((item) => item.change.key === 'rising').length
  const newCount = activeRows.filter((item) => item.workflow_state === 'NEW').length

  const clearFilters = () => { setQuery(''); setConcern('all'); setChange('all'); setStatus('all'); setUnit('all') }
  const openRow = async (workflowItemId: string) => {
    try { setSelected(await getWorkflowItem(workflowItemId)) }
    catch (err) { setError(err instanceof Error ? err.message : "We couldn't load this case.") }
  }
  const selectSearchResult = (result: SearchResult) => {
    setSearchOpen(false)
    if (result.type === 'PERSONNEL') {
      const row = activeRows.find((item) => item.person_id === result.key)
      if (row) setSelected(row)
    } else setUnit(result.key)
  }

  const navItems: NavItem[] = [
    { id: 'attention', label: 'Attention', enabled: true },
    { id: 'personnel', label: 'Personnel', enabled: false },
    { id: 'units', label: 'Units', enabled: false },
    { id: 'trends', label: 'Trends', enabled: false },
    { id: 'data', label: 'Data', enabled: false },
    { id: 'reviews', label: 'Reviews', enabled: false },
  ]

  const shellSearchChange = (value: string) => { setQuery(value); setSearchOpen(Boolean(value)) }

  if (loading) return <AppShell navItems={navItems} query={query} searchResults={[]} searchOpen={false} onQueryChange={shellSearchChange} onSearchSelect={selectSearchResult}><LoadingSkeleton /></AppShell>
  if (error && !overview) return <AppShell navItems={navItems} query={query} searchResults={[]} searchOpen={false} onQueryChange={shellSearchChange} onSearchSelect={selectSearchResult}><ErrorState message={error} onRetry={() => void load()} /></AppShell>
  if (!overview) return null

  return <AppShell navItems={navItems} query={query} searchResults={searchResults} searchOpen={searchOpen} onQueryChange={shellSearchChange} onSearchSelect={selectSearchResult}>
    <div className="attention-page">
      <div className="attention-header"><div><div className="breadcrumb">ATTENTION / QUEUE</div><h1>Attention</h1><p>Cases that may need your review</p></div><div className="updated-chip"><span className="status-dot" />Updated today</div></div>
      <div className="summary-line"><strong>{activeRows.length} {activeRows.length === 1 ? 'case' : 'cases'} need review</strong><span>·</span><span>{worsening} {worsening === 1 ? 'is' : 'are'} getting worse</span><span>·</span><span>{overview.personnel_count} synthetic personnel in this demonstration</span></div>
      <FilterBar concern={concern} change={change} status={status} unit={unit} units={unitOptions} onConcern={setConcern} onChange={setChange} onStatus={setStatus} onUnit={setUnit} onClear={clearFilters} />
      <div className="attention-layout">
        <AttentionTable rows={filteredRows} selectedId={selected?.workflow_item_id} onOpen={(id) => void openRow(id)} />
        <aside className="attention-side-panel">
          {selected ? <CasePreview item={selected} unitId={personnelMap[selected.person_id] ?? '—'} onClose={() => setSelected(null)} /> : <><div className="side-kicker">TODAY</div><h2>{highOpen} {highOpen === 1 ? 'case needs' : 'cases need'} focused attention.</h2><div className="side-stat"><span>New</span><strong>{newCount}</strong></div><div className="side-stat"><span>Getting worse</span><strong>{worsening}</strong></div><div className="side-stat"><span>Open cases</span><strong>{activeRows.length}</strong></div><div className="side-note">Select a case to review its current operational context and suggested next step.</div></>}
        </aside>
      </div>
      {filteredRows.length === 0 && <EmptyState onClear={clearFilters} />}
      {error && <div className="inline-error"><span>{error}</span><button onClick={() => setError(null)}>Dismiss</button></div>}
    </div>
  </AppShell>
}

function CasePreview({ item, unitId, onClose }: { item: WorkflowItem; unitId: string; onClose: () => void }) {
  return <div className="case-preview"><div className="case-preview-head"><div><span className="side-kicker">CASE PREVIEW</span><h2>{item.person_id}</h2><p>{unitId} · {item.date}</p></div><button className="close-button" onClick={onClose} aria-label="Close case preview">×</button></div><div className={`preview-signal ${item.risk_band.toLowerCase()}`}><span>{formatConcern(item.risk_band)}</span><strong>{changeFor(item).label}</strong></div><div className="preview-grid"><div><span>Review</span><strong>{humanize(item.workflow_state)}</strong></div><div><span>Suggested next step</span><strong>{humanize(item.recommended_action)}</strong></div><div><span>Can support be scheduled now?</span><strong>{humanize(item.feasibility_status)}</strong></div></div><div className="preview-copy"><span className="side-kicker">WHY THIS CASE</span><p>{item.rationale || 'The system identified a meaningful pattern in the available operational data.'}</p>{item.constraint_flags && item.constraint_flags !== 'NONE' ? <small>Operational context: {humanize(item.constraint_flags)}</small> : null}</div><div className="preview-foot"><span>🔒 Access logged</span><span>{item.requires_human_review ? 'Human review required' : 'Human oversight retained'}</span></div></div>
}
