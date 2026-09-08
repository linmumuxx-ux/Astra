import type {
  AstraEvent,
  DashboardActivity,
  DashboardAttention,
  DashboardEmployees,
  DashboardKnowledge,
  DashboardOverview,
  DashboardTasks,
  Employee,
  EmployeeUsage,
  Evidence,
  ExecutionEnvironment,
  KnowledgeDetail,
  KnowledgePage,
  KnowledgeSpace,
  KnowledgeUsageRecord,
  LibraryPermissions,
  Metrics,
  LibraryStats,
  LibraryUsageSummary,
  LibraryServiceStatus,
  RelatedTask,
  Run,
  RunUsage,
  RunPage,
  Task,
  TaskCategory,
  TaskCategoryWrite,
  TaskUsage,
  TaskWorkbench,
} from './types'

const API_BASE = import.meta.env.VITE_API_BASE ?? ''

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message)
  }
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', ...options?.headers },
    ...options,
  })
  if (!response.ok) {
    const body = await response.json().catch(() => ({ detail: response.statusText }))
    throw new ApiError(body.detail ?? '请求失败', response.status)
  }
  return response.json() as Promise<T>
}

export const api = {
  metrics: () => request<Metrics>('/api/system/metrics'),
  health: () => request<{ status: string; time: string }>('/api/health'),
  dashboardOverview: () => request<DashboardOverview>('/api/dashboard/overview'),
  dashboardEmployees: () => request<DashboardEmployees>('/api/dashboard/employees'),
  dashboardAttention: () => request<DashboardAttention>('/api/dashboard/attention'),
  dashboardTasks: () => request<DashboardTasks>('/api/dashboard/tasks'),
  dashboardActivity: () => request<DashboardActivity>('/api/dashboard/activity'),
  dashboardKnowledge: () => request<DashboardKnowledge>('/api/dashboard/knowledge'),
  categories: (includeDisabled = false) => request<TaskCategory[]>(`/api/task-categories${includeDisabled ? '?include_disabled=true' : ''}`),
  createCategory: (body: TaskCategoryWrite) => request<TaskCategory>('/api/task-categories', { method: 'POST', body: JSON.stringify(body) }),
  updateCategory: (id: string, body: TaskCategoryWrite) => request<TaskCategory>(`/api/task-categories/${id}`, { method: 'PATCH', body: JSON.stringify(body) }),
  employees: () => request<Employee[]>('/api/employees'),
  employee: (id: string) => request<Employee>(`/api/employees/${id}`),
  employeeUsage: (id: string, days = 7) => request<EmployeeUsage>(`/api/employees/${id}/usage?days=${days}`),
  createEmployee: (body: Record<string, unknown>) =>
    request<Employee>('/api/employees', { method: 'POST', body: JSON.stringify(body) }),
  updateEmployee: (id: string, body: Record<string, unknown>) =>
    request<Employee>(`/api/employees/${id}`, { method: 'PATCH', body: JSON.stringify(body) }),
  updateEnvironment: (id: string, body: Record<string, unknown>) =>
    request<ExecutionEnvironment>(`/api/employees/${id}/environment`, { method: 'PUT', body: JSON.stringify(body) }),
  testEnvironment: (id: string) =>
    request<{ status: string; checked_at: string; checks: Array<{ name: string; passed: boolean; detail: string }> }>(`/api/employees/${id}/environment/test`, { method: 'POST' }),
  tasks: (query = '') => request<Task[]>(`/api/tasks${query}`),
  task: (id: string) => request<Task>(`/api/tasks/${id}`),
  taskWorkbench: (id: string, beforeSequence?: number) =>
    request<TaskWorkbench>(`/api/tasks/${id}/workspace${beforeSequence ? `?before_sequence=${beforeSequence}` : ''}`),
  postTaskMessage: (id: string, content: string) =>
    request<TaskWorkbench>(`/api/tasks/${id}/messages`, { method: 'POST', body: JSON.stringify({ content }) }),
  answerInquiry: (id: string, answer: string) =>
    request<TaskWorkbench>(`/api/inquiries/${id}/answer`, { method: 'POST', body: JSON.stringify({ answer }) }),
  taskUsage: (id: string) => request<TaskUsage>(`/api/tasks/${id}/usage`),
  events: (limit = 50) => request<AstraEvent[]>(`/api/events?limit=${limit}`),
  taskEvents: (id: string) => request<AstraEvent[]>(`/api/tasks/${id}/events`),
  runPage: (params: URLSearchParams) => request<RunPage>(`/api/runs/page?${params}`),
  runs: () => request<Run[]>('/api/runs'),
  run: (id: string) => request<Run>(`/api/runs/${id}`),
  runUsage: (id: string) => request<RunUsage>(`/api/runs/${id}/usage`),
  runEvents: (id: string) => request<AstraEvent[]>(`/api/runs/${id}/events`),
  taskRuns: (id: string) => request<Run[]>(`/api/tasks/${id}/runs`),
  evidence: (id: string) => request<Evidence[]>(`/api/tasks/${id}/evidence`),
  taskAction: (id: string, action: string, body: Record<string, unknown> = {}) =>
    request<Task>(`/api/tasks/${id}/${action}`, { method: 'POST', body: JSON.stringify(body) }),
  employeeAction: (id: string, action: 'pause' | 'resume') =>
    request<Employee>(`/api/employees/${id}/${action}`, { method: 'POST' }),
  createTask: (body: Record<string, unknown>) =>
    request<Task>('/api/tasks', { method: 'POST', body: JSON.stringify(body) }),
  libraryPermissions: () => request<LibraryPermissions>('/api/library/permissions'),
  libraryServiceStatus: () => request<LibraryServiceStatus>('/api/library/service/status'),
  libraryResync: () => request<{ pending_count: number }>('/api/library/service/resync', { method: 'POST' }),
  libraryStats: () => request<LibraryStats>('/api/library/stats'),
  librarySpaces: () => request<KnowledgeSpace[]>('/api/library/spaces'),
  createLibrarySpace: (body: Record<string, unknown>) =>
    request<KnowledgeSpace>('/api/library/spaces', { method: 'POST', body: JSON.stringify(body) }),
  updateLibrarySpace: (id: string, body: Record<string, unknown>) =>
    request<KnowledgeSpace>(`/api/library/spaces/${id}`, { method: 'PUT', body: JSON.stringify(body) }),
  moveLibrarySpace: (id: string, targetParentId: string | null) =>
    request<KnowledgeSpace>(`/api/library/spaces/${id}/move`, { method: 'POST', body: JSON.stringify({ target_parent_id: targetParentId }) }),
  deleteLibrarySpace: (id: string) =>
    request<{ deleted: string }>(`/api/library/spaces/${id}`, { method: 'DELETE' }),
  libraryKnowledge: (query = '') => request<KnowledgePage>(`/api/library/knowledge${query}`),
  libraryKnowledgeDetail: (id: string) => request<KnowledgeDetail>(`/api/library/knowledge/${id}`),
  createLibraryKnowledge: (body: Record<string, unknown>) =>
    request<KnowledgeDetail>('/api/library/knowledge', { method: 'POST', body: JSON.stringify(body) }),
  updateLibraryKnowledge: (id: string, body: Record<string, unknown>) =>
    request<KnowledgeDetail>(`/api/library/knowledge/${id}`, { method: 'PUT', body: JSON.stringify(body) }),
  publishLibraryKnowledge: (id: string, body: Record<string, unknown>) =>
    request<KnowledgeDetail>(`/api/library/knowledge/${id}/publish`, { method: 'POST', body: JSON.stringify(body) }),
  rejectLibraryKnowledge: (id: string, reason: string) =>
    request<KnowledgeDetail>(`/api/library/knowledge/${id}/reject`, { method: 'POST', body: JSON.stringify({ reason }) }),
  supplementLibraryKnowledge: (id: string, reason: string) =>
    request<KnowledgeDetail>(`/api/library/knowledge/${id}/request-supplement`, { method: 'POST', body: JSON.stringify({ reason }) }),
  moveLibraryKnowledge: (id: string, spaceId: string) =>
    request<KnowledgeDetail>(`/api/library/knowledge/${id}/move`, { method: 'POST', body: JSON.stringify({ space_id: spaceId }) }),
  batchMoveLibraryKnowledge: (ids: string[], spaceId: string) =>
    request<{ moved: number }>('/api/library/knowledge/batch-move', { method: 'POST', body: JSON.stringify({ knowledge_ids: ids, space_id: spaceId }) }),
  batchArchiveLibraryKnowledge: (ids: string[]) =>
    request<{ archived: number }>('/api/library/knowledge/batch-archive', { method: 'POST', body: JSON.stringify({ knowledge_ids: ids }) }),
  batchPublishLibraryKnowledge: (ids: string[], spaceId: string, verificationStatus: string) =>
    request<{ published: number }>('/api/library/knowledge/batch-publish', { method: 'POST', body: JSON.stringify({ knowledge_ids: ids, space_id: spaceId, verification_status: verificationStatus }) }),
  archiveLibraryKnowledge: (id: string) =>
    request<KnowledgeDetail>(`/api/library/knowledge/${id}/archive`, { method: 'POST' }),
  deleteLibraryKnowledge: (id: string) =>
    request<{ deleted: string }>(`/api/library/knowledge/${id}`, { method: 'DELETE' }),
  batchDeleteLibraryKnowledge: (ids: string[]) =>
    Promise.all(ids.map((id) => request<{ deleted: string }>(`/api/library/knowledge/${id}`, { method: 'DELETE' }))),
  libraryKnowledgeUsages: (id: string, limit = 20) =>
    request<KnowledgeUsageRecord[]>(`/api/library/knowledge/${id}/usages?limit=${limit}`),
  favoriteLibraryKnowledge: (id: string) =>
    request<{ favorite: boolean }>(`/api/library/knowledge/${id}/favorite`, { method: 'POST' }),
  helpfulLibraryKnowledge: (id: string) =>
    request<{ created: boolean; helpful_count: number }>(`/api/library/knowledge/${id}/helpful`, { method: 'POST' }),
  libraryRelatedTasks: (id: string) => request<RelatedTask[]>(`/api/library/knowledge/${id}/related-tasks`),
  libraryUsageSummary: (days = 7) => request<LibraryUsageSummary>(`/api/library/usage/summary?days=${days}`),
}
