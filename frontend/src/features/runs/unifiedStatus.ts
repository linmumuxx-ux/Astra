import { statusTone } from '@/utils/format'

export type RunLevelStatus = 'QUEUED' | 'STARTING' | 'RUNNING' | 'WAITING_INPUT' | 'SUSPENDED' | 'TIMEOUT' | 'LOST' | 'COMPLETED' | 'FAILED' | 'CANCELLED'

export type RunTone = 'info' | 'success' | 'warning' | 'danger' | 'neutral'

export interface RunStatusMeta {
  level: RunLevelStatus
  label: string
  tone: RunTone
  /** 异常/失败的具体原因，作为二级信息，不覆盖一级状态。 */
  detail: string | null
}

export function isTerminalRun(status: string): boolean {
  return ['COMPLETED', 'FAILED', 'TIMEOUT', 'LOST', 'CANCELLED', 'SUSPENDED'].includes(status)
}

export function isFailedRun(status: string): boolean {
  return ['FAILED', 'TIMEOUT', 'LOST'].includes(status)
}

export function runUnifiedStatus(run: { runtime_state: string; runtime_status_label: string; runtime_detail: string }): RunStatusMeta {
  const level = run.runtime_state as RunLevelStatus
  return { level, label: run.runtime_status_label, detail: run.runtime_detail || null, tone: statusTone(run.runtime_state) }
}

export const RUN_LEVEL_RANK: Record<RunLevelStatus, number> = {
  QUEUED: 0,
  STARTING: 1,
  RUNNING: 1,
  WAITING_INPUT: 2,
  SUSPENDED: 3,
  TIMEOUT: 6,
  LOST: 6,
  COMPLETED: 4,
  CANCELLED: 5,
  FAILED: 6,
}
