const STATUS_LABEL: Record<string, string> = {
  OFFLINE: '离线', IDLE: '空闲', WORKING: '工作中', WAIT_HUMAN: '等待人工', PAUSED: '已暂停', ERROR: '异常',
  READY: '待领取', RUNNING: '处理中', SUSPENDED: '已挂起', PENDING_CONFIRMATION: '待确认', EXECUTION_ERROR: '执行异常', COMPLETED: '已完成', FAILED: '未完成', CANCELLED: '已取消',
  PASSED: '完成', BLOCKED: '阻塞',
  AVAILABLE: '正常', CHECKING: '检查中', UNAVAILABLE: '不可用', UNKNOWN: '未检查',
}

export const statusLabel = (value: string) => STATUS_LABEL[value] ?? '未知状态'
export const taskTypeLabel = (value: string) => value === 'ISSUE' ? '问题' : value === 'REQUIREMENT' ? '需求' : '未知类型'
export const priorityLabel = (value: string) => ({ VERY_HIGH: '很高', HIGH: '高', MEDIUM: '中', LOW: '低' }[value] ?? '未设置')
export const acceptanceStatusLabel = (value: string) => ({ SATISFIED: '满足', UNSATISFIED: '未满足', UNCONFIRMED: '无法确认' }[value] ?? '无法确认')

export function statusTone(status: string): 'info' | 'success' | 'warning' | 'danger' | 'neutral' {
  if (['COMPLETED', 'PASSED', 'IDLE', 'AVAILABLE'].includes(status)) return 'success'
  if (['WAIT_HUMAN', 'SUSPENDED', 'PENDING_CONFIRMATION', 'PAUSED', 'BLOCKED'].includes(status)) return 'warning'
  if (['FAILED', 'EXECUTION_ERROR', 'ERROR', 'CANCELLED', 'OFFLINE', 'UNAVAILABLE'].includes(status)) return 'danger'
  if (['RUNNING', 'WORKING', 'CHECKING'].includes(status)) return 'info'
  return 'neutral'
}

const parseApiTime = (value: string) => new Date(/[zZ]|[+-]\d{2}:?\d{2}$/.test(value) ? value : `${value}Z`)

export const formatTime = (value: string | null | undefined) =>
  value ? new Intl.DateTimeFormat('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }).format(parseApiTime(value)) : '—'

export const formatDuration = (from: string | null, to?: string | null) => {
  if (!from) return '—'
  const milliseconds = (to ? parseApiTime(to) : new Date()).getTime() - parseApiTime(from).getTime()
  const minutes = Math.max(0, Math.floor(milliseconds / 60_000))
  if (minutes === 0) return '不足 1 分钟'
  if (minutes < 60) return `${minutes} 分钟`
  const remainingMinutes = minutes % 60
  return `${Math.floor(minutes / 60)} 小时${remainingMinutes ? ` ${remainingMinutes} 分钟` : ''}`
}

export const formatTaskDuration = (task: { status: string; started_at: string | null; finished_at: string | null; last_activity_at: string | null }) =>
  formatDuration(task.started_at, task.finished_at ?? (task.status === 'RUNNING' ? undefined : task.last_activity_at))

export const formatTokens = (value: number | null | undefined) => {
  if (value === null || value === undefined) return '—'
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(value >= 10_000_000 ? 0 : 2)}M`
  if (value >= 1_000) return `${(value / 1_000).toFixed(1)}K`
  return String(value)
}

export const formatDurationSeconds = (seconds: number | null | undefined) => {
  if (seconds === null || seconds === undefined) return '—'
  const minutes = Math.floor(seconds / 60)
  if (minutes === 0) return '不足 1 分钟'
  if (minutes < 60) return `${minutes} 分钟`
  const remainingMinutes = minutes % 60
  return `${Math.floor(minutes / 60)} 小时${remainingMinutes ? ` ${remainingMinutes} 分钟` : ''}`
}

export const formatMilliseconds = (milliseconds: number | null | undefined) => {
  if (milliseconds === null || milliseconds === undefined) return '—'
  return milliseconds < 1000 ? `${milliseconds} 毫秒` : `${(milliseconds / 1000).toFixed(1)} 秒`
}

export const environmentLabel = (snapshot: { mode?: unknown; name?: unknown; host?: unknown } | null | undefined) => {
  if (!snapshot) return '未配置'
  return snapshot.mode === 'LINUX_REMOTE' ? `Linux · ${snapshot.name ?? snapshot.host ?? '远程'}` : '本地'
}

export const executionModeLabel = (value: unknown) =>
  value === 'LINUX_REMOTE' ? 'Linux 远程' : value === 'LOCAL' ? '本地' : '—'

export const executorLabel = (value: string) =>
  value === 'opencode_ssh' ? 'Linux 远程 OpenCode' : value === 'opencode_cli' ? '本地 OpenCode' : '未知执行方式'

export const sourceLabel = (source: string) => source === 'nr_test_system' ? 'nr_test_system' : source === 'manual' ? '手工创建' : '其他来源'

export const evidenceKindLabel = (value: string) =>
  value === 'work_record' ? 'OpenCode 工作记录' : value === 'log' ? '运行日志' : value === 'attachment' ? '结果附件' : '其他证据'
