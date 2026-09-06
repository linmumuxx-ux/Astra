import type { Employee, Task } from '@/api/types'
import {
  workspaceAreaMap,
  workspaceAreas,
  type WorkspaceAreaId,
} from '@/features/workspace/sceneLayout'
import { taskWorkspaceArea } from '@/features/workspace/taskAreaMapping'
import { employeeDisplayName, platformCopy } from '@/utils/format'

export { workspaceAreas, type WorkspaceAreaId } from '@/features/workspace/sceneLayout'

export interface EmployeeViewModel {
  employee: Employee
  id: string
  name: string
  role: string
  status: string
  statusText: string
  areaId: WorkspaceAreaId
  areaName: string
  currentTask?: Task
  currentTaskName: string
  statusTextLong: string
  needHelp: boolean
  lastActiveAt: string | null
}

const STATUS_COPY: Record<string, string> = {
  IDLE: '空闲',
  WORKING: '工作中',
  WAIT_HUMAN: '需要人工处理',
  PAUSED: '已暂停',
  ERROR: '异常',
  OFFLINE: '离线',
}

const STATUS_DETAIL: Record<string, string> = {
  IDLE: '等待新任务',
  WORKING: '正在推进当前任务',
  WAIT_HUMAN: '遇到问题，等待人工协助',
  PAUSED: '已暂停接收新任务',
  ERROR: '执行异常，工作现场已保留',
  OFFLINE: '当前不可用',
}

const activeTaskStatuses = new Set(['READY', 'ASSIGNED', 'QUEUED', 'RUNNING', 'WAIT_HUMAN', 'SUSPENDED', 'EXECUTION_ERROR'])

export function employeeCurrentTask(employeeId: string, tasks: Task[]): Task | undefined {
  const statusPriority: Record<string, number> = { WAIT_HUMAN: 0, EXECUTION_ERROR: 0, RUNNING: 0, QUEUED: 1, SUSPENDED: 2, ASSIGNED: 3, READY: 4 }
  return tasks
    .filter((task) => task.employee_id === employeeId && activeTaskStatuses.has(task.status))
    .sort((left, right) => (statusPriority[left.status] ?? 3) - (statusPriority[right.status] ?? 3) || right.updated_at.localeCompare(left.updated_at))[0]
}

export function employeeAreaId(employee: Employee, task?: Task): WorkspaceAreaId {
  return taskWorkspaceArea(task, employee)
}

export function toEmployeeViewModel(employee: Employee, tasks: Task[]): EmployeeViewModel {
  const currentTask = employeeCurrentTask(employee.id, tasks)
  const areaId = employeeAreaId(employee, currentTask)
  const area = workspaceAreaMap.get(areaId) ?? workspaceAreas[0]
  const statusTextLong = platformCopy(currentTask?.current_progress) || STATUS_DETAIL[employee.status] || '状态等待更新'
  return {
    employee,
    id: employee.id,
    name: employeeDisplayName(employee.name),
    role: employee.role,
    status: employee.status,
    statusText: STATUS_COPY[employee.status] ?? '状态未知',
    areaId,
    areaName: area.name,
    currentTask,
    currentTaskName: currentTask?.title ?? '暂无当前任务',
    statusTextLong,
    needHelp: employee.status === 'WAIT_HUMAN' || currentTask?.status === 'WAIT_HUMAN',
    lastActiveAt: currentTask?.last_activity_at ?? employee.last_heartbeat ?? employee.updated_at,
  }
}

export function employeeMatches(employee: EmployeeViewModel, query: string): boolean {
  const normalized = query.trim().toLocaleLowerCase('zh-CN')
  if (!normalized) return true
  return `${employee.name} ${employee.id} ${employee.role} ${employee.currentTaskName}`.toLocaleLowerCase('zh-CN').includes(normalized)
}
