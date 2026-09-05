<template>
  <div class="confirm-card" :data-status="payload.status">
    <header>
      <ShieldQuestion :size="15" />
      <strong>{{ payload.operation_label || '平台操作确认' }}</strong>
      <span class="confirm-card__risk" :class="`risk--${(payload.risk_level || '').toLowerCase()}`">
        风险 {{ riskLabel }}
      </span>
    </header>
    <dl class="confirm-card__preview">
      <div v-for="(value, key) in previewFields" :key="key">
        <dt>{{ labelOf(key) }}</dt>
        <dd>{{ value }}</dd>
      </div>
    </dl>
    <footer v-if="payload.status === 'WAITING_CONFIRM'" class="confirm-card__actions">
      <button class="confirm-card__confirm" type="button" :disabled="busy" @click="confirm">
        {{ busy ? '执行中…' : '确认执行' }}
      </button>
      <button class="confirm-card__modify" type="button" @click="modify">修改</button>
      <button class="confirm-card__cancel" type="button" @click="cancel">取消</button>
    </footer>
    <p v-else class="confirm-card__done">
      {{ statusText }}
    </p>
  </div>
</template>

<script setup lang="ts">
import { ShieldQuestion } from 'lucide-vue-next'
import { computed, ref } from 'vue'
import { useAssistantStore } from '../store'
import type { AssistantCardPayload } from '../types'

const props = defineProps<{ payload: AssistantCardPayload }>()
const emit = defineEmits<{ modify: [previewText: string] }>()
const store = useAssistantStore()
const busy = ref(false)

const riskLabel = computed(
  () => ({ L1: '低', L2: '中', L3: '高' }[props.payload.risk_level ?? ''] ?? props.payload.risk_level ?? '中'),
)

const PREVIEW_LABELS: Record<string, string> = {
  task_name: '任务名称',
  task_type_label: '任务类型',
  employee: '执行员工',
  category: '任务分类',
  priority: '优先级',
  task_id: '任务编号',
  current_status: '当前状态',
  reason: '操作原因',
}

const SKIP_KEYS = new Set(['inputs', 'acceptance_criteria', 'employee_id'])

const previewFields = computed(() => {
  const preview = props.payload.preview ?? {}
  const fields: Record<string, string> = {}
  for (const [key, value] of Object.entries(preview)) {
    if (SKIP_KEYS.has(key) || value === null || value === undefined || value === '') continue
    fields[key] = String(value)
  }
  return fields
})

const labelOf = (key: string) => PREVIEW_LABELS[key] ?? key

const statusText = computed(() => {
  const status = props.payload.status
  if (status === 'SUCCESS') {
    const taskId = props.payload.result?.task_id
    return taskId ? `已执行成功，任务编号 ${taskId}` : '已执行成功'
  }
  if (status === 'CANCELLED') return '操作已取消'
  if (status === 'EXPIRED') return '操作已过期，请重新发起'
  if (status === 'FAILED') return `执行失败：${props.payload.result?.error ?? '未知原因'}`
  return status ?? ''
})

const operationId = computed(() => props.payload.operation_id ?? '')

async function confirm() {
  busy.value = true
  try {
    await store.confirmOperation(operationId.value)
  } finally {
    busy.value = false
  }
}

async function cancel() {
  await store.cancelOperation(operationId.value)
}

function modify() {
  const preview = props.payload.preview ?? {}
  const summary = [
    preview.task_name ? `任务：${preview.task_name}` : '',
    preview.task_id ? `任务编号：${preview.task_id}` : '',
    preview.employee ? `执行员工：${preview.employee}` : '',
  ]
    .filter(Boolean)
    .join('；')
  emit('modify', `${summary}，请帮我修改：`)
}
</script>

<style scoped>
.confirm-card {
  border: 1px solid var(--astra-primary-border);
  background: var(--astra-primary-soft);
  border-radius: 12px;
  padding: 12px 14px;
  display: grid;
  gap: 10px;
  max-width: 340px;
}
.confirm-card header {
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--astra-primary-bright);
}
.confirm-card header strong { font-size: var(--astra-font-emphasis); flex: 1; }
.confirm-card__risk {
  font-size: var(--astra-font-helper);
  padding: 2px 8px;
  border-radius: 999px;
  background: var(--astra-warning-soft);
  color: var(--astra-warning);
}
.confirm-card__risk.risk--l3 { background: var(--astra-danger-soft); color: var(--astra-danger); }
.confirm-card__preview { display: grid; gap: 4px; margin: 0; }
.confirm-card__preview div {
  display: grid;
  grid-template-columns: 72px 1fr;
  gap: 8px;
  font-size: var(--astra-font-body);
}
.confirm-card__preview dt { color: var(--astra-text-muted); }
.confirm-card__preview dd { margin: 0; color: var(--astra-text-primary); word-break: break-all; }
.confirm-card__actions { display: flex; gap: 8px; }
.confirm-card__actions button {
  font-size: var(--astra-font-control);
  padding: 5px 14px;
  border-radius: 8px;
  cursor: pointer;
  border: 1px solid transparent;
}
.confirm-card__confirm {
  background: var(--astra-primary);
  color: #fff;
}
.confirm-card__confirm:disabled { opacity: 0.6; cursor: default; }
.confirm-card__modify,
.confirm-card__cancel {
  background: transparent;
  border-color: var(--astra-border);
  color: var(--astra-text-secondary);
}
.confirm-card__done {
  margin: 0;
  font-size: var(--astra-font-body);
  color: var(--astra-text-secondary);
}
</style>
