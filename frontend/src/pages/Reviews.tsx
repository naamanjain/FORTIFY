import { useEffect, useMemo, useState } from 'react'
import { AppShell } from '../components/AppShell'
import { PageChrome } from '../components/PageChrome'
import { AttentionTable } from '../components/AttentionTable'
import { LoadingSkeleton, ErrorState, EmptyState } from '../components/StatePanels'
import { getDashboardOverview, getPendingWorkflow } from '../services/api'
import type { DashboardOverview } from '../types/dashboard'
import type { WorkflowItem } from '../types/workflow'
import type { Trend } from '../components/TrendIndicator'

const nav=[
 {id:'attention',label:'Attention',path:'/attention',icon:'alert' as const},
 {id:'personnel',label:'Personnel',path:'/personnel',icon:'person' as const},
 {id:'units',label:'Units',path:'/units',icon:'units' as const},
 {id:'trends',label:'Trends',path:'/trends',icon:'trend' as const},
 {id:'data',label:'Data & Signals',path:'/data/signals',icon:'data' as const},
 {id:'reviews',label:'Reviews',path:'/reviews',icon:'review' as const},
 {id:'governance',label:'Governance',path:'/governance',icon:'audit' as const},
]
function push(p:string){history.pushState({},'',p);dispatchEvent(new PopStateEvent('popstate'))}
function statusLabel(s:WorkflowItem['workflow_state']){return ({NEW:'New',ACKNOWLEDGED:'Acknowledged',IN_REVIEW:'Being reviewed',SUPPORT_PLANNED:'Support planned',DEFERRED:'Deferred',COMPLETED:'Completed',DISMISSED:'Dismissed'})[s]}
export default function Reviews(){
 const [items,setItems]=useState<WorkflowItem[]>([]),[overview,setOverview]=useState<DashboardOverview|null>(null),[loading,setLoading]=useState(true),[error,setError]=useState<string|null>(null),[notificationsOpen,setNotificationsOpen]=useState(false),[section,setSection]=useState<'high'|'moderate'|'all'>('high')
 useEffect(()=>{void Promise.all([getDashboardOverview(),getPendingWorkflow(200)]).then(([o,w])=>{setOverview(o);setItems(w.items)}).catch(e=>setError(e instanceof Error?e.message:'Review queue could not be loaded.')).finally(()=>setLoading(false))},[])
 const latest=overview?.as_of_date ?? ''
 const active=useMemo(()=>items.filter(x=>x.date===latest && !['COMPLETED','DISMISSED'].includes(x.workflow_state)),[items,latest])
 const high=useMemo(()=>active.filter(x=>x.risk_band==='HIGH').map(x=>({...x,unit_id:x.unit_id??'—',trend:'RISING' as Trend})),[active])
 const moderate=useMemo(()=>active.filter(x=>x.risk_band==='MODERATE').map(x=>({...x,unit_id:x.unit_id??'—',trend:'STABLE' as Trend})),[active])
 const low=useMemo(()=>active.filter(x=>x.risk_band==='LOW').map(x=>({...x,unit_id:x.unit_id??'—',trend:'STABLE' as Trend})),[active])
 const rows=section==='high'?high:section==='moderate'?moderate:[...high,...moderate,...low]
 const open=(id:string)=>push(`/person/${encodeURIComponent(id)}`)
 if(loading)return <AppShell navItems={nav} activePath="/reviews" query="" searchResults={[]} searchOpen={false} onQueryChange={()=>{}} onSearchSelect={()=>{}} onNavigate={push} notificationsOpen={notificationsOpen} onToggleNotifications={()=>setNotificationsOpen(v=>!v)}><LoadingSkeleton/></AppShell>
 return <AppShell navItems={nav} activePath="/reviews" query="" searchResults={[]} searchOpen={false} onQueryChange={()=>{}} onSearchSelect={()=>{}} onNavigate={push} notificationsOpen={notificationsOpen} onToggleNotifications={()=>setNotificationsOpen(v=>!v)}>
  <PageChrome eyebrow="ATTENTION / REVIEWS" title="Reviews" subtitle="Work through the cases that need a human decision first">
   {error?<ErrorState message={error}/>:<>
    <div className="review-queue-summary">
      <button type="button" className={section==='high'?'review-section active':'review-section'} onClick={()=>setSection('high')}><span><i className="dot high"/>Needs attention</span><strong>{overview?.risk_band_counts?.HIGH??high.length}</strong><small>Start here</small></button>
      <button type="button" className={section==='moderate'?'review-section active':'review-section'} onClick={()=>setSection('moderate')}><span><i className="dot moderate"/>Worth checking</span><strong>{overview?.risk_band_counts?.MODERATE??moderate.length}</strong><small>After high-priority cases</small></button>
      <button type="button" className={section==='all'?'review-section active':'review-section'} onClick={()=>setSection('all')}><span>All monitored personnel</span><strong>{overview?.personnel_count??0}</strong><small>Keep lower-priority records accessible</small></button>
    </div>
    {rows.length?<AttentionTable rows={rows as any} onOpen={open}/>:<EmptyState title={section==='high'?'No one currently needs attention.':'No cases in this section.'} subtitle={section==='high'?'Monitored units are running normally.':'Choose All or search for a person to inspect other records.'} actionLabel={section==='high'?'Show worth checking':'Show all'} onAction={()=>setSection(section==='high'?'moderate':'all')}/>}
    <div className="page-note"><span>Current queue is ordered by operational concern.</span><span>{section==='all'?`${overview?.personnel_count??0} synthetic personnel are available in the demonstration environment.`:'Lower-priority records remain available through All, Personnel, and global search.'}</span></div>
   </>}
  </PageChrome>
 </AppShell>
}
