import type { DashboardActivityItem, DashboardEmployee, DashboardEmployees } from '@/api/types'
import { employeeDisplayName } from '@/utils/format'

export type OfficeStatus = 'idle' | 'working' | 'thinking' | 'waiting' | 'attention' | 'error' | 'offline' | 'disabled'

/** 首页展示契约。场景组件不接收 Task / Session 等执行模型。 */
export interface OfficeEmployee {
  id: string
  name: string
  role: string
  teamId: string
  teamName: string
  status: OfficeStatus
  statusLabel: string
  availability: 'online' | 'offline' | 'disabled' | 'error' | 'unknown'
  availabilityLabel: string
  currentAction: string
  taskTitle: string | null
  taskId: string | null
  target: string
  employeeTarget: string
  taskLinkLabel: string
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
  repeatCount: number
}

function officeStatus(employee: DashboardEmployee): OfficeStatus {
  const task = employee.current_task
  if (!employee.enabled) return 'disabled'
  if (employee.status === 'OFFLINE') return 'offline'
  if (employee.state === 'error') return 'error'
  // 人工等待优先于员工工作状态；普通暂停、外部等待与连接待确认保持静止。
  if (task?.status === 'WAITING' && (task.human_required_reason || employee.status === 'WAIT_HUMAN')) return 'attention'
  if (employee.state === 'waiting') return 'waiting'
  if (employee.state === 'working' && task?.session_status === 'RUNNING' && task.runtime_connection === 'CONNECTED') return 'working'
  return 'idle'
}

export function presentOfficeEmployees(data: DashboardEmployees | null): OfficeEmployee[] {
  const teams = data?.teams ?? []
  return teams.flatMap(team => team.employees.map(employee => {
    const status = officeStatus(employee)
    const task = employee.current_task
    const availability = !employee.enabled ? 'disabled' : employee.status === 'OFFLINE' ? 'offline'
      : employee.status === 'ERROR' ? 'error'
      : ['IDLE', 'WORKING', 'WAIT_HUMAN', 'PAUSED'].includes(employee.status) ? 'online' : 'unknown'
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
      availability,
      availabilityLabel: { online: '在线', offline: '离线', disabled: '已停用', error: '异常', unknown: '状态待确认' }[availability],
      currentAction,
      taskTitle: task?.title ?? null,
      taskId: task?.id ?? null,
      target: task ? `/tasks/${encodeURIComponent(task.id)}` : `/employees/${encodeURIComponent(employee.id)}`,
      employeeTarget: `/employees/${encodeURIComponent(employee.id)}`,
      taskLinkLabel: task?.current_session_id && task.session_status ? '进入会话' : '查看任务',
      characterIndex: employee.character_id,
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
    repeatCount: 1,
  }
}

/** 只合并相邻的相同事件，不跨越执行结果或其他员工的进展。 */
export function presentOfficeEvents(items: DashboardActivityItem[]): OfficeEvent[] {
  const events: OfficeEvent[] = []
  for (const item of items) {
    const event = presentOfficeEvent(item)
    const previous = events.at(-1)
    if (previous && previous.employeeId === event.employeeId && previous.employeeName === event.employeeName
      && previous.kind === event.kind && previous.target === event.target && previous.description === event.description) {
      previous.repeatCount += 1
    } else events.push(event)
  }
  return events
}

export function parseOfficeTime(value: string): Date {
  return new Date(/[zZ]|[+-]\d{2}:?\d{2}$/.test(value) ? value : `${value}Z`)
}

export function officeClock(value: string): string {
  return parseOfficeTime(value).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', hour12: false })
}
