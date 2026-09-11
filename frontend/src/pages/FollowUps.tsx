import { useEffect, useMemo, useState } from 'react'
import { AppShell } from '../components/AppShell'
import { PageChrome } from '../components/PageChrome'
import { ErrorState, EmptyState, LoadingSkeleton } from '../components/StatePanels'
import { StatusBadge } from '../components/StatusBadge'
import { getFollowUps, completeWorkflowFollowUp, scheduleWorkflowFollowUp } from '../services/api'
import type { FollowUpRecord } from '../types/workflow'

const nav=[
 {id:'attention',label:'Attention',path:'/attention',icon:'alert' as const},
 {id:'personnel',label:'Personnel',path:'/personnel',icon:'person' as const},
 {id:'units',label:'Units',path:'/units',icon:'units' as const},
 {id:'trends',label:'Trends',path:'/trends',icon:'trend' as const},
 {id:'data',label:'Data & Signals',path:'/data/signals',icon:'data' as const},
 {id:'reviews',label:'Reviews',path:'/reviews',icon:'review' as const},
 {id:'governance',label:'Governance',path:'/governance',icon:'audit' as const},
]
function push(path:string){history.pushState({},'',path);dispatchEvent(new PopStateEvent('popstate'))}
function formatDateTime(value:string){const d=new Date(value);return Number.isNaN(d.getTime())?value:d.toLocaleString([], {day:'2-digit',month:'short',year:'numeric',hour:'2-digit',minute:'2-digit',hour12:true})}
function actionLabel(action?:string){return action?action.replaceAll('_',' '):'Welfare support'}
export default function FollowUps(){
 const [items,setItems]=useState<FollowUpRecord[]>([]),[loading,setLoading]=useState(true),[error,setError]=useState<string|null>(null),[status,setStatus]=useState<'DUE_TODAY'|'THIS_WEEK'|'OVERDUE'|'UPCOMING'|'COMPLETED'|'ALL'>('DUE_TODAY'),[busy,setBusy]=useState<string|null>(null),[editId,setEditId]=useState<string|null>(null),[editValue,setEditValue]=useState(''),[notificationsOpen,setNotificationsOpen]=useState(false)
 const load=async()=>{setLoading(true);setError(null);try{const r=await getFollowUps();setItems(r.items)}catch(e){setError(e instanceof Error?e.message:'Follow-ups could not be loaded.')}finally{setLoading(false)}}
 useEffect(()=>{void load()},[])
 const visible=useMemo(()=>{const now=new Date();const start=new Date(now);start.setHours(0,0,0,0);const endToday=new Date(start);endToday.setDate(endToday.getDate()+1);const weekEnd=new Date(start);weekEnd.setDate(weekEnd.getDate()+7);return items.filter(x=>{const when=new Date(x.scheduled_for);if(status==='ALL')return true;if(status==='COMPLETED')return x.status==='COMPLETED';if(x.status==='COMPLETED')return false;if(status==='OVERDUE')return when<start;if(status==='DUE_TODAY')return when>=start&&when<endToday;if(status==='THIS_WEEK')return when>=start&&when<weekEnd;return when>=weekEnd})},[items,status])
 const open=(id:string)=>push(`/person/${encodeURIComponent(id)}`)
 const complete=async(id:string)=>{setBusy(id);try{await completeWorkflowFollowUp(id);await load()}catch(e){setError(e instanceof Error?e.message:'Follow-up could not be completed.')}finally{setBusy(null)}}
 const saveSchedule=async(item:FollowUpRecord)=>{if(!editValue)return;setBusy(item.followup_id);try{await scheduleWorkflowFollowUp(item.workflow_item_id,new Date(editValue).toISOString());setEditId(null);setEditValue('');await load()}catch(e){setError(e instanceof Error?e.message:'Follow-up could not be rescheduled.')}finally{setBusy(null)}}
 if(loading)return <AppShell navItems={nav} activePath="/follow-ups" query="" searchResults={[]} searchOpen={false} onQueryChange={()=>{}} onSearchSelect={()=>{}} onNavigate={push} notificationsOpen={notificationsOpen} onToggleNotifications={()=>setNotificationsOpen(v=>!v)}><LoadingSkeleton/></AppShell>
 return <AppShell navItems={nav} activePath="/follow-ups" query="" searchResults={[]} searchOpen={false} onQueryChange={()=>{}} onSearchSelect={()=>{}} onNavigate={push} notificationsOpen={notificationsOpen} onToggleNotifications={()=>setNotificationsOpen(v=>!v)}>
  <PageChrome eyebrow="ATTENTION / FOLLOW-UPS" title="Follow-up schedule" subtitle="Who needs another check-in, when, and why?">
   <div className="followup-filters" role="tablist" aria-label="Follow-up status filter">
    {(['DUE_TODAY','THIS_WEEK','OVERDUE','UPCOMING','COMPLETED','ALL'] as const).map(x=><button key={x} type="button" className={status===x?'filter-chip active':'filter-chip'} onClick={()=>setStatus(x)}>{x==='DUE_TODAY'?'Due today':x==='THIS_WEEK'?'This week':x==='OVERDUE'?'Overdue':x==='UPCOMING'?'Upcoming':x==='COMPLETED'?'Completed':'All'}</button>)}
   </div>
   {error?<ErrorState message={error} onRetry={()=>void load()}/>:visible.length?<div className="data-table-wrap followup-table-wrap"><table className="data-table followup-table"><thead><tr><th>PERSON</th><th>FOLLOW-UP</th><th>LAST SUPPORT</th><th>SUPPORT TYPE</th><th>STATUS</th><th>ACTION</th></tr></thead><tbody>{visible.map(item=>{
    const isBusy=busy===item.followup_id; const isEditing=editId===item.followup_id
    return <tr key={item.followup_id} className="followup-row" onClick={()=>open(item.person_id)} tabIndex={0} onKeyDown={e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();open(item.person_id)}}}>
      <td><button className="table-person" type="button" tabIndex={-1} onClick={e=>{e.stopPropagation();open(item.person_id)}}><strong>{item.person_id}</strong><small>{item.workflow_state?.replaceAll('_',' ') ?? 'Case'}</small></button></td>
      <td><strong>{formatDateTime(item.scheduled_for)}</strong></td>
      <td className="muted">{item.support_completed_at?formatDateTime(item.support_completed_at):'—'}</td>
      <td>{actionLabel(item.support_action || item.recommended_action)}<small className="followup-support-by">{item.support_actor_role==='WELFARE_OFFICER'?'Welfare Officer':item.support_actor_role || 'Authorized welfare role'}</small></td>
      <td><StatusBadge label={item.status==='DUE'?'Follow-up due':item.status==='COMPLETED'?'Follow-up completed':'Follow-up scheduled'} tone={item.status==='DUE'?'moderate':item.status==='COMPLETED'?'low':'neutral'}/></td>
      <td onClick={e=>e.stopPropagation()}><div className="followup-actions">{item.status!=='COMPLETED'&&<button className="button primary compact" type="button" disabled={isBusy} onClick={()=>void complete(item.followup_id)}>{isBusy?'Saving…':'Complete follow-up'}</button>}{item.status!=='COMPLETED'&&<button className="button secondary compact" type="button" disabled={isBusy} onClick={()=>{setEditId(item.followup_id);setEditValue(new Date(item.scheduled_for).toISOString().slice(0,16))}}>Reschedule</button>}{isEditing&&<div className="followup-inline-editor"><input type="datetime-local" value={editValue} onChange={e=>setEditValue(e.target.value)} aria-label="New follow-up date and time"/><button className="button primary compact" type="button" disabled={isBusy} onClick={()=>void saveSchedule(item)}>Save</button></div>}</div></td>
    </tr>
   })}</tbody></table></div>:<EmptyState title={status==='DUE_TODAY'?'No follow-ups are due today.':status==='OVERDUE'?'No overdue follow-ups.':'No follow-ups in this view.'} subtitle="Completed and scheduled support records remain available through filters and person history." actionLabel="Show all" onAction={()=>setStatus('ALL')}/>} 
   <div className="page-note"><span>Demonstration environment · synthetic operational data</span><span>Follow-up records are persisted workflow history, not appointments.</span></div>
  </PageChrome>
 </AppShell>
}
