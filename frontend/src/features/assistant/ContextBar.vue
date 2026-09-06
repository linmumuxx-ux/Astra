<template>
  <div v-if="context" class="assistant-context">
    <MapPin :size="13" />
    <span class="assistant-context__label">当前上下文</span>
    <span class="assistant-context__chip">{{ label }}</span>
  </div>
</template>

<script setup lang="ts">
import { MapPin } from 'lucide-vue-next'
import { computed } from 'vue'
import { useRoute } from 'vue-router'

const route = useRoute()
const context = computed(() => {
  const path = route.path
  if (path === '/') return { type: 'dashboard' as const, id: null }
  const match = (prefix: string) => path.startsWith(prefix) ? path.slice(prefix.length).split('/')[0] || null : null
  const taskId = match('/tasks/')
  if (taskId) return { type: 'task' as const, id: taskId }
  const employeeId = match('/employees/')
  if (employeeId) return { type: 'employee' as const, id: employeeId }
  const runId = match('/runs/')
  if (runId) return { type: 'run' as const, id: runId }
  if (path.startsWith('/library')) return { type: 'library' as const, id: null }
  return null
})

const LABELS: Record<string, string> = {
  dashboard: '平台总览',
  task: '任务',
  employee: '员工',
  run: '运行记录',
  library: '数字图书馆',
}

const label = computed(() =>
  context.value
    ? `${LABELS[context.value.type] ?? context.value.type}${context.value.id ? ` · ${context.value.id}` : ''}`
    : '',
)
</script>

<style scoped>
.assistant-context {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 14px;
  border-bottom: 1px solid var(--astra-border);
  color: var(--astra-text-muted);
  font-size: var(--astra-font-body);
  background: var(--astra-bg-sidebar);
}
.assistant-context__chip {
  background: var(--astra-primary-soft);
  color: var(--astra-primary-bright);
  border-radius: 999px;
  padding: 1px 9px;
  max-width: 240px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
