import type { RuntimeStatusProjection } from '@/features/runtime/status'
import {
  RUNTIME_STATUS_RANK,
  isFailureRuntimeState,
  isTerminalRuntimeState,
  runtimeStatusMeta,
  type RuntimeState,
  type RuntimeStatusMeta,
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

/** @deprecated Use RuntimeStatusMeta. */
export type RunStatusMeta = RuntimeStatusMeta

/** @deprecated Use isTerminalRuntimeState. */
export const isTerminalRun = isTerminalRuntimeState

/** @deprecated Use isFailureRuntimeState. */
export const isFailedRun = isFailureRuntimeState

/** @deprecated Use runtimeStatusMeta. */
export function runUnifiedStatus(run: RuntimeStatusProjection): RuntimeStatusMeta {
  return runtimeStatusMeta(run)
}

/** @deprecated Use RUNTIME_STATUS_RANK. */
export const RUN_LEVEL_RANK: Partial<Record<RunLevelStatus, number>> = RUNTIME_STATUS_RANK
