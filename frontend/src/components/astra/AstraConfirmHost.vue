<template>
  <Teleport to="body">
    <div v-if="state" class="modal-backdrop" data-testid="astra-confirm-dialog">
      <div
        class="modal-card confirm-action-card"
        role="alertdialog"
        aria-modal="true"
        :aria-label="state.title"
      >
        <header>
          <div>
            <h3>{{ state.title }}</h3>
            <p v-if="state.message" class="astra-confirm__message">{{ state.message }}</p>
          </div>
        </header>
        <footer>
          <button type="button" class="button" @click="resolveConfirm(false)">{{ state.cancelLabel }}</button>
          <button
            type="button"
            class="button"
            :class="state.danger ? 'button--danger' : 'button--primary'"
            @click="resolveConfirm(true)"
          >
            {{ state.confirmLabel }}
          </button>
        </footer>
      </div>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { onBeforeUnmount, watch } from 'vue'
import { resolveConfirm, useConfirmState } from '@/composables/useConfirm'
import { acquireOverlayLock, releaseOverlayLock } from '@/composables/useOverlayLock'

// A danger/confirm dialog must not close by overlay click or ESC; the user has
// to press 取消 or 确认 explicitly. Cancel is always on the left, confirm on the
// right, and a destructive action uses the danger button style.
const state = useConfirmState()

let locked = false
watch(state, (value) => {
  if (value && !locked) {
    acquireOverlayLock()
    locked = true
  } else if (!value && locked) {
    releaseOverlayLock()
    locked = false
  }
})

onBeforeUnmount(() => {
  if (locked) releaseOverlayLock()
})
</script>

<style scoped>
/* Must sit above any open form dialog so the explicit 取消 / 确认 is reachable. */
.modal-backdrop { z-index: 1300; }
.confirm-action-card { width: min(440px, 100%); }
.astra-confirm__message { margin: 6px 0 0; color: var(--astra-text-muted); font-size: var(--astra-font-body); line-height: 1.6; }
</style>