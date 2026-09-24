<template>
  <el-dialog
    :model-value="open"
    :width="width || 'min(720px, calc(100vw - 32px))'"
    :close-on-click-modal="dismissible && !busy"
    :close-on-press-escape="dismissible && !busy"
    :show-close="!busy"
    :class="['astra-dialog', cardClass]"
    :data-testid="testid"
    append-to-body
    lock-scroll
    @update:model-value="onModelValue"
  >
    <template #header>
      <div class="astra-dialog__heading">
        <small v-if="eyebrow">{{ eyebrow }}</small>
        <h3>{{ title }}</h3>
        <p v-if="subtitle" class="astra-dialog__subtitle">{{ subtitle }}</p>
      </div>
    </template>

    <div class="astra-dialog__body">
      <slot />
    </div>

    <template v-if="$slots.footer" #footer>
      <div class="astra-dialog__footer">
        <slot name="footer" />
      </div>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
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

function onModelValue(value: boolean): void {
  if (!value && !props.busy) emit('close')
}
</script>

<style scoped>
.astra-dialog__heading { min-width: 0; }
.astra-dialog__heading small { display: block; margin-bottom: 4px; color: var(--astra-primary); font-size: var(--astra-font-helper); font-weight: var(--astra-weight-bold); }
.astra-dialog__heading h3 { margin: 0; color: var(--astra-text-primary); }
.astra-dialog__subtitle { margin: 5px 0 0; color: var(--astra-text-muted); font-size: var(--astra-font-body); }
.astra-dialog__body { display: grid; gap: 14px; }
.astra-dialog__footer { display: flex; justify-content: flex-end; gap: 10px; }
</style>
