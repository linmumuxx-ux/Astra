<template>
  <span class="astra-switch-field">
    <el-switch
      :model-value="modelValue"
      :disabled="disabled"
      :aria-label="label"
      @update:model-value="onUpdate"
    />
    <span v-if="label" class="astra-switch-field__label">{{ label }}</span>
  </span>
</template>

<script setup lang="ts">
withDefaults(defineProps<{ modelValue: boolean; label?: string; disabled?: boolean }>(), {
  modelValue: false,
  disabled: false,
})
const emit = defineEmits<{ (e: 'update:modelValue', value: boolean): void }>()

function onUpdate(value: boolean | string | number): void {
  emit('update:modelValue', Boolean(value))
}
</script>

<style scoped>
.astra-switch-field { display: inline-flex; align-items: center; gap: 8px; color: var(--astra-text-secondary); }
.astra-switch-field__label { font-size: var(--astra-font-control); }
</style>
