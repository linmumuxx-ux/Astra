import type { Employee, Task } from '@/api/types'

export const EMPLOYEE_STATES = [
  'OFFLINE', 'IDLE', 'WORKING', 'WAITING', 'NEED_HUMAN', 'ERROR', 'COMPLETED',
] as const
export type EmployeeState = (typeof EMPLOYEE_STATES)[number]
export type EmployeeMotion = 'idle' | 'working' | 'waiting' | 'error' | 'celebrate'

export interface EmployeeStatePresentation {
  label: string
  detail: string
  motion: EmployeeMotion
  tone: 'muted' | 'normal' | 'info' | 'warning' | 'danger' | 'success'
}

export const EMPLOYEE_STATE_PRESENTATION: Record<EmployeeState, EmployeeStatePresentation> = {
  OFFLINE: { label: '离线', detail: '当前不可用', motion: 'idle', tone: 'muted' },
  IDLE: { label: '空闲', detail: '等待新任务', motion: 'idle', tone: 'normal' },
  WORKING: { label: '工作中', detail: '正在推进当前任务', motion: 'working', tone: 'info' },
  WAITING: { label: '等待中', detail: '当前工作已暂停', motion: 'waiting', tone: 'warning' },
  NEED_HUMAN: { label: '等待人工', detail: '等待你的确认', motion: 'waiting', tone: 'warning' },
  ERROR: { label: '异常', detail: '执行异常，工作现场已保留', motion: 'error', tone: 'danger' },
  COMPLETED: { label: '刚完成', detail: '任务已完成', motion: 'celebrate', tone: 'success' },
}

export function resolveEmployeeState(employee: Employee, task?: Task, recentlyCompleted = false): EmployeeState {
  if (!employee.enabled || employee.status === 'OFFLINE') return 'OFFLINE'
  if (employee.status === 'ERROR' || task?.status === 'EXECUTION_ERROR' || task?.status === 'FAILED') return 'ERROR'
  if (employee.status === 'WAIT_HUMAN' || task?.status === 'WAIT_HUMAN' || task?.status === 'PENDING_CONFIRMATION') return 'NEED_HUMAN'
  if (task?.status === 'SUSPENDED' || employee.status === 'PAUSED') return 'WAITING'
  if (task?.status === 'RUNNING' || task?.status === 'READY' || employee.status === 'WORKING') return 'WORKING'
  if (recentlyCompleted) return 'COMPLETED'
  return 'IDLE'
}

export function statePriority(state: EmployeeState): number {
  return ({ ERROR: 0, NEED_HUMAN: 1, WORKING: 2, COMPLETED: 3, WAITING: 4, IDLE: 5, OFFLINE: 6 })[state]
}
