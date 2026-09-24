<template>
  <div v-if="hasError" class="error-detail" :data-tone="tone">
    <div class="error-detail__row">
      <div class="error-detail__icon"><CircleX :size="16" /></div>
      <div class="error-detail__summary">
        <span v-if="label">{{ label }}</span>
        <strong>{{ title }}</strong>
        <p v-if="description">{{ description }}</p>
        <code v-if="code">HTTP {{ code }}</code>
      </div>
      <el-button v-if="rawError" size="small" @click="expanded = !expanded">
        {{ expanded ? '收起' : '查看原始错误' }}
      </el-button>
    </div>
    <pre v-if="expanded && rawError">{{ rawError }}</pre>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { CircleX } from 'lucide-vue-next'

const props = defineProps<{
  title: string
  label?: string | null
  description?: string | null
  code?: number | null
  rawError?: string | null
}>()

const expanded = ref(false)
const hasError = computed(() => Boolean(props.rawError || props.description || props.title))
const tone = computed(() => 'danger')
</script>

<style scoped>
.error-detail {
  padding: 12px 13px;
  border: 1px solid rgba(255, 111, 125, 0.26);
  border-radius: 10px;
  background: var(--astra-danger-soft);
}
.error-detail__row { display: flex; align-items: center; gap: 11px; }
.error-detail__icon {
  display: grid; place-items: center; flex: none;
  width: 32px; height: 32px; border-radius: 9px;
  color: var(--astra-danger); background: var(--astra-danger-soft);
}
.error-detail__summary { display: grid; gap: 1px; min-width: 0; margin-right: auto; }
.error-detail__summary span { color: var(--astra-danger); font-size: var(--astra-font-helper); font-weight: var(--astra-weight-bold); letter-spacing: 0.04em; }
.error-detail__summary strong { font-size: var(--astra-font-control); }
.error-detail__summary p { margin: 0; color: var(--astra-text-secondary); font-size: var(--astra-font-helper); }
.error-detail__summary code {
  align-self: start; margin-top: 3px; padding: 1px 7px;
  color: var(--astra-danger); border-radius: 5px; background: rgba(255, 111, 125, 0.13);
  font: var(--astra-weight-bold) var(--astra-font-helper) var(--astra-font-family);
}
.error-detail pre {
  max-height: 180px; margin: 10px 0 0; padding: 10px 12px; overflow: auto;
  color: #f0b7bc; border-radius: 8px; background: #2a1013;
  font: var(--astra-font-helper)/1.5 var(--astra-font-family); white-space: pre-wrap; word-break: break-word;
}
</style>
