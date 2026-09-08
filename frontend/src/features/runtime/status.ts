export type RuntimeState =
  | 'READY'
  | 'ASSIGNED'
  | 'QUEUED'
  | 'STARTING'
  | 'RUNNING'
  | 'WAITING_INPUT'
  | 'SUSPENDED'
  | 'PENDING_CONFIRMATION'
  | 'COMPLETED'
  | 'FAILED'
  | 'EXECUTION_ERROR'
  | 'TIMEOUT'
  | 'LOST'
  | 'CANCELLED'
  | 'IDLE'
  | 'OFFLINE'
  | 'PAUSED'
  | 'ERROR'
  | 'UNKNOWN'

export type RuntimeTone = 'info' | 'success' | 'warning' | 'danger' | 'neutral'
export type RuntimeStatusFilter = RuntimeState | 'ABNORMAL' | ''

export interface RuntimeStatusProjection {
  runtime_state: string
  runtime_status_label: string
  runtime_detail: string
}

export interface RuntimeStatusMeta {
  state: RuntimeState
  label: string
  detail: string | null
  tone: RuntimeTone
  pulse: boolean
}

/**
 * Fallback only. Runtime objects should display runtime_status_label returned by
 * backend/app/runtime/presentation.py. Keep these strings aligned with that contract.
 */
const RUNTIME_FALLBACK_LABELS: Record<RuntimeState, string> = {
  READY: '等待领取',
  ASSIGNED: '已分配',
  QUEUED: '等待执行',
  STARTING: '启动中',
  RUNNING: '执行中',
  WAITING_INPUT: '等待人工输入',
  SUSPENDED: '已暂停',
  PENDING_CONFIRMATION: '等待确认',
  COMPLETED: '已完成',
  FAILED: '执行失败',
  EXECUTION_ERROR: '执行异常',
  TIMEOUT: '执行超时',
  LOST: '运行丢失',
  CANCELLED: '已取消',
  IDLE: '空闲',
  OFFLINE: '离线',
  PAUSED: '已暂停',
  ERROR: '异常',
  UNKNOWN: '状态待校正',
}

const RUNTIME_TONES: Record<RuntimeState, RuntimeTone> = {
  READY: 'neutral',
  ASSIGNED: 'warning',
  QUEUED: 'warning',
  STARTING: 'info',
  RUNNING: 'info',
  WAITING_INPUT: 'warning',
  SUSPENDED: 'warning',
  PENDING_CONFIRMATION: 'warning',
  COMPLETED: 'success',
  FAILED: 'danger',
  EXECUTION_ERROR: 'danger',
  TIMEOUT: 'danger',
  LOST: 'danger',
  CANCELLED: 'neutral',
  IDLE: 'neutral',
  OFFLINE: 'neutral',
  PAUSED: 'warning',
  ERROR: 'danger',
  UNKNOWN: 'danger',
}

export const RUNTIME_ACTIVE_STATES = new Set<RuntimeState>(['QUEUED', 'STARTING', 'RUNNING', 'WAITING_INPUT'])
export const RUNTIME_TERMINAL_STATES = new Set<RuntimeState>(['COMPLETED', 'FAILED', 'EXECUTION_ERROR', 'TIMEOUT', 'LOST', 'CANCELLED'])
export const RUNTIME_FAILURE_STATES = new Set<RuntimeState>(['FAILED', 'EXECUTION_ERROR', 'TIMEOUT', 'LOST', 'ERROR', 'UNKNOWN'])
export const RUNTIME_ABNORMAL_STATES = new Set<RuntimeState>(['FAILED', 'EXECUTION_ERROR', 'TIMEOUT', 'LOST', 'UNKNOWN'])

export const TASK_RUNTIME_FILTER_STATES: RuntimeState[] = [
  'READY',
  'ASSIGNED',
  'QUEUED',
  'STARTING',
  'RUNNING',
  'WAITING_INPUT',
  'SUSPENDED',
  'PENDING_CONFIRMATION',
  'COMPLETED',
  'FAILED',
  'EXECUTION_ERROR',
  'TIMEOUT',
  'LOST',
  'CANCELLED',
  'UNKNOWN',
]

export const RUN_RUNTIME_FILTER_STATES: RuntimeState[] = [
  'QUEUED',
  'STARTING',
  'RUNNING',
  'WAITING_INPUT',
  'SUSPENDED',
  'COMPLETED',
  'FAILED',
  'TIMEOUT',
  'LOST',
  'CANCELLED',
]

export const RUNTIME_STATUS_RANK: Partial<Record<RuntimeState, number>> = {
  READY: 0,
  ASSIGNED: 1,
  QUEUED: 2,
  STARTING: 3,
  RUNNING: 4,
  WAITING_INPUT: 5,
  SUSPENDED: 6,
  PENDING_CONFIRMATION: 7,
  COMPLETED: 8,
  CANCELLED: 9,
  FAILED: 10,
  EXECUTION_ERROR: 10,
  TIMEOUT: 10,
  LOST: 10,
  UNKNOWN: 11,
}

const knownStates = new Set<RuntimeState>(Object.keys(RUNTIME_FALLBACK_LABELS) as RuntimeState[])

export function runtimeState(value: string | null | undefined): RuntimeState {
  return knownStates.has(value as RuntimeState) ? value as RuntimeState : 'UNKNOWN'
}

export function runtimeStatusLabel(state: string | null | undefined, backendLabel?: string | null): string {
  const label = backendLabel?.trim()
  if (label) return label
  return RUNTIME_FALLBACK_LABELS[runtimeState(state)]
}

export function runtimeStatusTone(state: string | null | undefined): RuntimeTone {
  return RUNTIME_TONES[runtimeState(state)]
}

export function isActiveRuntimeState(state: string | null | undefined): boolean {
  return RUNTIME_ACTIVE_STATES.has(runtimeState(state))
}

export function isTerminalRuntimeState(state: string | null | undefined): boolean {
  return RUNTIME_TERMINAL_STATES.has(runtimeState(state))
}

export function isFailureRuntimeState(state: string | null | undefined): boolean {
  return RUNTIME_FAILURE_STATES.has(runtimeState(state))
}

export function isAbnormalRuntimeState(state: string | null | undefined): boolean {
  return RUNTIME_ABNORMAL_STATES.has(runtimeState(state))
}

export function runtimeStatusMatchesFilter(state: string | null | undefined, filter: RuntimeStatusFilter): boolean {
  if (!filter) return true
  if (filter === 'ABNORMAL') return isAbnormalRuntimeState(state)
  return runtimeState(state) === filter
}

export function runtimeStatusMeta(projection: RuntimeStatusProjection): RuntimeStatusMeta {
  const state = runtimeState(projection.runtime_state)
  return {
    state,
    label: runtimeStatusLabel(state, projection.runtime_status_label),
    detail: projection.runtime_detail?.trim() || null,
    tone: runtimeStatusTone(state),
    pulse: ['QUEUED', 'STARTING', 'RUNNING'].includes(state),
  }
}
