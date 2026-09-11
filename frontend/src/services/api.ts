export type HealthResponse = { status: string; service: string }

import type { DashboardOverview, PersonDetail, TrendPoint, UnitSummary } from '../types/dashboard'
import type { WorkflowItem, WorkflowState } from '../types/workflow'
import type { AuditRecord, DataSource, PersonnelRow, SearchResult } from '../types/product'
import type { FollowUpRecord } from '../types/workflow'

export const FORTIFY_ROLE = import.meta.env.VITE_FORTIFY_ROLE ?? 'WELFARE_OFFICER'
export const FORTIFY_PURPOSE = import.meta.env.VITE_FORTIFY_PURPOSE ?? 'WELFARE_SUPPORT'

async function request<T>(path: string, init: RequestInit = {}, purpose: string = FORTIFY_PURPOSE): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      'X-Fortify-Role': FORTIFY_ROLE,
      'X-Fortify-Purpose': purpose,
      ...(init.headers ?? {}),
    },
  })

  if (!response.ok) {
    if (response.status === 401 || response.status === 403) {
      throw new Error('Access restricted: this workspace does not have the required authorization.')
    }
    const text = await response.text()
    throw new Error(text || `Backend returned ${response.status}`)
  }

  return response.json() as Promise<T>
}

export const getHealth = () => request<HealthResponse>('/health')
export const getDashboardOverview = () => request<DashboardOverview>('/api/dashboard/overview')
export const getDashboardTrend = (days = 30) =>
  request<{ days: number; points: TrendPoint[] }>(`/api/dashboard/trend?days=${days}`)
export const getUnitSummary = (purpose = 'AGGREGATE_OPERATIONS') =>
  request<{ as_of_date: string; units: UnitSummary[] }>('/api/dashboard/units', {}, purpose)
export const getUnitDetail = (unitId: string, purpose = 'AGGREGATE_OPERATIONS') =>
  request<any>(`/api/dashboard/unit/${encodeURIComponent(unitId)}`, {}, purpose)
export const getPersonDetail = (personId: string) =>
  request<PersonDetail>(`/api/dashboard/person/${encodeURIComponent(personId)}`)
export const getPersonnel = (query = '', unitId = '', riskBand = '') =>
  request<{ items: PersonnelRow[]; count: number; total_personnel: number; privacy_note: string }>(
    `/api/dashboard/personnel?query=${encodeURIComponent(query)}&unit_id=${encodeURIComponent(unitId)}&risk_band=${encodeURIComponent(riskBand)}`,
  )
export const searchDashboard = (query: string) =>
  request<{ query: string; results: SearchResult[]; privacy_note?: string }>(
    `/api/dashboard/search?query=${encodeURIComponent(query)}`,
  )
export const getDataSources = (purpose = 'AGGREGATE_OPERATIONS') =>
  request<{ environment: string; sources: DataSource[]; privacy_note: string }>('/api/dashboard/data-sources', {}, purpose)
export const getAuditView = (purpose = 'AUDIT') =>
  request<{ chain_valid: boolean; event_count: number; events: AuditRecord[]; privacy_note: string }>('/api/dashboard/audit', {}, purpose)
export const getSystemHealth = (purpose = 'INFRASTRUCTURE_ADMIN') =>
  request<any>('/api/dashboard/system-health', {}, purpose)

export const getPendingWorkflow = (limit = 30) =>
  request<{ items: WorkflowItem[]; count: number }>(`/api/workflow/pending?limit=${limit}`)
export const getWorkflowItem = (workflowItemId: string) =>
  request<WorkflowItem>(`/api/workflow/${encodeURIComponent(workflowItemId)}`)
export const transitionWorkflow = (workflowItemId: string, newState: WorkflowState, reasonCode: string) =>
  request<WorkflowItem>(`/api/workflow/${encodeURIComponent(workflowItemId)}/transition`, {
    method: 'POST',
    body: JSON.stringify({ new_state: newState, reason_code: reasonCode }),
  })

export const recordWorkflowFeedback = (
  workflowItemId: string,
  helpfulness: number,
  comment: string | null,
  followUpRequested: boolean,
) =>
  request<WorkflowItem>(`/api/workflow/${encodeURIComponent(workflowItemId)}/feedback`, {
    method: 'POST',
    body: JSON.stringify({
      helpfulness,
      comment,
      follow_up_requested: followUpRequested,
    }),
  })

export const scheduleWorkflowFollowUp = (workflowItemId: string, scheduledFor: string) =>
  request<WorkflowItem>(`/api/workflow/${encodeURIComponent(workflowItemId)}/follow-up`, {
    method: 'POST',
    body: JSON.stringify({ scheduled_for: scheduledFor }),
  })

export const completeWorkflowFollowUp = (followupId: string) =>
  request<WorkflowItem>(`/api/workflow/follow-ups/${encodeURIComponent(followupId)}/complete`, {
    method: 'POST',
  })

export const getFollowUps = (status?: string) =>
  request<{ items: FollowUpRecord[]; count: number }>(
    `/api/workflow/follow-ups?limit=200${status ? `&status=${encodeURIComponent(status)}` : ''}`,
  )
