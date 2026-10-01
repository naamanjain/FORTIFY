import { useEffect, useMemo, useState } from 'react'
import { PageChrome } from '../components/PageChrome'
import { AppShell } from '../components/AppShell'
import { ErrorState, LoadingSkeleton } from '../components/StatePanels'
import { StatusBadge } from '../components/StatusBadge'
import { TrendIndicator, type Trend } from '../components/TrendIndicator'
import { Icon } from '../components/Icon'
import { ApiError, getPersonDetail, transitionWorkflow, recordWorkflowFeedback, scheduleWorkflowFollowUp, completeWorkflowFollowUp } from '../services/api'
import type { PersonDetail } from '../types/dashboard'
import type { WorkflowItem, WorkflowState } from '../types/workflow'
import { FORTIFY_ROLE } from '../services/api'
import { Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'

const nav=[
 {id:'attention',label:'Attention',path:'/attention',icon:'alert' as const},{id:'personnel',label:'Personnel',path:'/personnel',icon:'person' as const},{id:'followups',label:'Follow-ups',path:'/follow-ups',icon:'calendar' as const},
 {id:'units',label:'Units',path:'/units',icon:'units' as const},{id:'trends',label:'Trends',path:'/trends',icon:'trend' as const},
 {id:'data',label:'Data & Signals',path:'/data/signals',icon:'data' as const},{id:'reviews',label:'Reviews',path:'/reviews',icon:'review' as const},{id:'governance',label:'Governance',path:'/governance',icon:'audit' as const}
]
function push(p:string){history.pushState({},'',p);dispatchEvent(new PopStateEvent('popstate'))}
function bandLabel(b:string){return b==='HIGH'?'Needs attention':b==='MODERATE'?'Worth checking':'No current concern'}
function statusLabel(s:WorkflowState){return ({NEW:'New',ACKNOWLEDGED:'Acknowledged',IN_REVIEW:'Being reviewed',SUPPORT_PLANNED:'Support planned',SUPPORT_COMPLETED:'Support completed',COMPLETED:'Support completed',FOLLOW_UP_SCHEDULED:'Follow-up scheduled',FOLLOW_UP_DUE:'Follow-up due',FOLLOW_UP_COMPLETED:'Follow-up completed',CLOSED:'Closed',DEFERRED:'Deferred',DISMISSED:'Dismissed'})[s] ?? s.replaceAll('_',' ')}

/**
 * Trend comes from the backend, which computes it from the same person-day
 * stream the attention queue uses. Recomputing it here from the last two
 * history points produced a second, contradictory definition of the same word
 * (the backend also promotes to RISING when the band becomes HIGH), so the
 * profile could say "no major change" while the attention table said "getting
 * worse". The backend value is authoritative; when it is absent we show
 * unknown rather than inventing a neutral verdict.
 */
function trendFor(detail: PersonDetail): Trend | null {
  const fromWorkflow = (detail.workflow as WorkflowItem | null | undefined)?.trend
  if (fromWorkflow === 'RISING' || fromWorkflow === 'IMPROVING' || fromWorkflow === 'STABLE') return fromWorkflow
  return null
}

function formatDateTime(value:string|null|undefined){if(!value)return '—';const d=new Date(value);return Number.isNaN(d.getTime())?value:d.toLocaleString([], {day:'2-digit',month:'short',year:'numeric',hour:'2-digit',minute:'2-digit',hour12:true})}
const TRANSITION_LABELS:Record<WorkflowState,Array<[WorkflowState,string,string]>>={
 NEW:[['ACKNOWLEDGED','Acknowledge','ACKNOWLEDGE_REVIEW'],['DISMISSED','Dismiss','DISMISS_REVIEW']],
 ACKNOWLEDGED:[['IN_REVIEW','Start review','START_REVIEW'],['DEFERRED','Defer','DEFER_REVIEW'],['DISMISSED','Dismiss','DISMISS_REVIEW']],
 IN_REVIEW:[['SUPPORT_PLANNED','Plan support','PLAN_SUPPORT'],['DEFERRED','Defer','DEFER_REVIEW'],['DISMISSED','Dismiss','DISMISS_REVIEW']],
 SUPPORT_PLANNED:[['SUPPORT_COMPLETED','Mark support completed','SUPPORT_COMPLETED_BY_HUMAN'],['DEFERRED','Defer','DEFER_REVIEW']],
 SUPPORT_COMPLETED:[['FOLLOW_UP_SCHEDULED','Schedule follow-up','FOLLOW_UP_SCHEDULED'],['CLOSED','Close case','CASE_CLOSED'],['SUPPORT_PLANNED','Plan further support','FURTHER_SUPPORT_REQUIRED']],
 FOLLOW_UP_SCHEDULED:[], FOLLOW_UP_DUE:[], FOLLOW_UP_COMPLETED:[['CLOSED','Close case','CASE_CLOSED'],['SUPPORT_PLANNED','Plan further support','FURTHER_SUPPORT_REQUIRED']],
 DEFERRED:[['ACKNOWLEDGED','Reopen review','REOPEN_REVIEW'],['IN_REVIEW','Resume review','RESUME_REVIEW'],['DISMISSED','Dismiss','DISMISS_REVIEW']], CLOSED:[], DISMISSED:[], COMPLETED:[]
}
function nextTransitions(state:WorkflowState):Array<[WorkflowState,string,string]>{return TRANSITION_LABELS[state] ?? []}
function supportState(state:WorkflowState|undefined){return state==='SUPPORT_COMPLETED'||state==='COMPLETED'||state==='FOLLOW_UP_SCHEDULED'||state==='FOLLOW_UP_DUE'||state==='FOLLOW_UP_COMPLETED'||state==='CLOSED'}
export default function PersonProfile({personId}:{personId:string}){
 const [detail,setDetail]=useState<PersonDetail|null>(null),[workflow,setWorkflow]=useState<WorkflowItem|null>(null),[loading,setLoading]=useState(true),[loadError,setLoadError]=useState<string|null>(null),[actionError,setActionError]=useState<string|null>(null),[busy,setBusy]=useState(false),[notificationsOpen,setNotificationsOpen]=useState(false),[helpfulness,setHelpfulness]=useState(3),[comment,setComment]=useState(''),[followUpRequested,setFollowUpRequested]=useState(false),[scheduleValue,setScheduleValue]=useState('')
 const load=async()=>{setLoading(true);setLoadError(null);setActionError(null);try{const d=await getPersonDetail(personId);setDetail(d);if(d.workflow?.workflow_item_id)setWorkflow(d.workflow as WorkflowItem);else setWorkflow(null)}catch(e){setLoadError(e instanceof Error?e.message:'Personnel record could not be loaded.')}finally{setLoading(false)}}
 useEffect(()=>{void load()},[personId])
 const trendValue=useMemo(()=>detail?trendFor(detail):null,[detail])

 // Load failures and action failures are different situations. A load failure
 // means there is no page to show. An action failure means the page is fine
 // and the user needs to retry the action, so tearing the whole profile down
 // with a "couldn't load this view" panel was the wrong response.
 const reportActionError=(message:string)=>setActionError(message)

 const doTransition=async(next:WorkflowState,reason:string)=>{
   if(!workflow)return
   setBusy(true);setActionError(null)
   try{
     const updated=await transitionWorkflow(workflow.workflow_item_id,next,reason,workflow.workflow_state)
     setWorkflow(updated)
     setDetail(await getPersonDetail(personId))
   }catch(e){
     // A stale-state rejection means the case moved on underneath this screen;
     // reloading gives the user the current truth instead of a dead end.
     if(e instanceof ApiError && /changed since it was loaded/i.test(e.message)){
       reportActionError('Someone else updated this case while you were viewing it. The view has been refreshed with the current state.')
       try{setWorkflow(await getPersonDetail(personId).then(d=>d.workflow as WorkflowItem|null))}catch{/* keep what we have */}
     } else {
       reportActionError(e instanceof Error?e.message:'Workflow action could not be recorded.')
     }
   }finally{setBusy(false)}
 }
 const saveFeedback=async()=>{
   if(!workflow||!workflow.support_event)return
   setBusy(true);setActionError(null)
   try{
     // The idempotency key is stable per case+score so a double-click records
     // one entry instead of corrupting the outcome record.
     const updated=await recordWorkflowFeedback(workflow.workflow_item_id,helpfulness,comment,followUpRequested,`${workflow.workflow_item_id}-feedback-${helpfulness}`)
     setWorkflow(updated)
   }catch(e){reportActionError(e instanceof Error?e.message:'Feedback could not be recorded.')}finally{setBusy(false)}
 }
 const schedule=async()=>{
   if(!workflow||!scheduleValue)return
   setBusy(true);setActionError(null)
   try{
     const updated=await scheduleWorkflowFollowUp(workflow.workflow_item_id,new Date(scheduleValue).toISOString())
     setWorkflow(updated)
     setDetail(await getPersonDetail(personId))
     setScheduleValue('')
   }catch(e){reportActionError(e instanceof Error?e.message:'Follow-up could not be scheduled.')}finally{setBusy(false)}
 }
 const completeFollowup=async()=>{
   if(!workflow?.followup)return
   setBusy(true);setActionError(null)
   try{
     const updated=await completeWorkflowFollowUp(workflow.followup.followup_id)
     setWorkflow(updated)
     setDetail(await getPersonDetail(personId))
   }catch(e){reportActionError(e instanceof Error?e.message:'Follow-up could not be completed.')}finally{setBusy(false)}
 }
 if(loading)return <AppShell navItems={nav} activePath="/person" query="" searchResults={[]} searchOpen={false} onQueryChange={()=>{}} onSearchSelect={()=>{}} onNavigate={push} notificationsOpen={notificationsOpen} onToggleNotifications={()=>setNotificationsOpen(v=>!v)}><LoadingSkeleton/></AppShell>
 if(loadError||!detail)return <AppShell navItems={nav} activePath="/person" query="" searchResults={[]} searchOpen={false} onQueryChange={()=>{}} onSearchSelect={()=>{}} onNavigate={push} notificationsOpen={notificationsOpen} onToggleNotifications={()=>setNotificationsOpen(v=>!v)}><ErrorState message={loadError??'Personnel record not found.'} onRetry={()=>void load()}/></AppShell>
 const latest=detail.latest
 const explanation=detail.explanation
 // No workflow record means no case has been opened for this person yet.
 // Pretending the state is NEW made Acknowledge/Dismiss buttons look live
 // while every click did nothing. Saying "not opened" and hiding the buttons
 // is the truthful rendering.
 const hasWorkflow=workflow!==null
 const state:WorkflowState=workflow?.workflow_state??'NEW'
 const displayState:WorkflowState=workflow?.followup?.status==='DUE'?'FOLLOW_UP_DUE':state
 const actions=hasWorkflow?nextTransitions(state):[]
 const activeSupport=supportState(state)
 return <AppShell navItems={nav} activePath="/person" query="" searchResults={[]} searchOpen={false} onQueryChange={()=>{}} onSearchSelect={()=>{}} onNavigate={push} notificationsOpen={notificationsOpen} onToggleNotifications={()=>setNotificationsOpen(v=>!v)}>
  <PageChrome eyebrow="PERSONNEL / PROFILE" title={detail.person_id} subtitle={`Unit ${detail.unit_id??'—'} · ${detail.role??'Operational context'}`} right={<button className="back-button" type="button" onClick={()=>push('/attention')}>← Attention</button>}>
   {actionError&&<div className="action-error" role="alert">{actionError}</div>}
   <div className="profile-status-strip"><StatusBadge label={bandLabel(latest.risk_band)} tone={latest.risk_band==='HIGH'?'high':latest.risk_band==='MODERATE'?'moderate':'low'}/><TrendIndicator trend={trendValue}/><span className="status-text">Current concern · {bandLabel(latest.risk_band)}</span><span className="status-text">Support status · {hasWorkflow?statusLabel(displayState):'No case opened yet'}</span>{workflow?.requires_human_review&&!['CLOSED','DISMISSED'].includes(state)?<span className="review-required"><Icon name="lock" size={13}/> Human review required</span>:null}</div>
   <section className="profile-grid two">
    <div className="panel"><div className="panel-title">What changed</div><div className="change-list"><div><b>Welfare signal trend</b><span>{trendValue==='RISING'?'↑ Higher than recent days':trendValue==='IMPROVING'?'↓ Lower than recent days':trendValue==='STABLE'?'→ Similar to recent days':'Trend unavailable for this case'}</span></div><div><b>Recovery opportunity</b><span>{latest.feasibility_status==='CONSTRAINED'?'↓ Constrained by current duties':latest.feasibility_status==='NOT_FEASIBLE'?'↓ Not schedulable in current duties':latest.feasibility_status==='FEASIBLE_WITH_ADJUSTMENT'?'→ Scheduling possible with adjustment':'→ Scheduling possible'}</span></div><div><b>Human review</b><span>{latest.requires_human_review?'Required before support action':'Not required for this day'}</span></div></div></div>
    <div className="panel"><div className="panel-title">Usual pattern</div><p className="panel-copy">This view compares the current operational pattern with the person's own recent history. It does not interpret missing voluntary reporting as a concern.</p><div className="mini-metrics"><span><b>{Math.round(latest.risk_probability*100)}%</b><small>model output · not a medical probability</small></span><span><b>{detail.date_range[1]}</b><small>latest available day</small></span></div></div>
   </section>
   <section className="panel"><div className="panel-title">Recent trend</div><div className="trend-chart"><ResponsiveContainer width="100%" height={220}><LineChart data={detail.history}><XAxis dataKey="date" hide/><YAxis domain={[0,1]} tickFormatter={(v)=>`${Math.round(Number(v)*100)}%`} width={42}/><Tooltip formatter={(value)=>[`${Math.round(Number(value)*100)}%`,'Signal']} labelFormatter={(v)=>String(v)}/><Line type="monotone" dataKey="risk_probability" dot={false} stroke="var(--navy)" strokeWidth={2}/></LineChart></ResponsiveContainer></div></section>
   <section className="profile-grid two">
    <div className="panel"><div className="panel-title">Why FORTIFY brought this up</div>
      {explanation?.factors?.length
        ? <ul className="factor-list">{explanation.factors.map((f:any)=><li key={f.factor_id}><strong>{f.signal}</strong><span>{f.value_display} · {f.window} · compared with {f.comparison}</span>{f.change_display&&<small>Change: {f.change_display}</small>}<small>{f.rule}</small></li>)}</ul>
        : <p className="panel-copy">No adverse operational change above the reporting threshold was recorded for this date. The signal may reflect factors not present in the operational data.</p>}
      {latest.contributing_operational_signals&&!explanation?.factors?.length&&<p className="panel-copy">{latest.contributing_operational_signals}</p>}
      <details className="technical"><summary>How FORTIFY reached this</summary>
        <p>Each factor above is measured from generated duty, recovery, leave, deployment, training and incident records: the value shown, the reference it is compared against, the window it covers, and the rule that admitted it. Factors are included only when the measured change is adverse and exceeds a stated deviation threshold.</p>
        <p>These are operational associations, not a clinical or psychological interpretation, and not a diagnosis.</p>
      </details>
    </div>
    <div className="panel support-panel"><div className="panel-title">Suggested next step</div><h2>{latest.recommended_action.replaceAll('_',' ')}</h2><p>{latest.adjustment_recommendation || 'Review the suggested support with the current operational context.'}</p><div className="feasibility-block"><span>Can support be scheduled now?</span><strong>{latest.feasibility_status==='FEASIBLE'?'Can be scheduled':latest.feasibility_status==='FEASIBLE_WITH_ADJUSTMENT'?'Can be scheduled with adjustment':latest.feasibility_status==='CONSTRAINED'?'Constrained by current duties':'Not schedulable now'}</strong><small>{latest.constraint_flags || 'No additional constraint recorded.'}</small></div></div>
   </section>
   {activeSupport&&hasWorkflow?<section className="panel lifecycle-panel"><div className="panel-heading"><div><div className="panel-title">Support status</div><h2>{statusLabel(displayState)}</h2></div><span className="audit-inline"><Icon name="lock" size={14}/> Access logged</span></div>
      {workflow?.support_event&&<div className="support-event"><strong>Support provided</strong><span>{formatDateTime(workflow.support_event.completed_at)}</span><small>Recorded by {workflow.support_event.actor_role==='WELFARE_OFFICER'?'Welfare Officer':workflow.support_event.actor_role}</small></div>}
      {workflow?.feedback?<div className="feedback-readonly"><div className="panel-title">Personnel feedback</div><p>{'★'.repeat(workflow.feedback.helpfulness)}{'☆'.repeat(5-workflow.feedback.helpfulness)} · {['','Not helpful','Slightly helpful','Helpful','Very helpful','Extremely helpful'][workflow.feedback.helpfulness]}</p><small>Submitted {formatDateTime(workflow.feedback.submitted_at)}</small>{workflow.feedback.comment&&<small>{workflow.feedback.comment}</small>}{workflow.feedback.follow_up_requested&&<small>Follow-up requested</small>}</div>:workflow?.support_event&&!workflow?.feedback?<div className="feedback-form"><div className="panel-title">Personnel feedback <small>Voluntary</small></div><label>How helpful was the support you received?<select value={helpfulness} onChange={e=>setHelpfulness(Number(e.target.value))}><option value={1}>1 — Not helpful</option><option value={2}>2 — Slightly helpful</option><option value={3}>3 — Helpful</option><option value={4}>4 — Very helpful</option><option value={5}>5 — Extremely helpful</option></select></label><label><span>Optional comment</span><textarea value={comment} onChange={e=>setComment(e.target.value)} maxLength={1000} placeholder="No comment required" /></label><label className="check-row"><input type="checkbox" checked={followUpRequested} onChange={e=>setFollowUpRequested(e.target.checked)}/> Follow-up requested</label><button className="button primary" type="button" disabled={busy} onClick={()=>void saveFeedback()}>{busy?'Saving…':'Record voluntary feedback'}</button></div>:null}
      {state==='SUPPORT_COMPLETED'&&<div className="followup-plan"><div className="panel-title">Next step</div><p>Schedule a follow-up after support to keep the case connected to human care.</p><div className="followup-schedule-form"><input type="datetime-local" value={scheduleValue} onChange={e=>setScheduleValue(e.target.value)} aria-label="Follow-up date and time"/><button className="button primary" type="button" disabled={busy||!scheduleValue} onClick={()=>void schedule()}>Schedule follow-up</button></div></div>}
      {workflow?.followup&&<div className="followup-current"><div><div className="panel-title">Follow-up</div><strong>{workflow.followup.status==='COMPLETED'?'Follow-up completed':workflow.followup.status==='DUE'?'Follow-up due':'Follow-up scheduled'}</strong><span>{formatDateTime(workflow.followup.scheduled_for)}</span></div>{workflow.followup.status!=='COMPLETED'&&<button className="button primary" type="button" disabled={busy} onClick={()=>void completeFollowup()}>Complete follow-up</button>}</div>}
   </section>:null}
   <section className="panel workflow-panel"><div className="panel-heading"><div><div className="panel-title">Human review</div><h2>{hasWorkflow?statusLabel(state):'No case opened'}</h2></div><span className="audit-inline"><Icon name="lock" size={14}/> Access logged</span></div>
    {!hasWorkflow&&<p className="panel-copy">No welfare case has been opened for this person yet. Cases are opened from the attention queue when a signal is reviewed.</p>}
    <div className="workflow-actions">{busy?<span className="muted">Saving workflow action…</span>:actions.map(([next,label,reason])=><button key={`${next}-${label}`} className={`button ${next==='DISMISSED'?'secondary':'primary'}`} type="button" onClick={()=>void doTransition(next,reason)}>{label}</button>)}{hasWorkflow&&actions.length===0?<span className="muted">No human transition is available from this state.</span>:null}</div>{workflow?.history?.length?<div className="audit-history">{workflow.history.map(event=><div key={event.event_id}><span>{formatDateTime(event.timestamp)}</span><strong>{statusLabel(event.new_state)}</strong><small>{event.actor_role==='WELFARE_OFFICER'?'Welfare Officer':event.actor_role} · {event.reason_code}</small></div>)}</div>:<div className="empty-history">No human actions have been recorded yet.</div>}</section>
   <div className="privacy-note">{FORTIFY_ROLE} · Configured access context (not authenticated) · Operational welfare information only · No raw wellness responses are shown.</div>
  </PageChrome>
 </AppShell>
}