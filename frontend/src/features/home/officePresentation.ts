import type { DashboardActivityItem, DashboardEmployee, DashboardEmployees } from '@/api/types'
import { employeeDisplayName } from '@/utils/format'

export type OfficeStatus = 'idle' | 'working' | 'thinking' | 'waiting' | 'attention' | 'error'

/** 首页展示契约。场景组件不接收 Task / Session 等执行模型。 */
export interface OfficeEmployee {
  id: string
  name: string
  role: string
  teamId: string
  teamName: string
  status: OfficeStatus
  statusLabel: string
  currentAction: string
  taskTitle: string | null
  taskId: string | null
  target: string
  characterIndex: number
}

export interface OfficeEvent {
  id: number
  employeeId: string | null
  employeeName: string
  kind: DashboardActivityItem['kind']
  description: string
  occurredAt: string
  target: string | null
}

function officeStatus(employee: DashboardEmployee): OfficeStatus {
  const task = employee.current_task
  // 人工等待优先于员工工作状态；普通暂停、外部等待与连接待确认保持静止。
  if (task?.status === 'WAITING' && (task.human_required_reason || employee.status === 'WAIT_HUMAN')) return 'attention'
  if (employee.state === 'error') return 'error'
  if (employee.state === 'waiting') return 'waiting'
  if (employee.state === 'working' && task?.session_status === 'RUNNING' && task.runtime_connection === 'CONNECTED') return 'working'
  return 'idle'
}

export function presentOfficeEmployees(data: DashboardEmployees | null): OfficeEmployee[] {
  const teams = data?.teams ?? []
  return teams.flatMap(team => team.employees.map(employee => {
    const status = officeStatus(employee)
    const task = employee.current_task
    const currentAction = status === 'attention' ? '等待你的确认'
      : status === 'working' ? `正在处理：${task!.title}`.slice(0, 80)
      : employee.state_label
    return {
      id: employee.id,
      name: employeeDisplayName(employee.name),
      role: employee.role,
      teamId: team.id,
      teamName: team.name,
      status,
      statusLabel: employee.state_label,
      currentAction,
      taskTitle: task?.title ?? null,
      taskId: task?.id ?? null,
      target: task ? `/tasks/${encodeURIComponent(task.id)}` : `/employees/${encodeURIComponent(employee.id)}`,
      characterIndex: [...employee.id].reduce((value, character) => (value * 31 + character.charCodeAt(0)) >>> 0, 7) % 9,
    }
  }))
}

export function presentOfficeEvent(item: DashboardActivityItem): OfficeEvent {
  return {
    id: item.id,
    employeeId: item.employee_id,
    employeeName: employeeDisplayName(item.employee_name),
    kind: item.kind,
    description: item.description,
    occurredAt: item.created_at,
    target: item.target_id && item.target_type
      ? `/${item.target_type === 'task' ? 'tasks' : 'employees'}/${encodeURIComponent(item.target_id)}` : null,
  }
}

export function parseOfficeTime(value: string): Date {
  return new Date(/[zZ]|[+-]\d{2}:?\d{2}$/.test(value) ? value : `${value}Z`)
}

export function officeClock(value: string): string {
  return parseOfficeTime(value).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', hour12: false })
}
