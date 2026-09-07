export type TaskType = 'ISSUE' | 'REQUIREMENT'
export type TaskPriority = 'VERY_HIGH' | 'HIGH' | 'MEDIUM' | 'LOW'
export type TaskStatus = 'READY' | 'ASSIGNED' | 'QUEUED' | 'RUNNING' | 'WAIT_HUMAN' | 'SUSPENDED' | 'PENDING_CONFIRMATION' | 'COMPLETED' | 'FAILED' | 'EXECUTION_ERROR' | 'CANCELLED'
export type CompletionPolicy = 'AUTO' | 'MANUAL_CONFIRM'
export type AcceptanceStatus = 'SATISFIED' | 'UNSATISFIED' | 'UNCONFIRMED'

export interface TaskCategory {
  id: string
  name: string
  description: string
  task_prompt: string | null
  question_prompt: string | null
  enabled: boolean
  sort_order: number
  created_at: string
  updated_at: string
}

export type TaskCategoryWrite = Pick<TaskCategory, 'name' | 'description' | 'enabled' | 'sort_order' | 'task_prompt' | 'question_prompt'>

export interface ExecutionEnvironment {
  id: number
  employee_id: string
  mode: 'LOCAL' | 'LINUX_REMOTE'
  name: string
  description: string
  host: string | null
  port: number
  username: string | null
  has_ssh_password: boolean
  opencode_server_port: number
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
  default_work_area: 'development' | 'collaboration' | 'pantry' | 'integration' | 'meeting' | 'special'
  status: string
  task_types: TaskType[]
  category_ids: string[]
  enabled: boolean
  auto_claim: boolean
  auto_execute: boolean
  max_auto_retries: number
  current_task_count: number
  active_run_id: string | null
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
  active_run_id: string | null
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
  previous_run_id: string | null
  run_number: number
  status: string
  executor_type: string
  opencode_session_id: string | null
  queued_at: string | null
  dispatched_at: string | null
  started_at: string | null
  finished_at: string | null
  celery_task_id: string | null
  dispatch_attempt: number
  heartbeat_at: string | null
  worker_id: string | null
  executor_status: string | null
  failure_type: string | null
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

export interface TaskSession {
  id: string
  task_id: string
  status: 'ACTIVE' | 'WAITING_INPUT' | 'PAUSED' | 'COMPLETED' | 'FAILED' | 'CANCELLED'
  current_run_id: string | null
  created_at: string
  updated_at: string
}

export interface SessionMessage {
  id: string
  session_id: string
  run_id: string | null
  role: 'user' | 'agent' | 'system'
  content: string
  status: 'PENDING' | 'QUEUED' | 'APPLIED' | 'ANSWERED'
  created_at: string
}

export interface RunInquiry {
  id: string
  session_id: string
  run_id: string | null
  agent_name: string | null
  question: string
  description: string
  options: Array<{ label?: string; value?: string; description?: string }>
  answer: string | null
  status: 'OPEN' | 'PENDING' | 'ANSWERED' | 'CANCELLED'
  created_at: string
  answered_at: string | null
}

export interface RuntimeEvent {
  id: string
  session_id: string
  run_id: string | null
  sequence: number
  event_type: string
  agent_name: string | null
  timestamp: string
  phase: string
  summary: string
  payload: Record<string, unknown>
}

export interface SessionBlock {
  id: string
  session_id: string
  run_id: string | null
  sequence: number | null
  block_type: 'message' | 'inquiry' | 'event' | 'operation_group'
  semantic_type: string
  visibility: 'primary' | 'diagnostic'
  actor_name: string | null
  status: string | null
  timestamp: string
  summary: string
  payload: Record<string, unknown>
  message: SessionMessage | null
  inquiry: RunInquiry | null
  events: RuntimeEvent[]
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

export interface TaskWorkbench {
  task: Task
  session: TaskSession
  messages: SessionMessage[]
  events: RuntimeEvent[]
  blocks: SessionBlock[]
  inquiries: RunInquiry[]
  artifacts: Evidence[]
  runs: Run[]
  has_more_events: boolean
}

export type KnowledgeType = 'document' | 'rule' | 'guide' | 'experience' | 'faq' | 'tool' | 'example'
export type KnowledgeStatus = 'draft' | 'candidate' | 'published' | 'archived' | 'rejected'
export type VerificationStatus = 'unverified' | 'verified' | 'failed'

export interface LibraryPermissions {
  user_id: string
  role: 'viewer' | 'maintainer' | 'reviewer' | 'admin'
  can_manage: boolean
  can_review: boolean
}

export interface LibraryStats {
  knowledge_pages: number
  knowledge_spaces: number
  weekly_references: number
  published_experiences: number
  candidate_experiences: number
}

export interface KnowledgeSpace {
  id: string
  name: string
  description: string
  parent_id: string | null
  sort_order: number
  status: string
  access_scope: string
  knowledge_count: number
  subtree_knowledge_count: number
  children: KnowledgeSpace[]
  created_at: string
  updated_at: string
}

export interface KnowledgeUsageRecord {
  id: number
  employee_id: string | null
  employee_name: string | null
  task_id: string | null
  task_title: string | null
  action: string
  used_at: string
}

export interface KnowledgeListItem {
  id: string
  space_id: string | null
  space_name: string | null
  title: string
  type: KnowledgeType
  summary: string
  status: KnowledgeStatus
  verification_status: VerificationStatus
  tags: string[]
  source_type: string | null
  source_task_id: string | null
  reference_count: number
  helpful_count: number
  updated_at: string
  published_at: string | null
}

export interface KnowledgeSource {
  id: number
  source_type: string
  source_id: string | null
  source_name: string | null
  source_uri: string | null
  version: string | null
  created_at: string
}

export interface ExperienceEvidence {
  id: number
  task_id: string | null
  run_id: string | null
  evidence_type: string
  content: string | null
  uri: string | null
  result: string | null
  created_at: string
}

export interface KnowledgeDetail extends KnowledgeListItem {
  content_md: string
  source_type: string | null
  source_ref: string | null
  source_employee_id: string | null
  source_employee_name: string | null
  source_task_title: string | null
  source_run_id: string | null
  experience_data: Record<string, unknown>
  review_note: string | null
  created_by: string
  updated_by: string
  published_by: string | null
  created_at: string
  sources: KnowledgeSource[]
  evidence: ExperienceEvidence[]
  is_favorite: boolean
  user_helpful: boolean
}

export interface KnowledgePage {
  items: KnowledgeListItem[]
  total: number
  page: number
  page_size: number
  pages: number
}

export interface UsageTopKnowledge {
  knowledge_id: string
  title: string
  reference_count: number
}

export interface LibraryUsageSummary {
  days: number
  total_references: number
  active_employees: number
  top_knowledge: UsageTopKnowledge[]
  popular_space: string | null
  trend: Array<{ date: string; reference_count: number }>
}

export interface RelatedTask {
  id: string
  title: string
  status: string
  relation: string
  last_used_at: string | null
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

export interface DashboardOverview {
  employee_total: number
  team_count: number
  working_employees: number
  running_tasks: number
  completed_today: number
  attention_total: number
}

export interface DashboardEmployee {
  id: string
  name: string
  role: string
  status: string
  state: 'working' | 'idle' | 'waiting' | 'error'
  state_label: '执行中' | '空闲' | '等待' | '异常'
  current_task: { id: string; title: string; status: string } | null
}

export interface DashboardTeam {
  id: string
  name: string
  order: number
  employee_count: number
  employees: DashboardEmployee[]
}

export interface DashboardEmployees {
  teams: DashboardTeam[]
}

export interface DashboardAttentionItem {
  task_id: string
  task_title: string
  employee_id: string | null
  employee_name: string
  status: 'execution_failed' | 'blocked' | 'waiting' | 'exception'
  status_label: '执行失败' | '任务阻塞' | '等待处理' | '异常'
  occurred_at: string
}

export interface DashboardAttention {
  items: DashboardAttentionItem[]
}

export interface DashboardTaskTrendPoint {
  date: string
  total: number
  completed: number
}

export interface DashboardTasks {
  running: number
  waiting: number
  completed_today: number
  failed_today: number
  trend: DashboardTaskTrendPoint[]
  recent: Array<{
    id: string
    title: string
    status: string
    employee_id: string | null
    employee_name: string
    updated_at: string
  }>
}

export interface DashboardActivityItem {
  id: number
  employee_id: string | null
  employee_name: string
  kind: 'task_created' | 'task_started' | 'task_completed' | 'task_failed' | 'waiting_human' | 'schedule_triggered' | 'employee_created'
  description: string
  created_at: string
  target_type: 'task' | 'employee' | null
  target_id: string | null
}

export interface DashboardActivity {
  items: DashboardActivityItem[]
}

export interface DashboardKnowledge {
  today_added: number
  candidate_experiences: number
  total: number
  recent: Array<{ id: string; title: string }>
}

export interface RunStats {
  run_count: number
  task_count: number
  completed_count: number
  failed_count: number
  retry_count: number
  waiting_input_count: number
  success_rate: number | null
  avg_duration_seconds: number | null
  total_tokens: number | null
}
export interface RunPage {
  items: (Run & { task_title: string })[]
  page: number
  page_size: number
  total: number
  stats: RunStats
}
