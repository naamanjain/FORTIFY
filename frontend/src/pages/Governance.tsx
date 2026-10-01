import { useEffect, useState } from 'react'
import { AppShell } from '../components/AppShell'
import { PageChrome } from '../components/PageChrome'
import { LoadingSkeleton, ErrorState } from '../components/StatePanels'
import { StatusBadge } from '../components/StatusBadge'
import { Icon } from '../components/Icon'
import { getAuditView, getSystemHealth } from '../services/api'
import type { AuditView } from '../types/product'
const nav=[{id:'attention',label:'Attention',path:'/attention',icon:'alert' as const},{id:'personnel',label:'Personnel',path:'/personnel',icon:'person' as const},{id:'followups',label:'Follow-ups',path:'/follow-ups',icon:'calendar' as const},{id:'units',label:'Units',path:'/units',icon:'units' as const},{id:'trends',label:'Trends',path:'/trends',icon:'trend' as const},{id:'data',label:'Data & Signals',path:'/data/signals',icon:'data' as const},{id:'reviews',label:'Reviews',path:'/reviews',icon:'review' as const},{id:'governance',label:'Governance',path:'/governance',icon:'audit' as const}]
function push(p:string){history.pushState({},'',p);dispatchEvent(new PopStateEvent('popstate'))}
export default function Governance(){
 const [audit,setAudit]=useState<AuditView|null>(null),[health,setHealth]=useState<any>(null),[loading,setLoading]=useState(true),[error,setError]=useState<string|null>(null),[notificationsOpen,setNotificationsOpen]=useState(false)
 useEffect(()=>{void (async()=>{setLoading(true);const [a,h]=await Promise.allSettled([getAuditView(),getSystemHealth()]);if(a.status==='fulfilled')setAudit(a.value);if(h.status==='fulfilled')setHealth(h.value);if(a.status==='rejected'&&h.status==='rejected'){setError(a.reason instanceof Error?a.reason.message:'Access restricted: governance information requires the authorized audit or administration workspace.')}else if(a.status==='rejected'){setError('Audit view requires the auditor workspace; system health may still be shown when available.')}setLoading(false)})()},[])
 return <AppShell navItems={nav} activePath="/governance" query="" searchResults={[]} searchOpen={false} onQueryChange={()=>{}} onSearchSelect={()=>{}} onNavigate={push} notificationsOpen={notificationsOpen} onToggleNotifications={()=>setNotificationsOpen(v=>!v)}>
  {loading?<LoadingSkeleton/>:(error&&!audit)?<div className="restricted-panel"><Icon name="lock" size={24}/><h2>Access restricted</h2><p>The current Welfare Officer workspace does not have governance/audit authorization. Switch to an authorized security or administration workspace to view this information.</p></div>:<PageChrome eyebrow="GOVERNANCE" title="Governance & Security Audit" subtitle="System oversight, access controls, and audit integrity">
   <div className="governance-grid"><div className="panel"><div className="panel-title">System integrity</div><div className="integrity-box"><div><strong>Audit chain</strong><StatusBadge label={audit?.chain_valid?'Verified':'Failed'} tone={audit?.chain_valid?'ok':'danger'}/></div><small>{audit?.event_count??0} events in current view{typeof audit?.audit_records==='number'?` · ${audit.audit_records} total in log`:''}</small>{audit?.chain_reason&&<small>{audit.chain_reason}</small>}</div><div className="health-lines">{health
      ? <span>Access controls <b>{health.governance?.access_control??'Unavailable'}</b></span>
      // When the health endpoint is not reachable with this workspace's
      // authorization, say so. Substituting plausible-looking text presented
      // fabricated state as live system posture.
      : <span>Access controls <b>Unavailable in this workspace</b></span>}
      {health&&<span>Security boundary <b>{health.governance?.security_boundary??'Unavailable'}</b></span>}
      {!health&&<span>Security boundary <b>Unavailable in this workspace</b></span>}
      <span>Audit chain <b>{audit?(audit.chain_valid?'Healthy':'Failed'):'Unavailable in this workspace'}</b></span>
      {health?.governance?.authenticated===false&&<span>Authentication <b>None (header-trust prototype)</b></span>}
    </div></div><div className="panel"><div className="panel-title">Role-based access</div><small className="panel-note">Documented prototype policy - the authoritative matrix lives in the backend security configuration.</small><div className="role-list"><div><Icon name="person" size={18}/><span><strong>Welfare Officers</strong><small>Individual welfare review</small></span><b>Restricted</b></div><div><Icon name="units" size={18}/><span><strong>Command Leadership</strong><small>Aggregate operations</small></span><b>Aggregate</b></div><div><Icon name="audit" size={18}/><span><strong>Auditors / Administrators</strong><small>Governance and system health</small></span><b>Governance</b></div></div></div></div>
   <section className="panel audit-panel"><div className="panel-heading"><div><div className="panel-title">Immutable audit log</div><h2>Recent governance events</h2></div><span className="muted">Showing {audit?.events.length??0}</span></div><div className="audit-table-wrap"><table className="audit-table"><thead><tr><th>UTC</th><th>ROLE</th><th>ACTION</th><th>PURPOSE</th><th>STATUS</th></tr></thead><tbody>{audit?.events.map((e,i)=><tr key={`${e.timestamp}-${i}`}><td>{new Date(e.timestamp).toLocaleString()}</td><td><StatusBadge label={e.actor_role}/></td><td>{e.event_type.replaceAll('_',' ')}</td><td>{e.purpose.replaceAll('_',' ')}</td><td><StatusBadge label={e.outcome} tone={e.outcome==='ALLOWED'?'ok':'danger'}/></td></tr>)}</tbody></table></div></section>
  </PageChrome>}
 </AppShell>
}
