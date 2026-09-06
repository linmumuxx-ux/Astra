<template>
  <button
    type="button"
    class="astra-switch"
    :class="{ 'astra-switch--on': modelValue }"
    role="switch"
    :aria-checked="modelValue"
    :disabled="disabled"
    :aria-label="label"
    @click="toggle"
  >
    <span class="astra-switch__track"><i /></span>
    <span v-if="label" class="astra-switch__label">{{ label }}</span>
  </button>
</template>

<script setup lang="ts">
const props = withDefaults(defineProps<{ modelValue: boolean; label?: string; disabled?: boolean }>(), { modelValue: false })
const emit = defineEmits<{ (e: 'update:modelValue', value: boolean): void }>()
function toggle() {
  if (props.disabled) return
  emit('update:modelValue', !props.modelValue)
}
</script>

<style scoped>
.astra-switch { display: inline-flex; align-items: center; gap: 8px; padding: 0; color: var(--astra-text-secondary); border: 0; background: transparent; cursor: pointer; }
.astra-switch__track { position: relative; display: inline-flex; align-items: center; width: 38px; height: 22px; padding: 2px; border-radius: 999px; background: var(--astra-bg-elevated); transition: background-color 0.16s ease; }
.astra-switch__track i { width: 18px; height: 18px; border-radius: 50%; background: #fff; box-shadow: 0 1px 3px rgba(0, 0, 0, 0.18); transition: transform 0.16s ease; }
.astra-switch--on .astra-switch__track { background: var(--astra-primary); }
.astra-switch--on .astra-switch__track i { transform: translateX(16px); }
.astra-switch:disabled { opacity: 0.55; cursor: not-allowed; }
.astra-switch__label { font-size: var(--astra-font-control); }
</style>
