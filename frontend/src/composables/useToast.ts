import { ElMessage } from 'element-plus'
import { ref, type Ref } from 'vue'

export type ToastKind = 'success' | 'error' | 'info'

export interface ToastItem {
  id: number
  message: string
  kind: ToastKind
}

// Kept only as a source-compatible bridge for old callers/components while
// feedback rendering is owned by Element Plus.
const legacyItems = ref<ToastItem[]>([])
let sequence = 0

export function notify(message: string, kind: ToastKind = 'success', duration = 2600): number {
  const id = ++sequence
  ElMessage({
    message,
    type: kind,
    duration,
    showClose: kind === 'error',
    grouping: true,
  })
  return id
}

export function dismissToast(_id: number): void {
  // Element Plus owns message lifecycle; retained for compatibility until the
  // unused legacy toaster component is removed from the source tree.
}

export function useToasts(): Ref<ToastItem[]> {
  return legacyItems
}
