<template>
  <ElDialog
    v-if="open"
    :data-testid="testid"
    :model-value="true"
    :class="cardClass"
    :title="ariaLabel || title"
    :width="width"
    :close-on-click-modal="dismissible"
    :close-on-press-escape="dismissible"
    :before-close="requestClose"
  >
    <template #header>
      <small v-if="eyebrow">{{ eyebrow }}</small>
      <h3 class="astra-dialog__title">{{ title }}</h3>
      <p v-if="subtitle" class="astra-dialog__subtitle">{{ subtitle }}</p>
    </template>
    <div class="astra-dialog__body">
      <slot />
    </div>
    <template v-if="$slots.footer" #footer>
      <div class="astra-dialog__footer">
        <slot name="footer" />
      </div>
    </template>
  </ElDialog>
</template>

<script setup lang="ts">
import { ElDialog } from 'element-plus'

// Form/config/settings dialogs default to a non-dismissible overlay and ESC so a
// stray click can never discard typed input. View-only dialogs can opt in with
// dismissible, and the two dismissal paths always share the same rule.
// The close paths (overlay, ESC, header close button) all funnel into
// before-close, which only requests a close from the parent; done() is never
// called, so the dialog unmounts exactly when the `open` prop flips to false.
const props = withDefaults(
  defineProps<{
    open: boolean
    title: string
    subtitle?: string
    eyebrow?: string
    ariaLabel?: string
    dismissible?: boolean
    busy?: boolean
    testid?: string
    width?: string
    cardClass?: string
  }>(),
  { dismissible: false, busy: false, width: 'min(620px, 100%)' },
)

const emit = defineEmits<{ close: [] }>()

function requestClose(): void {
  if (!props.busy) emit('close')
}
</script>

<style scoped>
.astra-dialog__title { margin: 0; font-size: var(--astra-font-section); line-height: normal; }
.astra-dialog__subtitle { margin: 5px 0 0; color: var(--astra-text-muted); font-size: var(--astra-font-body); }
.astra-dialog__body { display: grid; gap: 14px; }
.astra-dialog__footer { display: flex; justify-content: flex-end; gap: 10px; }
</style>
