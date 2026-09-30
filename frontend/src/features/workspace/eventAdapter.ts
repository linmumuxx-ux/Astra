import type { AstraEvent, Employee, Task } from '@/api/types'
import { employeeCurrentTask } from '@/features/employees/presentation'
import { employeeDisplayName, platformCopy } from '@/utils/format'
import { assignEmployeeCharacterIndices } from './characterAssets'
import { EMPLOYEE_STATE_PRESENTATION, resolveEmployeeState, type EmployeeState } from './employeeStateMachine'
import { workspaceAreaMap, type WorkspaceAreaId } from './sceneLayout'
import { taskWorkspaceArea } from './taskAreaMapping'

export interface WorkspaceEmployee {
  employee: Employee
  id: string
  characterIndex: number
  name: string
  role: string
  state: EmployeeState
  stateLabel: string
  stateDetail: string
  areaId: WorkspaceAreaId
  areaName: string
  currentTask?: Task
  currentTaskName: string
  currentPhase: string
  runningSeconds: number
  lastAction: string
  lastActiveAt: string | null
  needHuman: boolean
  hasError: boolean
}

const COMPLETION_EVENT_TYPES = new Set(['TASK_SUCCEEDED'])
const ERROR_EVENT_TYPES = new Set(['TASK_FAILED'])

function timestamp(value: string | null | undefined): number {
  if (!value) return 0
  const normalized = /[zZ]|[+-]\d{2}:?\d{2}$/.test(value) ? value : `${value}Z`
  return new Date(normalized).getTime()
}

export const currentEmployeeTask = employeeCurrentTask

export function adaptWorkspaceEmployees(
  employees: Employee[],
  tasks: Task[],
  events: AstraEvent[],
  now = Date.now(),
): WorkspaceEmployee[] {
  const characterIndices = assignEmployeeCharacterIndices(employees.map((employee) => employee.id))
  const latestEvents = new Map<string, AstraEvent>()
  for (const event of events) {
    if (!event.employee_id) continue
    const existing = latestEvents.get(event.employee_id)
    if (!existing || timestamp(event.created_at) > timestamp(existing.created_at)) latestEvents.set(event.employee_id, event)
  }

  return employees.map((employee) => {
    const currentTask = currentEmployeeTask(employee.id, tasks)
    const latestEvent = latestEvents.get(employee.id)
    const recentlyCompleted = Boolean(
      latestEvent
      && COMPLETION_EVENT_TYPES.has(latestEvent.event_type)
      && now - timestamp(latestEvent.created_at) < 12_000,
    )
    const recentlyErrored = Boolean(
      latestEvent
      && ERROR_EVENT_TYPES.has(latestEvent.event_type)
      && now - timestamp(latestEvent.created_at) < 12_000,
    )
    const areaId = taskWorkspaceArea(currentTask, employee)
    const state: EmployeeState = recentlyErrored ? 'ERROR' : resolveEmployeeState(employee, currentTask, recentlyCompleted)
    const presentation = EMPLOYEE_STATE_PRESENTATION[state]
    const areaName = workspaceAreaMap.get(areaId)?.name ?? '开发办公区'
    const startedAt = timestamp(currentTask?.started_at || currentTask?.claimed_at)
    const lastAction = platformCopy(latestEvent?.message) || platformCopy(currentTask?.current_progress) || presentation.detail
    return {
      employee,
      id: employee.id,
      characterIndex: characterIndices.get(employee.id) ?? 0,
      name: employeeDisplayName(employee.name),
      role: employee.role,
      state,
      stateLabel: presentation.label,
      stateDetail: platformCopy(currentTask?.current_progress) || presentation.detail,
      areaId,
      areaName,
      currentTask,
      currentTaskName: currentTask?.title ?? '暂无当前任务',
      currentPhase: latestEvent?.phase || (currentTask ? '任务执行' : '等待分配'),
      runningSeconds: startedAt ? Math.max(0, Math.floor((now - startedAt) / 1000)) : 0,
      lastAction,
      lastActiveAt: currentTask?.last_activity_at ?? latestEvent?.created_at ?? employee.last_heartbeat ?? employee.updated_at,
      needHuman: state === 'NEED_HUMAN',
      hasError: state === 'ERROR',
    }
  })
}

export function workspaceEmployeeMatches(employee: WorkspaceEmployee, query: string): boolean {
  const normalized = query.trim().toLowerCase()
  if (!normalized) return true
  return `${employee.name} ${employee.employee.name} ${employee.id} ${employee.role} ${employee.currentTaskName}`.toLowerCase().includes(normalized)
}

