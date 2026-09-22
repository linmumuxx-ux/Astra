<template>
  <Teleport to="body">
    <div v-if="open" class="modal-backdrop" :data-testid="testid" @click.self="onBackdrop">
      <section
        class="modal-card astra-dialog"
        :class="cardClass"
        role="dialog"
        aria-modal="true"
        :aria-label="ariaLabel || title"
        :style="width ? { width } : undefined"
      >
        <header>
          <div>
            <small v-if="eyebrow">{{ eyebrow }}</small>
            <h3>{{ title }}</h3>
            <p v-if="subtitle" class="astra-dialog__subtitle">{{ subtitle }}</p>
          </div>
          <button type="button" aria-label="关闭" :disabled="busy" @click="requestClose"><X :size="18" /></button>
        </header>
        <div class="modal-body astra-dialog__body">
          <slot />
        </div>
        <footer v-if="$slots.footer" class="astra-dialog__footer">
          <slot name="footer" />
        </footer>
      </section>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { X } from 'lucide-vue-next'
import { onBeforeUnmount, watch } from 'vue'
import { acquireOverlayLock, releaseOverlayLock } from '@/composables/useOverlayLock'

// Form/config/settings dialogs default to a non-dismissible overlay and ESC so a
// stray click can never discard typed input. View-only dialogs can opt in with
// dismissible, and the two dismissal paths always share the same rule.
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
  { dismissible: false, busy: false },
)

const emit = defineEmits<{ close: [] }>()

function onBackdrop(): void {
  if (props.dismissible && !props.busy) emit('close')
}

function onKeydown(event: KeyboardEvent): void {
  if (event.key === 'Escape' && props.open && props.dismissible && !props.busy) emit('close')
}

function requestClose(): void {
  if (!props.busy) emit('close')
}

let locked = false
watch(
  () => props.open,
  (open) => {
    if (open && !locked) {
      acquireOverlayLock()
      locked = true
    } else if (!open && locked) {
      releaseOverlayLock()
      locked = false
    }
  },
  { immediate: true },
)

if (typeof window !== 'undefined') window.addEventListener('keydown', onKeydown)
onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKeydown)
  if (locked) releaseOverlayLock()
})
</script>

<style scoped>
.astra-dialog__subtitle { margin: 5px 0 0; color: var(--astra-text-muted); font-size: var(--astra-font-body); }
.astra-dialog__body { display: grid; gap: 14px; }
.astra-dialog__footer { display: flex; flex: none; justify-content: flex-end; gap: 10px; margin-top: 16px; }
</style>