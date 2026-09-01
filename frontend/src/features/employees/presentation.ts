import type { Employee, Task } from '@/api/types'
import {
  isWorkspaceAreaId,
  workspaceAreaMap,
  workspaceAreas,
  type WorkspaceAreaId,
} from '@/features/workspace/sceneLayout'
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

const activeTaskStatuses = new Set(['READY', 'RUNNING', 'WAIT_HUMAN', 'SUSPENDED', 'EXECUTION_ERROR'])

export function employeeCurrentTask(employeeId: string, tasks: Task[]): Task | undefined {
  const statusPriority: Record<string, number> = { WAIT_HUMAN: 0, EXECUTION_ERROR: 0, RUNNING: 0, SUSPENDED: 1, READY: 2 }
  return tasks
    .filter((task) => task.employee_id === employeeId && activeTaskStatuses.has(task.status))
    .sort((left, right) => (statusPriority[left.status] ?? 3) - (statusPriority[right.status] ?? 3) || right.updated_at.localeCompare(left.updated_at))[0]
}

export function employeeAreaId(employee: Employee, task?: Task): WorkspaceAreaId {
  const taskText = `${task?.title ?? ''}${task?.current_progress ?? ''}`
  if (task && /(会议|评审会|复盘会|汇报会)/u.test(taskText)) return 'meeting'
  if (task && /(协作|讨论|联合分析|方案评审)/u.test(taskText)) return 'collaboration'
  if (task && /(自动化|集成|接口|流水线|部署)/u.test(taskText)) return 'integration'
  if (task && /(专项|排查|修复|应急|故障)/u.test(taskText)) return 'special'
  if (isWorkspaceAreaId(employee.default_work_area)) return employee.default_work_area

  const responsibility = `${employee.role}${employee.description}`
  if (/(自动化|集成|接口|流水线|部署)/u.test(responsibility)) return 'integration'
  if (/(协作|产品|管理|运营|治理|分析)/u.test(responsibility)) return 'collaboration'
  if (/(专项|排查|修复|应急|防线)/u.test(responsibility)) return 'special'
  return 'development'
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
