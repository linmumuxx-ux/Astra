<template>
  <Teleport to="body">
    <div class="astra-toaster" aria-live="polite">
      <TransitionGroup name="astra-toast">
        <div
          v-for="toast in items"
          :key="toast.id"
          class="astra-toast"
          :data-kind="toast.kind"
          :role="toast.kind === 'error' ? 'alert' : 'status'"
        >
          <CircleCheck v-if="toast.kind === 'success'" :size="15" />
          <TriangleAlert v-else-if="toast.kind === 'error'" :size="15" />
          <Info v-else :size="15" />
          <span>{{ toast.message }}</span>
          <button type="button" aria-label="关闭提示" @click="dismissToast(toast.id)"><X :size="13" /></button>
        </div>
      </TransitionGroup>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { CircleCheck, Info, TriangleAlert, X } from 'lucide-vue-next'
import { dismissToast, useToasts } from '@/composables/useToast'

// The only application-level feedback channel. Success/info are polite status
// messages; failures announce as alerts and never auto-hide the user's input.
const items = useToasts()
</script>

<style scoped>
.astra-toaster { position: fixed; z-index: 1500; right: 24px; bottom: 24px; display: grid; gap: 8px; max-width: min(420px, calc(100vw - 32px)); }
.astra-toast { display: flex; align-items: center; gap: 8px; padding: 11px 12px; color: var(--astra-text-primary); border: 1px solid var(--astra-border); border-left-width: 3px; border-radius: 10px; background: var(--astra-bg-panel); box-shadow: 0 14px 40px rgba(16,37,34,.2); font-size: var(--astra-font-body); }
.astra-toast > svg { flex: none; }
.astra-toast > span { flex: 1; line-height: 1.5; word-break: break-word; }
.astra-toast > button { display: grid; place-items: center; flex: none; width: 22px; height: 22px; color: var(--astra-text-muted); border: 0; border-radius: 6px; background: transparent; cursor: pointer; }
.astra-toast > button:hover { color: var(--astra-text-primary); background: rgba(101,121,145,.12); }
.astra-toast[data-kind='success'] { border-left-color: var(--astra-success); }
.astra-toast[data-kind='success'] > svg { color: var(--astra-success); }
.astra-toast[data-kind='error'] { border-left-color: var(--astra-danger); }
.astra-toast[data-kind='error'] > svg { color: var(--astra-danger); }
.astra-toast[data-kind='info'] { border-left-color: var(--astra-primary); }
.astra-toast[data-kind='info'] > svg { color: var(--astra-primary); }
.astra-toast-enter-active, .astra-toast-leave-active { transition: opacity .18s ease, transform .18s ease; }
.astra-toast-enter-from, .astra-toast-leave-to { opacity: 0; transform: translateY(8px); }
@media (max-width: 600px) { .astra-toaster { right: 16px; left: 16px; bottom: 16px; } }
</style>