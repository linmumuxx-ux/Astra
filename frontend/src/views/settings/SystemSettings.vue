<template>
  <div class="system-settings">
    <section class="config-grid">
      <AstraPanel title="运行参数"><dl class="config-list"><div><dt>任务发现 / 分配</dt><dd>30 秒 / 5 秒</dd></div><div><dt>无活动提示</dt><dd>15 分钟（不改变任务状态）</dd></div><div><dt>员工并发</dt><dd>每人 1 项任务</dd></div></dl></AstraPanel>
      <AstraPanel title="平台助手配置" subtitle="助手异常时入口仍保留，不影响任务与员工功能"><dl class="config-list"><div><dt>助手服务</dt><dd>{{ assistantHealth ? (assistantHealth.available ? '正常' : '异常') : '检测中…' }}</dd></div><div><dt>助手 OpenCode</dt><dd>{{ assistantHealth ? (assistantHealth.opencode_healthy ? `正常（${assistantHealth.opencode_version || '未知版本'}）` : '不可用') : '检测中…' }}</dd></div></dl></AstraPanel>
      <AstraPanel title="界面偏好"><label class="config-row"><AstraSwitch v-model="reducedMotion" @update:model-value="saveMotion" :label="reducedMotion ? '已减少动效' : '未减少动效'" /><span class="row-note">关闭数字办公室的工作动画，适合长时间观看。</span></label></AstraPanel>
      <AstraPanel title="Agent 执行策略"><dl class="config-list"><div><dt>工作空间</dt><dd>属于员工并长期复用</dd></div><div><dt>会话</dt><dd>每项任务独立，挂起与恢复时保留</dd></div><div><dt>工作方式</dt><dd>由员工自己的 Agent 自主决定</dd></div><div><dt>用量数据</dt><dd>只记录 Agent 实际返回值</dd></div></dl></AstraPanel>
      <AstraPanel title="平台助手服务状态与运行端点" subtitle="仅关心服务是否可用，不混入配置项">
        <div class="service-status-list">
          <ServiceStatusCard v-if="assistantHealth" title="平台助手（OpenCode）" :state="assistantState" :message="assistantMessage" :detail="assistantDetail" :endpoint="assistantHealth.opencode_url || null" :http-code="assistantHttp" :raw-error="assistantRaw" :timestamp="checkedAt" recheckable :checking="checking" @recheck="checkAssistant" />
          <ServiceStatusCard title="平台控制台 API" :state="apiState" :message="apiMessage" :detail="apiDetail" :raw-error="apiRaw" :timestamp="apiCheckedAt" recheckable :checking="checking" @recheck="checkApi" />
        </div>
      </AstraPanel>
    </section>
    <div v-if="message" class="form-message" :data-error="messageIsError">{{ message }}</div>
    <StickyActionBar v-if="dirty" :dirty="dirty" :saving="saving" save-label="保存系统设置" @save="save" @cancel="reset" />
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { api } from '@/api/client'
import AstraPanel from '@/components/astra/AstraPanel.vue'
import AstraSwitch from '@/components/astra/AstraSwitch.vue'
import ServiceStatusCard from '@/components/astra/ServiceStatusCard.vue'
import StickyActionBar from '@/components/astra/StickyActionBar.vue'
import { assistantApi } from '@/features/assistant/api'
import type { AssistantHealth } from '@/features/assistant/types'

const reducedMotion = ref(localStorage.getItem('astra-reduced-motion') === 'true')
const originalMotion = ref(reducedMotion.value)
const saving = ref(false)
const checking = ref(false)
const message = ref('')
const messageIsError = ref(false)
const confirmed = ref(false)

const assistantHealth = ref<AssistantHealth | null>(null)
const checkedAt = ref<string | null>(null)
const apiState = ref<'ok' | 'error' | 'checking' | 'unknown'>('unknown')
const apiMessage = ref('')
const apiDetail = ref('')
const apiRaw = ref<string | null>(null)
const apiCheckedAt = ref<string | null>(null)

const dirty = computed(() => reducedMotion.value !== originalMotion.value)

const assistantState = computed<'ok' | 'error' | 'checking' | 'unknown'>(() => {
  if (!assistantHealth.value) return 'unknown'
  return assistantHealth.value.available && assistantHealth.value.opencode_healthy ? 'ok' : 'error'
})
const assistantMessage = computed(() => {
  if (!assistantHealth.value) return '检测中…'
  return assistantHealth.value.opencode_healthy ? 'OpenCode 服务正常' : 'OpenCode 服务异常'
})
const assistantDetail = computed(() => assistantHealth.value?.available ? null : (assistantHealth.value?.detail || '助手服务暂不可用，平台其他功能不受影响。'))
const assistantHttp = computed(() => {
  const detail = assistantHealth.value?.detail ?? ''
  const match = detail.match(/HTTP\s*(\d{3})/i)
  return match ? Number(match[1]) : null
})
const assistantRaw = computed(() => {
  const detail = assistantHealth.value?.detail ?? ''
  if (/Server error|502|bad gateway|exception|error/i.test(detail)) return detail || null
  return null
})

function saveMotion() { localStorage.setItem('astra-reduced-motion', String(reducedMotion.value)) }
async function checkAssistant() {
  checking.value = true
  try {
    const health = await assistantApi.health()
    assistantHealth.value = health
    checkedAt.value = new Date().toISOString()
  } catch (error) {
    assistantHealth.value = {
      available: false, assistant: 'unreachable', opencode_healthy: false, opencode_version: null, opencode_url: '',
      detail: error instanceof Error ? error.message : '助手服务不可达',
    }
    checkedAt.value = new Date().toISOString()
  } finally { checking.value = false }
}
async function checkApi() {
  checking.value = true
  try {
    await api.health()
    apiState.value = 'ok'; apiMessage.value = '控制台 API 正常'; apiDetail.value = ''
  } catch (error) {
    apiState.value = 'error'; apiMessage.value = '控制台 API 异常'; apiDetail.value = error instanceof Error ? error.message : '服务不可达'
    apiRaw.value = error instanceof Error ? error.message : null
  } finally {
    apiRaw.value = apiState.value === 'error' ? apiDetail.value : null
    apiCheckedAt.value = new Date().toISOString()
    checking.value = false
  }
}

async function save() {
  saving.value = true; message.value = ''; messageIsError.value = false
  try {
    originalMotion.value = reducedMotion.value
    localStorage.setItem('astra-reduced-motion', String(reducedMotion.value))
    message.value = '系统设置已保存。'
  } finally { saving.value = false }
}
function reset() { reducedMotion.value = originalMotion.value }

defineExpose({ loadHealth: checkAssistant })
</script>

<style scoped>
.system-settings { display: grid; gap: 0; }
.config-grid { display: grid; grid-template-columns: 1fr 1fr; gap: var(--astra-content-gap); }
.system-settings :deep(.config-list) { display: grid; }
.system-settings :deep(.config-list > div) { display: flex; justify-content: space-between; gap: 16px; padding: 10px 0; border-bottom: 1px solid var(--astra-border); }
.system-settings :deep(.config-list dt) { color: var(--astra-text-muted); font-size: var(--astra-font-helper); }
.system-settings :deep(.config-list dd) { margin: 0; color: var(--astra-text-primary); font: 600 var(--astra-font-helper) var(--astra-font-display); text-align: right; }
.config-row { display: flex; align-items: center; justify-content: space-between; gap: 14px; padding: 10px 0; border-bottom: 1px solid var(--astra-border); }
.row-note { color: var(--astra-text-muted); font-size: var(--astra-font-helper); }
.service-status-list { display: grid; gap: 10px; }
@media (max-width: 900px) { .config-grid { grid-template-columns: 1fr; } }
</style>
