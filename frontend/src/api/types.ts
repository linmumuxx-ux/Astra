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
  performance: {
    completed_tasks: number
    autonomous_completion_rate: number | null
    human_intervention_rate: number | null
    success_rate: number | null
    average_retries: number | null
    average_duration_seconds: number | null
  }
}

export interface TaskUsage {
  summary: UsageSummary
  tools: ToolUsage[]
  runs: number
}

export interface RunUsage {
  summary: UsageSummary
  tools: ToolUsage[]
}

export interface Employee {
  id: string
  name: string
  role: string
  description: string
  status: string
  capabilities: string[]
  skills: string[]
  source_scope: string[]
  enabled: boolean
  auto_claim: boolean
  auto_execute: boolean
  auto_repair: boolean
  max_auto_retries: number
  max_concurrency: number
  current_task_count: number
  last_heartbeat: string | null
  online_since: string | null
  created_at: string
  updated_at: string
  execution_environment: ExecutionEnvironment | null
  today_usage: UsageSummary
  today_completed: number
  success_rate: number | null
}

export interface Task {
  id: string
  source: string
  external_task_id: string | null
  task_type: string
  title: string
  description: string
  input: Record<string, unknown>
  definition_of_done: string[]
  priority: string
  status: string
  employee_id: string | null
  workspace: string | null
  opencode_session_id: string | null
  current_phase: string
  progress: number
  retry_count: number
  max_retry_count: number
  result: Record<string, unknown> | null
  failure_reason: string | null
  human_required_reason: string | null
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
  ready_tasks: number
  wait_human_tasks: number
  completed_today: number
  failed_today: number
  today_tokens: number | null
  today_tool_calls: number | null
  task_status_distribution: Record<string, number>
  employee_status_distribution: Record<string, number>
}
