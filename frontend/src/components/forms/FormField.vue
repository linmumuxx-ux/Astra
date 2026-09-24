<template>
  <div class="astra-form-field" :class="{ 'astra-form-field--inline': inline }">
    <FormLabel :label="label" :help="help" :for-id="controlId" />
    <slot :id="controlId" />
  </div>
</template>

<script setup lang="ts">
import { useId } from 'vue'
import FormLabel from './FormLabel.vue'
withDefaults(defineProps<{ label: string; help?: string; inline?: boolean }>(), { inline: false })
const controlId = `form-control-${useId()}`
</script>

<style scoped>
.astra-form-field { display: grid; align-content: start; gap: 7px; min-width: 0; margin-bottom: 14px; color: var(--astra-text-secondary); font-size: var(--astra-font-control); }
.astra-form-field--inline { display: flex; align-items: center; margin-bottom: 0; }
.astra-form-field--inline > :deep(.astra-form-label) { flex: 1; }
.astra-form-field--inline > :deep(.el-switch) { flex: none; }
.astra-form-field :deep(.el-input), .astra-form-field :deep(.el-select), .astra-form-field :deep(.el-input-number) { width: 100%; min-width: 0; }
.astra-form-field :deep(input:not([type='checkbox']):not([type='file'])), .astra-form-field :deep(select) { width: 100%; min-width: 0; height: var(--astra-control-height); }
</style>
