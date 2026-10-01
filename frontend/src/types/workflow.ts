export type WorkflowState =
  | 'NEW'
  | 'ACKNOWLEDGED'
  | 'IN_REVIEW'
  | 'SUPPORT_PLANNED'
  | 'SUPPORT_COMPLETED'
  | 'FOLLOW_UP_SCHEDULED'
  | 'FOLLOW_UP_DUE'
  | 'FOLLOW_UP_COMPLETED'
  | 'CLOSED'
  | 'COMPLETED'
  | 'DEFERRED'
  | 'DISMISSED'

export type WorkflowHistoryEvent = {
  event_id: string
  workflow_item_id: string
  person_id: string
  date: string
  previous_state: WorkflowState
  new_state: WorkflowState
  actor_role: string
  purpose: string
  timestamp: string
  reason_code: string
  model_version: string
  policy_version: string
  feasibility_policy_version: string
  workflow_policy_version: string
}

export type SupportEventRecord = {
  support_event_id: string
  workflow_item_id: string
  person_id: string
  support_action: string
  completed_at: string
  actor_role: string
}

export type FeedbackRecord = {
  feedback_id: string
  support_event_id: string
  helpfulness: number
  comment: string | null
  follow_up_requested: boolean
  submitted_at: string
  recorded_by_role: string
}

export type FollowUpRecord = {
  followup_id: string
  workflow_item_id: string
  support_event_id: string
  person_id: string
  scheduled_for: string
  status: string
  created_at: string
  created_by_role: string
  last_updated_at: string
  completed_at: string | null
  completed_by_role: string | null
  risk_band?: string
  recommended_action?: string
  priority?: string
  feasibility_status?: string
  constraint_flags?: string
  workflow_state?: WorkflowState
  support_completed_at?: string | null
  support_action?: string
  support_actor_role?: string
  follow_up_requested?: boolean
}

export type WorkflowItem = {
  workflow_item_id: string
  person_id: string
  unit_id?: string | null
  date: string
  risk_band: 'LOW' | 'MODERATE' | 'HIGH'
  recommended_action: string
  priority: string
  feasibility_status: string
  constraint_flags: string
  rationale: string
  requires_human_review: boolean
  model_version: string
  policy_version: string
  feasibility_policy_version: string
  workflow_state: WorkflowState
  last_transition_at: string | null
  last_actor_role: string | null
  last_reason_code: string | null
  support_completed_at?: string | null
  support_completed_by_role?: string | null
  active_support_event_id?: string | null
  active_followup_id?: string | null
  feedback_submitted?: boolean
  trend?: 'RISING' | 'STABLE' | 'IMPROVING'
  history?: WorkflowHistoryEvent[]
  support_event?: SupportEventRecord | null
  feedback?: FeedbackRecord | null
  followup?: FollowUpRecord | null
  privacy_note?: string
}
