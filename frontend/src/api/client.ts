import type { AstraEvent, Employee, EmployeeUsage, Evidence, ExecutionEnvironment, Metrics, Run, RunUsage, Task, TaskUsage } from './types'

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
  taskUsage: (id: string) => request<TaskUsage>(`/api/tasks/${id}/usage`),
  events: (limit = 50) => request<AstraEvent[]>(`/api/events?limit=${limit}`),
  taskEvents: (id: string) => request<AstraEvent[]>(`/api/tasks/${id}/events`),
  runs: () => request<Run[]>('/api/runs'),
  run: (id: string) => request<Run>(`/api/runs/${id}`),
  runUsage: (id: string) => request<RunUsage>(`/api/runs/${id}/usage`),
  taskRuns: (id: string) => request<Run[]>(`/api/tasks/${id}/runs`),
  evidence: (id: string) => request<Evidence[]>(`/api/tasks/${id}/evidence`),
  taskAction: (id: string, action: string, body: Record<string, unknown> = {}) =>
    request<Task>(`/api/tasks/${id}/${action}`, { method: 'POST', body: JSON.stringify(body) }),
  employeeAction: (id: string, action: 'pause' | 'resume') =>
    request<Employee>(`/api/employees/${id}/${action}`, { method: 'POST' }),
  createTask: (body: Record<string, unknown>) =>
    request<Task>('/api/tasks', { method: 'POST', body: JSON.stringify(body) }),
}
