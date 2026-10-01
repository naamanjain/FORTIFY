export type HealthResponse = { status: string; service: string; version?: string }
export type ReadinessResponse = {
  ready: boolean
  version: string
  checks: { database: string; artifacts: string }
  missing_artifacts: string[]
  remedy?: string
}

import type { DashboardOverview, PersonDetail, TrendPoint, UnitSummary } from '../types/dashboard'
import type { FollowUpRecord, WorkflowItem, WorkflowState } from '../types/workflow'
import type { AuditRecord, DataSource, PersonnelRow, SearchResult } from '../types/product'

/**
 * Access context for this deployment.
 *
 * These are build-time configuration values, NOT an authenticated identity.
 * The backend trusts them because the prototype has no identity provider; the
 * `currentAccess` helper below is what the UI shows, and it says so. Do not
 * render these as a signed-in user.
 */
export const FORTIFY_ROLE = import.meta.env.VITE_FORTIFY_ROLE ?? 'WELFARE_OFFICER'
export const FORTIFY_PURPOSE = import.meta.env.VITE_FORTIFY_PURPOSE ?? 'WELFARE_SUPPORT'

export const currentAccess = {
  role: FORTIFY_ROLE,
  defaultPurpose: FORTIFY_PURPOSE,
  authenticated: false,
  label: 'Configured access context (not authenticated)',
}

// Base URL of the FORTIFY backend. Empty = same origin (dev proxy or reverse
// proxy in deployment). Override with VITE_API_BASE_URL when the API lives on
// another host.
const API_BASE = (import.meta.env.VITE_API_BASE_URL ?? '').replace(/\/$/, '')

/**
 * Purpose constants. Each request declares *why* it is asking, which is what
 * purpose limitation means: the backend enforces that the declared purpose
 * matches the sensitivity of the view, rather than trusting one global claim.
 */
export const PURPOSE = {
  WELFARE_SUPPORT: 'WELFARE_SUPPORT',
  AGGREGATE_OPERATIONS: 'AGGREGATE_OPERATIONS',
  AUDIT: 'AUDIT',
  INFRASTRUCTURE_ADMIN: 'INFRASTRUCTURE_ADMIN',
} as const

export class ApiError extends Error {
  readonly status: number
  readonly kind: 'access' | 'data' | 'server' | 'other'

  constructor(message: string, status: number, kind: ApiError['kind']) {
    super(message)
    this.status = status
    this.kind = kind
  }
}

async function request<T>(path: string, init: RequestInit = {}, purpose: string = FORTIFY_PURPOSE): Promise<T> {
  let response: Response
  try {
    response = await fetch(`${API_BASE}${path}`, {
      ...init,
      headers: {
        'Content-Type': 'application/json',
        'X-Fortify-Role': FORTIFY_ROLE,
        'X-Fortify-Purpose': purpose,
        ...(init.headers ?? {}),
      },
    })
  } catch {
    // A transport failure is not "no results". Say so, rather than letting the
    // caller render an empty screen that looks like an answer.
    throw new ApiError(
      'Could not reach the FORTIFY backend. Check that the API is running.',
      0,
      'server',
    )
  }

  if (!response.ok) {
    if (response.status === 401 || response.status === 403) {
      throw new ApiError(
        'Access restricted: this workspace does not have the required authorization.',
        response.status,
        'access',
      )
    }
    if (response.status === 503) {
      throw new ApiError(
        'The demonstration dataset is not available on the backend. Generate it with: python scripts/build_all.py',
        503,
        'data',
      )
    }
    if (response.status === 429) {
      throw new ApiError('Too many requests. Please wait a moment and try again.', 429, 'server')
    }
    let detail = ''
    try {
      const body = await response.json()
      detail = typeof body?.detail === 'string' ? body.detail : ''
    } catch {
      detail = ''
    }
    throw new ApiError(detail || `Backend returned ${response.status}`, response.status, 'other')
  }

  return response.json() as Promise<T>
}

export const getHealth = () => request<HealthResponse>('/health')
export const getReadiness = () => request<ReadinessResponse>('/ready')

export const getDashboardOverview = () =>
  request<DashboardOverview>('/api/dashboard/overview', {}, PURPOSE.WELFARE_SUPPORT)

/** Per-person cases needing review. Welfare purpose only - the endpoint enforces it. */
export const getAttentionCases = (limit = 25) =>
  request<{ as_of_date: string; cases: any[]; count: number; privacy_note: string }>(
    `/api/dashboard/attention?limit=${limit}`,
    {},
    PURPOSE.WELFARE_SUPPORT,
  )

export const getDashboardTrend = (days = 30, purpose = PURPOSE.AGGREGATE_OPERATIONS) =>
  request<{ days: number; points: TrendPoint[] }>(`/api/dashboard/trend?days=${days}`, {}, purpose)
export const getUnitSummary = (purpose = PURPOSE.AGGREGATE_OPERATIONS) =>
  request<{ as_of_date: string; units: UnitSummary[] }>('/api/dashboard/units', {}, purpose)
export const getUnitDetail = (unitId: string, purpose = PURPOSE.AGGREGATE_OPERATIONS) =>
  request<any>(`/api/dashboard/unit/${encodeURIComponent(unitId)}`, {}, purpose)
export const getPersonDetail = (personId: string) =>
  request<PersonDetail>(`/api/dashboard/person/${encodeURIComponent(personId)}`, {}, PURPOSE.WELFARE_SUPPORT)
export const getPersonnel = (query = '', unitId = '', riskBand = '', limit = 50) =>
  request<{
    items: PersonnelRow[]
    count: number
    total_personnel: number
    total_matching: number
    limit: number
    truncated: boolean
    privacy_note: string
  }>(
    `/api/dashboard/personnel?query=${encodeURIComponent(query)}&unit_id=${encodeURIComponent(unitId)}&risk_band=${encodeURIComponent(riskBand)}&limit=${limit}`,
    {},
    PURPOSE.WELFARE_SUPPORT,
  )
export const searchDashboard = (query: string, purpose = PURPOSE.WELFARE_SUPPORT) =>
  request<{ query: string; results: SearchResult[]; privacy_note?: string }>(
    `/api/dashboard/search?query=${encodeURIComponent(query)}`,
    {},
    purpose,
  )
export const getDataSources = (purpose = PURPOSE.AGGREGATE_OPERATIONS) =>
  request<{ environment: string; sources: DataSource[]; privacy_note: string }>(
    '/api/dashboard/data-sources',
    {},
    purpose,
  )
export const getAuditView = (purpose = PURPOSE.AUDIT) =>
  request<{
    chain_valid: boolean
    chain_reason?: string
    audit_records?: number
    audit_anchored?: boolean
    event_count: number
    events: AuditRecord[]
    privacy_note: string
  }>('/api/dashboard/audit', {}, purpose)
/** Readable by the auditor (AUDIT purpose) and the infrastructure admin. */
export const getSystemHealth = (purpose = PURPOSE.AUDIT) =>
  request<any>('/api/dashboard/system-health', {}, purpose)

export const getPendingWorkflow = (limit = 30) =>
  request<{ items: WorkflowItem[]; count: number; truncated?: boolean }>(
    `/api/workflow/pending?limit=${limit}`,
    {},
    PURPOSE.WELFARE_SUPPORT,
  )
export const getWorkflowItem = (workflowItemId: string) =>
  request<WorkflowItem>(`/api/workflow/${encodeURIComponent(workflowItemId)}`, {}, PURPOSE.WELFARE_SUPPORT)

/**
 * @param expectedState the state the UI loaded. The server rejects the
 * transition if the case moved on, so a stale screen cannot overwrite someone
 * else's decision.
 */
export const transitionWorkflow = (
  workflowItemId: string,
  newState: WorkflowState,
  reasonCode: string,
  expectedState?: string,
) =>
  request<WorkflowItem>(`/api/workflow/${encodeURIComponent(workflowItemId)}/transition`, {
    method: 'POST',
    body: JSON.stringify({ new_state: newState, reason_code: reasonCode, expected_state: expectedState ?? null }),
  })

/** @param idempotencyKey stable across retries so a double-click records once. */
export const recordWorkflowFeedback = (
  workflowItemId: string,
  helpfulness: number,
  comment: string | null,
  followUpRequested: boolean,
  idempotencyKey?: string,
) =>
  request<WorkflowItem>(`/api/workflow/${encodeURIComponent(workflowItemId)}/feedback`, {
    method: 'POST',
    headers: idempotencyKey ? { 'Idempotency-Key': idempotencyKey } : {},
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

export const getFollowUps = (status?: string, purpose = PURPOSE.WELFARE_SUPPORT) =>
  request<{ items: FollowUpRecord[]; count: number; privacy_note?: string }>(
    `/api/workflow/follow-ups?limit=200${status ? `&status=${encodeURIComponent(status)}` : ''}`,
    {},
    purpose,
  )