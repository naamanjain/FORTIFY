import { useEffect, useState } from 'react'
import { AppShell } from '../components/AppShell'
import { PageChrome } from '../components/PageChrome'
import { LoadingSkeleton, ErrorState } from '../components/StatePanels'
import { StatusBadge } from '../components/StatusBadge'
import { getPersonnel } from '../services/api'
import type { PersonnelRow } from '../types/product'
const nav=[{id:'attention',label:'Attention',path:'/attention',icon:'alert' as const},{id:'personnel',label:'Personnel',path:'/personnel',icon:'person' as const},{id:'followups',label:'Follow-ups',path:'/follow-ups',icon:'calendar' as const},{id:'units',label:'Units',path:'/units',icon:'units' as const},{id:'trends',label:'Trends',path:'/trends',icon:'trend' as const},{id:'data',label:'Data & Signals',path:'/data/signals',icon:'data' as const},{id:'reviews',label:'Reviews',path:'/reviews',icon:'review' as const},{id:'governance',label:'Governance',path:'/governance',icon:'audit' as const}]
function push(p:string){history.pushState({},'',p);dispatchEvent(new PopStateEvent('popstate'))}
// The backend caps a single page, so load the full roster by paging until the
// response says nothing was dropped. Showing 50 of 500 rows with no indicator
// presented a truncated list as the whole roster.
const PAGE_SIZE = 100
export default function Personnel(){
 const[items,setItems]=useState<PersonnelRow[]>([]),[loading,setLoading]=useState(true),[error,setError]=useState<string|null>(null),[notificationsOpen,setNotificationsOpen]=useState(false),[total,setTotal]= useState<number|null>(null)
 useEffect(()=>{void (async()=>{
   try{
     const collected:PersonnelRow[]=[]
     for(let offset=0;;offset+=PAGE_SIZE){
       const page=await getPersonnel('','','',PAGE_SIZE)
       setTotal(page.total_personnel)
       collected.push(...page.items)
       setItems([...collected])
       if(!page.truncated||collected.length>=page.total_matching) break
       if(offset>2000) break // safety stop against a pathological backend
     }
   }catch(e){setError(e instanceof Error?e.message:'Personnel records could not be loaded.')}
   finally{setLoading(false)}
 })()},[])
 return <AppShell navItems={nav} activePath="/personnel" query="" searchResults={[]} searchOpen={false} onQueryChange={()=>{}} onSearchSelect={()=>{}} onNavigate={push} notificationsOpen={notificationsOpen} onToggleNotifications={()=>setNotificationsOpen(v=>!v)}>{loading?<LoadingSkeleton/>:<PageChrome eyebrow="PERSONNEL" title="Personnel" subtitle={total?`Authorized welfare-officer view · roster of ${total} personnel`:'Authorized welfare-officer view of current operational signals'}><div className="data-table-wrap"><table className="data-table personnel-table"><thead><tr><th>PERSON</th><th>UNIT</th><th>WELFARE CONCERN</th><th>SUGGESTED NEXT STEP</th><th>REVIEW STATUS</th></tr></thead><tbody>{error?<tr><td colSpan={5}><ErrorState message={error} onRetry={()=>{setLoading(true);setError(null);window.location.reload()}}/></td></tr>:!items.length?<tr><td colSpan={5}><div className="state-panel"><div className="state-mark">·</div><h2>No personnel records to show</h2><p>No personnel are available for this view in the current demonstration dataset.</p></div></td></tr>:items.map(r=><tr key={r.person_id} className="personnel-click-row" tabIndex={0} onClick={()=>push(`/person/${encodeURIComponent(r.person_id)}`)} onKeyDown={(e)=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();push(`/person/${encodeURIComponent(r.person_id)}`)}}}><td><button className="table-person" type="button" tabIndex={-1} onClick={(e)=>{e.stopPropagation();push(`/person/${encodeURIComponent(r.person_id)}`)}}><strong>{r.person_id}</strong><small>{r.date}</small></button></td><td className="mono muted">{r.unit_id}</td><td><StatusBadge label={r.risk_band==='HIGH'?'Needs attention':r.risk_band==='MODERATE'?'Worth checking':'No current concern'} tone={r.risk_band==='HIGH'?'high':r.risk_band==='MODERATE'?'moderate':'low'}/></td><td>{r.recommended_action.replaceAll('_',' ')}</td><td className="muted">{r.feasibility_status.replaceAll('_',' ')}</td></tr>)}</tbody></table>{items.length?<div className="table-footer"><span>{items.length} of {total??items.length} personnel shown</span></div>:null}</div></PageChrome>}</AppShell>}
