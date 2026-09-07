export type RunLevelStatus = 'WAITING' | 'EXECUTING' | 'WAITING_INPUT' | 'PAUSED' | 'COMPLETED' | 'FAILED' | 'CANCELLED'

export type RunTone = 'info' | 'success' | 'warning' | 'danger' | 'neutral'

export interface RunStatusMeta {
  level: RunLevelStatus
  label: string
  tone: RunTone
  /** 异常/失败的具体原因，作为二级信息，不覆盖一级状态。 */
  detail: string | null
}

const RUN_DETAIL: Record<string, string> = {
  FAILED: '执行失败',
  TIMEOUT: '执行超时',
  LOST: '运行丢失',
}

const META: Record<string, RunStatusMeta> = {
  QUEUED: { level: 'WAITING', label: '等待执行', tone: 'neutral', detail: null },
  STARTING: { level: 'EXECUTING', label: '执行中', tone: 'info', detail: '启动中' },
  RUNNING: { level: 'EXECUTING', label: '执行中', tone: 'info', detail: null },
  WAITING_INPUT: { level: 'WAITING_INPUT', label: '等待输入', tone: 'warning', detail: '等待人工输入' },
  SUSPENDED: { level: 'PAUSED', label: '已暂停', tone: 'warning', detail: null },
  COMPLETED: { level: 'COMPLETED', label: '已完成', tone: 'success', detail: null },
  PASSED: { level: 'COMPLETED', label: '已完成', tone: 'success', detail: null },
  FAILED: { level: 'FAILED', label: '执行失败', tone: 'danger', detail: RUN_DETAIL.FAILED },
  TIMEOUT: { level: 'FAILED', label: '执行失败', tone: 'danger', detail: RUN_DETAIL.TIMEOUT },
  LOST: { level: 'FAILED', label: '执行失败', tone: 'danger', detail: RUN_DETAIL.LOST },
  CANCELLED: { level: 'CANCELLED', label: '已取消', tone: 'neutral', detail: null },
}

export function isTerminalRun(status: string): boolean {
  return ['COMPLETED', 'PASSED', 'FAILED', 'TIMEOUT', 'LOST', 'CANCELLED', 'SUSPENDED'].includes(status)
}

export function isFailedRun(status: string): boolean {
  return ['FAILED', 'TIMEOUT', 'LOST'].includes(status)
}

export function runUnifiedStatus(status: string): RunStatusMeta {
  return META[status] ?? { level: 'EXECUTING', label: '执行中', tone: 'neutral', detail: null }
}

export const RUN_LEVEL_RANK: Record<RunLevelStatus, number> = {
  WAITING: 0,
  EXECUTING: 1,
  WAITING_INPUT: 2,
  PAUSED: 3,
  COMPLETED: 4,
  CANCELLED: 5,
  FAILED: 6,
}
