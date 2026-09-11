import { useEffect, useState } from 'react'
import { AppShell } from '../components/AppShell'
import { PageChrome } from '../components/PageChrome'
import { ErrorState, LoadingSkeleton } from '../components/StatePanels'
import { StatusBadge } from '../components/StatusBadge'
import { Icon } from '../components/Icon'
import { getUnitDetail, getUnitSummary } from '../services/api'
import type { UnitSummary } from '../types/dashboard'
import { ResponsiveContainer, LineChart, Line, XAxis, YAxis, Tooltip } from 'recharts'
const nav=[{id:'attention',label:'Attention',path:'/attention',icon:'alert' as const},{id:'personnel',label:'Personnel',path:'/personnel',icon:'person' as const},{id:'units',label:'Units',path:'/units',icon:'units' as const},{id:'trends',label:'Trends',path:'/trends',icon:'trend' as const},{id:'data',label:'Data & Signals',path:'/data/signals',icon:'data' as const},{id:'reviews',label:'Reviews',path:'/reviews',icon:'review' as const},{id:'governance',label:'Governance',path:'/governance',icon:'audit' as const}]
function push(p:string){history.pushState({},'',p);dispatchEvent(new PopStateEvent('popstate'))}
export default function UnitCommand({unitId}:{unitId?:string}){
 const [units,setUnits]=useState<UnitSummary[]>([]),[detail,setDetail]=useState<any>(null),[selected,setSelected]=useState(unitId||''),[loading,setLoading]=useState(true),[error,setError]=useState<string|null>(null),[notificationsOpen,setNotificationsOpen]=useState(false)
 useEffect(()=>{void (async()=>{setLoading(true);setError(null);try{const s=await getUnitSummary('AGGREGATE_OPERATIONS');setUnits(s.units);const target=unitId||s.units[0]?.unit_id;if(target){setSelected(target);setDetail(await getUnitDetail(target,'AGGREGATE_OPERATIONS'))}}catch(e){setError(e instanceof Error?e.message:'Unit view could not be loaded.')}finally{setLoading(false)}})()},[unitId])
 if(loading)return <AppShell navItems={nav} activePath="/units" query="" searchResults={[]} searchOpen={false} onQueryChange={()=>{}} onSearchSelect={()=>{}} onNavigate={push} notificationsOpen={notificationsOpen} onToggleNotifications={()=>setNotificationsOpen(v=>!v)}><LoadingSkeleton/></AppShell>
 if(error||!detail)return <AppShell navItems={nav} activePath="/units" query="" searchResults={[]} searchOpen={false} onQueryChange={()=>{}} onSearchSelect={()=>{}} onNavigate={push} notificationsOpen={notificationsOpen} onToggleNotifications={()=>setNotificationsOpen(v=>!v)}><ErrorState message={error??'No unit data available.'}/></AppShell>
 const current=units.find(x=>x.unit_id===selected)
 const highShare=current?Math.round(current.high_risk/current.personnel*100):0
 return <AppShell navItems={nav} activePath="/units" query="" searchResults={[]} searchOpen={false} onQueryChange={()=>{}} onSearchSelect={()=>{}} onNavigate={push} notificationsOpen={notificationsOpen} onToggleNotifications={()=>setNotificationsOpen(v=>!v)}>
  <PageChrome eyebrow="UNITS / COMMAND VIEW" title={`Unit ${selected} Overview`} subtitle="Aggregate operational context · no individual welfare data shown" right={<div className="restriction-banner"><Icon name="lock" size={15}/> Aggregate view</div>}>
   <div className="unit-picker"><span>Unit</span><select value={selected} onChange={(e)=>{setSelected(e.target.value);push(`/units/${e.target.value}`)}}>{units.map(u=><option key={u.unit_id} value={u.unit_id}>{u.unit_id}</option>)}</select></div>
   <section className="metric-strip"><div><span>PERSONNEL</span><strong>{current?.personnel??detail.personnel}</strong></div><div><span>NEEDS ATTENTION</span><strong>{detail.high_count}</strong></div><div><span>SCHEDULING CONSTRAINTS</span><strong>{detail.constrained_count}</strong></div><div><span>ATTENTION CONCENTRATION</span><strong>{highShare}%</strong></div></section>
   <section className="panel"><div className="panel-heading"><div><div className="panel-title">Unit welfare trends</div><h2>Is operational pressure changing?</h2></div><span className="muted">Last 30 available days</span></div><div className="trend-chart"><ResponsiveContainer width="100%" height={250}><LineChart data={detail.trend}><XAxis dataKey="date" tickFormatter={(v)=>String(v).slice(5)} minTickGap={24}/><YAxis yAxisId="left" width={34} domain={[0,1]} tickFormatter={(v)=>`${Math.round(Number(v)*100)}%`}/><YAxis yAxisId="right" orientation="right" width={34}/><Tooltip/><Line yAxisId="left" type="monotone" dataKey="average_probability" stroke="var(--navy)" strokeWidth={2} dot={false} name="Average signal"/><Line yAxisId="right" type="monotone" dataKey="high_count" stroke="var(--danger)" strokeWidth={1.5} dot={false} name="Needs attention"/></LineChart></ResponsiveContainer></div></section>
   <section className="panel"><div className="panel-title">Aggregate unit context</div><div className="unit-list">{units.slice(0,6).map(u=><button key={u.unit_id} type="button" className="unit-row" onClick={()=>push(`/units/${u.unit_id}`)}><span><strong>{u.unit_id}</strong><small>{u.personnel} personnel · {u.high_risk} need attention</small></span><span className="unit-bar"><i style={{width:`${Math.min(100, Math.round((u.high_risk/Math.max(1,u.personnel))*100))}%`}}/></span><span>{u.high_risk>0?<StatusBadge label="Attention" tone="high"/>:<StatusBadge label="Stable" tone="low"/>}</span></button>)}</div></section>
   <div className="privacy-note">Leadership view is aggregate-first. Individual personnel identifiers are not exposed on this screen.</div>
  </PageChrome>
 </AppShell>
}
