export type ProductView='attention'|'followups'|'personnel'|'units'|'trends'|'data'|'audit'|'health'
export type SearchResult={type:'PERSONNEL'|'UNIT';key:string;title:string;detail:string}
export type PersonnelRow={person_id:string;unit_id:string;date:string;risk_band:'LOW'|'MODERATE'|'HIGH';risk_probability:number;recommended_action:string;priority:string;feasibility_status:string}
export type DataSource={name:string;status:string;records:number;last_updated?:string;classification:string}
export type AuditRecord={event_type:string;actor_role:string;purpose:string;outcome:string;resource:string;timestamp:string;details:Record<string,unknown>}
