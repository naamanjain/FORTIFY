import { useEffect, useMemo, useState } from 'react'
import { AppShell } from '../components/AppShell'
import { AttentionTable } from '../components/AttentionTable'
import { FilterBar } from '../components/FilterBar'
import { LoadingSkeleton, EmptyState, ErrorState } from '../components/StatePanels'
import { PageChrome } from '../components/PageChrome'
import { Icon } from '../components/Icon'
import { getDashboardOverview, getPendingWorkflow, searchDashboard } from '../services/api'
import type { DashboardOverview } from '../types/dashboard'
import type { WorkflowItem } from '../types/workflow'
import type { Trend } from '../components/TrendIndicator'

type SearchResult = { type: 'PERSONNEL' | 'UNIT'; key: string; title: string; detail: string }
type Row = WorkflowItem & { unit_id?: string | null; trend?: Trend }
const nav = [
  { id: 'attention', label: 'Attention', path: '/attention', icon: 'alert' as const },
  { id: 'personnel', label: 'Personnel', path: '/personnel', icon: 'person' as const },
  { id: 'units', label: 'Units', path: '/units', icon: 'units' as const },
  { id: 'trends', label: 'Trends', path: '/trends', icon: 'trend' as const },
  { id: 'data', label: 'Data & Signals', path: '/data/signals', icon: 'data' as const },
  { id: 'reviews', label: 'Reviews', path: '/reviews', icon: 'review' as const },
  { id: 'governance', label: 'Governance', path: '/governance', icon: 'audit' as const },
]
function push(path:string){ window.history.pushState({},'',path); window.dispatchEvent(new PopStateEvent('popstate')) }
function trendFor(item: WorkflowItem, all: WorkflowItem[]): Trend {
  const histories = all.filter(x => x.person_id === item.person_id).sort((a,b)=>a.date.localeCompare(b.date))
  const idx = histories.findIndex(x => x.date === item.date)
  if (idx <= 0) return item.risk_band === 'HIGH' ? 'RISING' : 'STABLE'
  const previous = histories[idx-1]
  return item.risk_band !== previous.risk_band && item.risk_band === 'HIGH' ? 'RISING' : item.risk_band === 'HIGH' ? 'RISING' : 'STABLE'
}
export default function Attention() {
  const [overview,setOverview]=useState<DashboardOverview|null>(null), [items,setItems]=useState<WorkflowItem[]>([]), [loading,setLoading]=useState(true), [error,setError]=useState<string|null>(null)
  const [query,setQuery]=useState(''), [searchOpen,setSearchOpen]=useState(false), [searchResults,setSearchResults]=useState<SearchResult[]>([]), [path,setPath]=useState(window.location.pathname), [notificationsOpen,setNotificationsOpen]=useState(false)
  const [concern,setConcern]=useState<'all'|'HIGH'|'MODERATE'|'LOW'>('all'), [change,setChange]=useState<'all'|'RISING'|'STABLE'|'IMPROVING'>('all'), [status,setStatus]=useState<'all'|'NEW'|'ACKNOWLEDGED'|'IN_REVIEW'|'SUPPORT_PLANNED'|'DEFERRED'>('all'), [unit,setUnit]=useState('all')
  const load=async()=>{setLoading(true);setError(null);try{const [o,w]=await Promise.all([getDashboardOverview(),getPendingWorkflow(200)]);setOverview(o);setItems(w.items)}catch(e){setError(e instanceof Error?e.message:"We couldn't load today's cases.")}finally{setLoading(false)}}
  useEffect(()=>{void load();const h=()=>setPath(window.location.pathname);window.addEventListener('popstate',h);return()=>window.removeEventListener('popstate',h)},[])
  useEffect(()=>{if(!query.trim()){setSearchResults([]);return}const t=setTimeout(()=>void searchDashboard(query.trim()).then(r=>setSearchResults(r.results)).catch(()=>setSearchResults([])),150);return()=>clearTimeout(t)},[query])
  const latest=overview?.as_of_date ?? ''
  const active=useMemo<Row[]>(()=>items.filter(x=>x.date===latest&&x.risk_band!=='LOW'&&!['COMPLETED','DISMISSED'].includes(x.workflow_state)).map(x=>({...x,trend:trendFor(x,items)})),[items,latest])
  const unitOptions=useMemo(()=>Array.from(new Set(active.map(x=>x.unit_id).filter(Boolean) as string[])).sort(),[active])
  const filtered=useMemo(()=>active.filter(x=>(concern==='all'||x.risk_band===concern)&&(change==='all'||x.trend===change)&&(status==='all'||x.workflow_state===status)&&(unit==='all'||x.unit_id===unit)),[active,concern,change,status,unit])
  const openPerson=(personId:string)=>push(`/person/${encodeURIComponent(personId)}`)
  const selectSearch=(r:SearchResult)=>{setSearchOpen(false);setQuery('');push(r.type==='PERSONNEL'?`/person/${encodeURIComponent(r.key)}`:`/units/${encodeURIComponent(r.key)}`)}
  if(loading)return <AppShell navItems={nav} activePath="/attention" query={query} searchResults={searchResults} searchOpen={searchOpen} onQueryChange={(v)=>{setQuery(v);setSearchOpen(!!v.trim())}} onSearchSelect={selectSearch} onNavigate={push} notificationsOpen={notificationsOpen} onToggleNotifications={()=>setNotificationsOpen(v=>!v)} searchEnabled={false}><LoadingSkeleton/></AppShell>
  if(error&&!overview)return <AppShell navItems={nav} activePath="/attention" query={query} searchResults={searchResults} searchOpen={searchOpen} onQueryChange={(v)=>{setQuery(v);setSearchOpen(!!v.trim())}} onSearchSelect={selectSearch} onNavigate={push} notificationsOpen={notificationsOpen} onToggleNotifications={()=>setNotificationsOpen(v=>!v)} searchEnabled={false}><ErrorState message={error} onRetry={()=>void load()}/></AppShell>
  if(!overview)return null
  const high=active.filter(x=>x.risk_band==='HIGH').length, rising=active.filter(x=>x.trend==='RISING').length
  return <AppShell navItems={nav} activePath="/attention" query={query} searchResults={searchResults} searchOpen={searchOpen} onQueryChange={(v)=>{setQuery(v);setSearchOpen(!!v.trim())}} onSearchSelect={selectSearch} onNavigate={push} notificationsOpen={notificationsOpen} onToggleNotifications={()=>setNotificationsOpen(v=>!v)} searchEnabled={false}>
    <PageChrome title="Attention" subtitle={`Cases that may need your review · ${overview.personnel_count} synthetic personnel`} right={<div className="freshness"><span className="fresh-dot"/>Updated {overview.as_of_date}</div>}>
      <div className="attention-summary"><span><strong>{active.length}</strong> active cases</span><span><b className="dot high"/>{high} needs attention</span><span><b className="dot moderate"/>{active.filter(x=>x.risk_band==='MODERATE').length} worth checking</span><span><Icon name="trend" size={14}/>{rising} getting worse</span></div>
      <FilterBar concern={concern} change={change} status={status} unit={unit} units={unitOptions} onConcern={setConcern} onChange={setChange} onStatus={setStatus} onUnit={setUnit} onClear={()=>{setConcern('all');setChange('all');setStatus('all');setUnit('all')}}/>
      {filtered.length?<AttentionTable rows={filtered} onOpen={openPerson}/>:<EmptyState title="No cases match these filters" subtitle="Try removing one or more filters to see active cases." actionLabel="Clear filters" onAction={()=>{setConcern('all');setChange('all');setStatus('all');setUnit('all')}}/>}
      <div className="page-note"><span>Demonstration environment · synthetic operational data</span><span>Technical model details stay behind the review experience.</span></div>
    </PageChrome>
  </AppShell>
}
