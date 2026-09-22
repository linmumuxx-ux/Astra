import { ref, type Ref } from 'vue'

export type ToastKind = 'success' | 'error' | 'info'

export interface ToastItem {
  id: number
  message: string
  kind: ToastKind
}

const items = ref<ToastItem[]>([])
let sequence = 0

// Single application-wide toast channel. Business code calls notify() instead of
// window.alert so feedback stays inside the Astra UI system.
export function notify(message: string, kind: ToastKind = 'success', duration = 2600): number {
  const id = ++sequence
  items.value = [...items.value, { id, message, kind }]
  window.setTimeout(() => dismissToast(id), duration)
  return id
}

export function dismissToast(id: number): void {
  items.value = items.value.filter((item) => item.id !== id)
}

export function useToasts(): Ref<ToastItem[]> {
  return items
}