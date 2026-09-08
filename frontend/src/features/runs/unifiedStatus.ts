import type { RuntimeStatusProjection } from '@/features/runtime/status'
import {
  RUNTIME_STATUS_RANK,
  isFailureRuntimeState,
  isTerminalRuntimeState,
  runtimeStatusMeta,
  type RuntimeState,
  type RuntimeTone,
} from '@/features/runtime/status'

/** @deprecated Use RuntimeState and helpers from @/features/runtime/status. */
export type RunLevelStatus = Extract<RuntimeState,
  | 'QUEUED'
  | 'STARTING'
  | 'RUNNING'
  | 'WAITING_INPUT'
  | 'SUSPENDED'
  | 'TIMEOUT'
  | 'LOST'
  | 'COMPLETED'
  | 'FAILED'
  | 'CANCELLED'
>

/** @deprecated Use RuntimeTone. */
export type RunTone = RuntimeTone

/** @deprecated Use RuntimeStatusMeta from @/features/runtime/status. */
export interface RunStatusMeta {
  level: RunLevelStatus
  label: string
  tone: RunTone
  detail: string | null
}

/** @deprecated Use isTerminalRuntimeState. */
export function isTerminalRun(value: string): boolean { return isTerminalRuntimeState(value) }

/** @deprecated Use isFailureRuntimeState. */
export function isFailedRun(value: string): boolean { return isFailureRuntimeState(value) }

/** @deprecated Use runtimeStatusMeta. */
export function runUnifiedStatus(run: RuntimeStatusProjection): RunStatusMeta {
  const meta = runtimeStatusMeta(run)
  return { level: meta.state as RunLevelStatus, label: meta.label, tone: meta.tone, detail: meta.detail }
}

/** @deprecated Use RUNTIME_STATUS_RANK. */
export const RUN_LEVEL_RANK = RUNTIME_STATUS_RANK as Partial<Record<RunLevelStatus, number>>
