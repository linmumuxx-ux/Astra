export interface Employee {
  id: string
  name: string
  role: string
  description: string
  status: string
  capabilities: string[]
  source_scope: string[]
  max_concurrency: number
  current_task_count: number
  last_heartbeat: string | null
  online_since: string | null
  created_at: string
  updated_at: string
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
  task_status_distribution: Record<string, number>
  employee_status_distribution: Record<string, number>
}
