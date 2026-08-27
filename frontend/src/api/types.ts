export type TaskType = 'ISSUE' | 'REQUIREMENT'
export type TaskPriority = 'VERY_HIGH' | 'HIGH' | 'MEDIUM' | 'LOW'
export type TaskStatus = 'READY' | 'RUNNING' | 'WAIT_HUMAN' | 'SUSPENDED' | 'PENDING_CONFIRMATION' | 'COMPLETED' | 'FAILED' | 'EXECUTION_ERROR' | 'CANCELLED'
export type CompletionPolicy = 'AUTO' | 'MANUAL_CONFIRM'
export type AcceptanceStatus = 'SATISFIED' | 'UNSATISFIED' | 'UNCONFIRMED'

export interface TaskCategory {
  id: string
  name: string
  description: string
  enabled: boolean
  sort_order: number
  created_at: string
  updated_at: string
}

export interface ExecutionEnvironment {
  id: number
  employee_id: string
  mode: 'LOCAL' | 'LINUX_REMOTE'
  name: string
  description: string
  host: string | null
  port: number
  username: string | null
  auth_method: 'SSH_AGENT' | 'SSH_KEY'
  ssh_key_path: string | null
  opencode_path: string
  model_name: string | null
  workspace_root: string
  status: 'UNKNOWN' | 'CHECKING' | 'AVAILABLE' | 'UNAVAILABLE'
  status_detail: Record<string, unknown>
  labels: string[]
  last_checked_at: string | null
  created_at: string
  updated_at: string
}

export interface UsageSummary {
  input_tokens: number | null
  output_tokens: number | null
  cache_read_tokens: number | null
  cache_write_tokens: number | null
  total_tokens: number | null
  llm_call_count: number | null
  tool_call_count: number | null
  tool_success_count: number
  tool_failure_count: number
  duration_seconds: number
  completed_tasks: number
  task_count: number
}

export interface ToolUsage {
  tool_name: string
  call_count: number
  success_count: number
  failure_count: number
  duration_ms: number
}

export interface EmployeeUsage {
  period_days: number
  summary: UsageSummary
  trend: Array<{ date: string } & UsageSummary>
  tools: ToolUsage[]
}

export interface TaskUsage { summary: UsageSummary; tools: ToolUsage[]; runs: number }
export interface RunUsage { summary: UsageSummary; tools: ToolUsage[] }

export interface Employee {
  id: string
  name: string
  role: string
  description: string
  status: string
  task_types: TaskType[]
  category_ids: string[]
  enabled: boolean
  auto_claim: boolean
  auto_execute: boolean
  max_auto_retries: number
  current_task_count: number
  last_heartbeat: string | null
  online_since: string | null
  created_at: string
  updated_at: string
  execution_environment: ExecutionEnvironment | null
  today_usage: UsageSummary
  today_completed: number
}

export interface AcceptanceCriterion { id: string; content: string }
export interface AcceptanceResult {
  criterion_id: string
  status: AcceptanceStatus
  description: string
  evidence: string[]
}

export interface WorkResult {
  summary: string
  changes: string[]
  files: string[]
  commits: string[]
  logs: string[]
  attachments: string[]
  other: Record<string, unknown>
  acceptance_results: AcceptanceResult[]
}

export interface HumanIntervention {
  blocking_reason: string
  completed_work: string
  current_state: string
  requested_input: string
  can_suspend?: boolean
  scene_context?: string
}

export interface Task {
  id: string
  source: string
  external_task_id: string | null
  task_type: TaskType
  category_id: string | null
  title: string
  description: string
  acceptance_criteria: AcceptanceCriterion[]
  attachments: Array<Record<string, unknown>>
  priority: TaskPriority
  completion_policy: CompletionPolicy
  status: TaskStatus
  employee_id: string | null
  opencode_session_id: string | null
  current_progress: string
  result: WorkResult | null
  failure_reason: string | null
  human_required_reason: string | null
  human_intervention: HumanIntervention | null
  suspension: Record<string, unknown> | null
  execution_error: Record<string, unknown> | null
  review_history: Array<Record<string, unknown>>
  inactivity_alert: boolean
  inactivity_alert_since: string | null
  last_activity_at: string | null
  submitted_at: string | null
  confirmed_at: string | null
  execution_environment_snapshot: Record<string, unknown> | null
  claimed_at: string | null
  started_at: string | null
  finished_at: string | null
  created_at: string
  updated_at: string
}

export interface Run {
  id: string
  task_id: string
  employee_id: string
  run_number: number
  status: string
  executor_type: string
  opencode_session_id: string | null
  started_at: string
  finished_at: string | null
  exit_code: number | null
  result: Record<string, unknown> | null
  execution_environment_snapshot: Record<string, unknown>
  model_name: string | null
  input_tokens: number | null
  output_tokens: number | null
  cache_read_tokens: number | null
  cache_write_tokens: number | null
  total_tokens: number | null
  llm_call_count: number | null
  tool_call_count: number | null
  created_at: string
}

export interface AstraEvent {
  id: number
  task_id: string | null
  employee_id: string | null
  run_id: string | null
  event_type: string
  phase: string
  message: string
  detail: Record<string, unknown>
  created_at: string
}

export interface Evidence {
  id: number
  task_id: string
  run_id: string | null
  name: string
  kind: string
  path: string
  size: number
  content_type: string
  metadata_: Record<string, unknown>
  created_at: string
}

export interface Metrics {
  online_employees: number
  running_tasks: number
  idle_employees: number
  error_employees: number
  ready_tasks: number
  wait_human_tasks: number
  pending_confirmation_tasks: number
  execution_error_tasks: number
  completed_today: number
  failed_today: number
  today_tokens: number | null
  today_tool_calls: number | null
  task_status_distribution: Record<string, number>
  employee_status_distribution: Record<string, number>
}
