import type { AstraEvent, Employee, Evidence, Metrics, Run, Task } from './types'

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
  tasks: (query = '') => request<Task[]>(`/api/tasks${query}`),
  task: (id: string) => request<Task>(`/api/tasks/${id}`),
  events: (limit = 50) => request<AstraEvent[]>(`/api/events?limit=${limit}`),
  taskEvents: (id: string) => request<AstraEvent[]>(`/api/tasks/${id}/events`),
  runs: () => request<Run[]>('/api/runs'),
  taskRuns: (id: string) => request<Run[]>(`/api/tasks/${id}/runs`),
  evidence: (id: string) => request<Evidence[]>(`/api/tasks/${id}/evidence`),
  taskAction: (id: string, action: string, body: Record<string, unknown> = {}) =>
    request<Task>(`/api/tasks/${id}/${action}`, { method: 'POST', body: JSON.stringify(body) }),
  employeeAction: (id: string, action: 'pause' | 'resume') =>
    request<Employee>(`/api/employees/${id}/${action}`, { method: 'POST' }),
  createTask: (body: Record<string, unknown>) =>
    request<Task>('/api/tasks', { method: 'POST', body: JSON.stringify(body) }),
}
