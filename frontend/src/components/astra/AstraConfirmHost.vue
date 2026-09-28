<template>
  <ElDialog
    v-if="state"
    data-testid="astra-confirm-dialog"
    :model-value="true"
    :title="state.title"
    width="min(440px, 100%)"
    :show-close="false"
    :close-on-click-modal="false"
    :close-on-press-escape="false"
  >
    <template #header>
      <h3 class="astra-confirm__title">{{ state.title }}</h3>
    </template>
    <p v-if="state.message" class="astra-confirm__message">{{ state.message }}</p>
    <template #footer>
      <ElButton @click="resolveConfirm(false)">{{ state.cancelLabel }}</ElButton>
      <ElButton :type="state.danger ? 'danger' : 'primary'" @click="resolveConfirm(true)">
        {{ state.confirmLabel }}
      </ElButton>
    </template>
  </ElDialog>
</template>

<script setup lang="ts">
import { ElButton, ElDialog } from 'element-plus'
import { resolveConfirm, useConfirmState } from '@/composables/useConfirm'

// A danger/confirm dialog must not close by overlay click or ESC; the user has
// to press 取消 or 确认 explicitly. Cancel is always on the left, confirm on the
// right, and a destructive action uses the danger button style. The dialog only
// mounts while a confirm is pending, so Element Plus gives it a z-index above
// any already-open form dialog and the explicit buttons stay reachable.
const state = useConfirmState()
</script>

<style scoped>
.astra-confirm__title { margin: 0; font-size: var(--astra-font-section); line-height: normal; }
.astra-confirm__message { margin: 0; color: var(--astra-text-muted); font-size: var(--astra-font-body); line-height: 1.6; }
</style>
