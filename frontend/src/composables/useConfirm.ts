import { ElMessageBox } from 'element-plus'
import { ref, type Ref } from 'vue'

export interface ConfirmOptions {
  title: string
  message?: string
  confirmLabel?: string
  cancelLabel?: string
  danger?: boolean
}

interface ConfirmState extends ConfirmOptions {
  resolve: (value: boolean) => void
}

// Compatibility state for the old host component. The live application no
// longer mounts that host; confirmation rendering is owned by Element Plus.
const legacyState = ref<ConfirmState | null>(null)

export async function confirmDialog(options: ConfirmOptions): Promise<boolean> {
  try {
    await ElMessageBox.confirm(options.message ?? '', options.title, {
      confirmButtonText: options.confirmLabel ?? '确认',
      cancelButtonText: options.cancelLabel ?? '取消',
      closeOnClickModal: false,
      closeOnPressEscape: false,
      showClose: false,
      lockScroll: true,
      distinguishCancelAndClose: false,
      confirmButtonClass: options.danger ? 'astra-confirm-danger' : '',
      type: options.danger ? 'warning' : 'info',
    })
    return true
  } catch {
    return false
  }
}

export function resolveConfirm(value: boolean): void {
  const current = legacyState.value
  legacyState.value = null
  current?.resolve(value)
}

export function useConfirmState(): Ref<ConfirmState | null> {
  return legacyState
}
