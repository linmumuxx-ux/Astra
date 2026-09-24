<template>
  <section class="gateway-section">
    <header class="gateway-section__head">
      <div><h3>Gateway Key</h3><p>Key 以 agw_ 前缀生成，库中只存不可逆摘要；原文仅在创建后显示一次。</p></div>
      <div class="gateway-section__actions">
        <button type="button" class="button" :disabled="loading" @click="load"><RefreshCw :size="14" :class="{ spin: loading }" />刷新</button>
        <button v-if="canKey" type="button" class="button button--primary" @click="openCreate"><Plus :size="15" />新建 Key</button>
      </div>
    </header>

    <p v-if="error" class="gateway-alert"><TriangleAlert :size="15" />{{ error }}<button type="button" @click="load">重试</button></p>

    <div class="table-wrap gateway-card">
      <table class="gateway-key-table">
        <thead><tr><th>名称</th><th>前缀</th><th>归属</th><th>允许模型</th><th>并发</th><th>额度（时 / 日）</th><th>有效期</th><th>状态</th><th>最近使用</th><th class="gateway-col-actions">操作</th></tr></thead>
        <tbody>
          <tr v-for="key in keys" :key="key.id">
            <td><strong>{{ key.name }}</strong><small>{{ key.id }}</small></td>
            <td class="gateway-mono">{{ key.key_prefix }}…</td>
            <td>{{ key.owner_id || '—' }}</td>
            <td>{{ key.allowed_models.length ? key.allowed_models.join('、') : '全部' }}</td>
            <td class="gateway-num">{{ key.max_concurrency || '不限' }}</td>
            <td class="gateway-num">{{ limitText(key.hourly_token_limit) }} / {{ limitText(key.daily_token_limit) }}</td>
            <td class="gateway-time">{{ key.expires_at ? formatDateTime(key.expires_at) : '长期' }}</td>
            <td>
              <span v-if="key.revoked_at" class="status-badge" data-tone="danger">已吊销</span>
              <span v-else class="status-badge" :data-tone="key.enabled ? 'success' : 'neutral'">{{ key.enabled ? '启用' : '停用' }}</span>
            </td>
            <td class="gateway-time">{{ formatRelativeTime(key.last_used_at) }}</td>
            <td class="gateway-col-actions">
              <div v-if="canKey" class="gateway-row-actions">
                <button class="gateway-icon-btn" type="button" title="编辑" @click="openEdit(key)"><Pencil :size="14" /></button>
                <button class="gateway-icon-btn gateway-icon-btn--danger" type="button" title="吊销" :disabled="Boolean(key.revoked_at)" @click="revoke(key)"><Ban :size="14" /></button>
              </div>
            </td>
          </tr>
          <tr v-if="!keys.length"><td colspan="10" class="empty-cell">暂无 Gateway Key。</td></tr>
        </tbody>
      </table>
    </div>

    <el-dialog :model-value="editorOpen" :title="form.id ? '编辑 Gateway Key' : '新建 Gateway Key'" data-testid="gateway-key-dialog" width="min(540px,100%)" @close="editorOpen = false"
      :close-on-click-modal="false"
      :close-on-press-escape="false"
      :show-close="!(saving)"
      append-to-body
      lock-scroll
      destroy-on-close
    >
      <form id="gateway-key-form" class="gateway-dialog-form" @submit.prevent="submit">
        <label>名称<input v-model="form.name" required /></label>
        <div class="gateway-form__grid">
          <label>归属 ID<input v-model="form.owner_id" placeholder="可选" /></label>
          <label>有效至<input v-model="form.expires_at" type="datetime-local" /></label>
        </div>
        <label>允许模型（留空为全部，逗号或换行分隔）<textarea v-model="form.allowed_models" rows="2" /></label>
        <div class="gateway-form__grid">
          <label>最大并发（0 不限）<input v-model="form.max_concurrency" type="number" min="0" /></label>
          <label v-if="form.id" class="gateway-toggle"><span>启用</span><el-switch v-model="form.enabled" /></label>
        </div>
        <div class="gateway-form__grid">
          <label>每小时 Token 限额<input v-model="form.hourly" type="number" min="0" placeholder="不限" /></label>
          <label>每日 Token 限额<input v-model="form.daily" type="number" min="0" placeholder="不限" /></label>
        </div>
      </form>
      <template #footer>
        <button type="button" class="button" :disabled="saving" @click="editorOpen = false">取消</button>
        <button type="submit" form="gateway-key-form" class="button button--primary" :disabled="saving"><LoaderCircle v-if="saving" :size="14" class="spin" />保存</button>
      </template>
    </el-dialog>

    <el-dialog :model-value="plaintextOpen && Boolean(createdKey)" title="Gateway Key 已创建" data-testid="gateway-key-plaintext" width="min(560px,100%)" @close="closePlaintext"
      :close-on-click-modal="false"
      :close-on-press-escape="false"
      :show-close="true"
      append-to-body
      lock-scroll
      destroy-on-close
    >
      <p class="astra-dialog-subtitle">请立即复制保存，关闭后无法再次查看原文。</p>
      <p class="gateway-key-warning"><TriangleAlert :size="15" />库中只保存摘要，任何页面与日志都不会再显示该 Key。</p>
      <IdDisplay v-if="createdKey" :value="createdKey.key" :max-width="52" />
      <template #footer>
        <button type="button" class="button button--primary" @click="closePlaintext">我已保存</button>
      </template>
    </el-dialog>
  </section>
</template>

<script setup lang="ts">
import { Ban, LoaderCircle, Pencil, Plus, RefreshCw, TriangleAlert } from 'lucide-vue-next'
import { computed, onMounted, reactive, ref } from 'vue'
import {
  gatewayApi,
  GatewayApiError,
  type GatewayKey,
  type GatewayKeyCreated,
} from '@/api/gateway'
import IdDisplay from '@/components/astra/IdDisplay.vue'
import { confirmDialog } from '@/composables/useConfirm'
import { notify } from '@/composables/useToast'
import { useGatewayAuth } from '@/composables/useGatewayAuth'
import { errorMessage, formatDateTime, formatRelativeTime, parseNumberList } from '@/utils/gateway'

const { hasRole, disconnect } = useGatewayAuth()
const canKey = computed(() => hasRole('key'))
const keys = ref<GatewayKey[]>([])
const loading = ref(false)
const error = ref('')
const saving = ref(false)
const editorOpen = ref(false)
const plaintextOpen = ref(false)
const createdKey = ref<GatewayKeyCreated | null>(null)

const form = reactive({
  id: '',
  name: '',
  owner_id: '',
  allowed_models: '',
  max_concurrency: '0',
  hourly: '',
  daily: '',
  expires_at: '',
  enabled: true,
})

function limitText(value: number | null): string {
  if (value === null || value === undefined) return '不限'
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`
  if (value >= 1_000) return `${(value / 1_000).toFixed(0)}K`
  return String(value)
}

function intOrNull(value: string): number | null {
  const text = value.trim()
  if (!text) return null
  const parsed = Number(text)
  return Number.isFinite(parsed) ? Math.trunc(parsed) : null
}

function expiresIso(value: string): string | null {
  if (!value) return null
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? null : date.toISOString()
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    keys.value = await gatewayApi.keys()
  } catch (reason) {
    if (reason instanceof GatewayApiError && reason.status === 401) { disconnect(); return }
    error.value = errorMessage(reason, 'Key 列表加载失败')
  } finally {
    loading.value = false
  }
}

function openCreate() {
  Object.assign(form, { id: '', name: '', owner_id: '', allowed_models: '', max_concurrency: '0', hourly: '', daily: '', expires_at: '', enabled: true })
  editorOpen.value = true
}

function openEdit(key: GatewayKey) {
  Object.assign(form, {
    id: key.id,
    name: key.name,
    owner_id: key.owner_id ?? '',
    allowed_models: key.allowed_models.join('\n'),
    max_concurrency: String(key.max_concurrency),
    hourly: key.hourly_token_limit?.toString() ?? '',
    daily: key.daily_token_limit?.toString() ?? '',
    expires_at: key.expires_at ? key.expires_at.slice(0, 16) : '',
    enabled: key.enabled,
  })
  editorOpen.value = true
}

async function submit() {
  saving.value = true
  try {
    const body = {
      name: form.name.trim(),
      owner_id: form.owner_id.trim() || null,
      allowed_models: parseNumberList(form.allowed_models),
      max_concurrency: Number(form.max_concurrency) || 0,
      hourly_token_limit: intOrNull(form.hourly),
      daily_token_limit: intOrNull(form.daily),
      expires_at: expiresIso(form.expires_at),
    }
    if (form.id) {
      await gatewayApi.updateKey(form.id, { ...body, enabled: form.enabled })
      notify('Key 已更新')
      editorOpen.value = false
      await load()
    } else {
      const created = await gatewayApi.createKey(body)
      createdKey.value = created
      editorOpen.value = false
      plaintextOpen.value = true
      await load()
    }
  } catch (reason) {
    notify(errorMessage(reason, '保存 Key 失败'), 'error')
  } finally {
    saving.value = false
  }
}

function closePlaintext() {
  plaintextOpen.value = false
  createdKey.value = null
}

async function revoke(key: GatewayKey) {
  const confirmed = await confirmDialog({ title: '吊销 Gateway Key', message: `确认吊销「${key.name}」？吊销后该 Key 立即失效且不可恢复。`, confirmLabel: '吊销', danger: true })
  if (!confirmed) return
  try {
    await gatewayApi.revokeKey(key.id)
    notify('Key 已吊销')
    await load()
  } catch (reason) {
    notify(errorMessage(reason, '吊销失败'), 'error')
  }
}

onMounted(load)
</script>

<style scoped>
.gateway-card { border: 1px solid var(--astra-border); border-radius: 12px; background: var(--astra-bg-card); box-shadow: var(--astra-shadow-panel); }
.gateway-key-table { min-width: 1060px; }
.gateway-key-table td > strong { display: block; color: var(--astra-text-primary); font-size: var(--astra-font-body); }
.gateway-key-table td > small { display: block; color: var(--astra-text-muted); font-size: var(--astra-font-micro); }
.gateway-mono { font-family: var(--astra-font-family); font-size: var(--astra-font-helper); }
.gateway-num, .gateway-time { white-space: nowrap; font-size: var(--astra-font-helper); font-variant-numeric: tabular-nums; }
.gateway-dialog-form { display: grid; gap: 12px; }
.gateway-dialog-form label { display: grid; gap: 6px; margin: 0; color: var(--astra-text-secondary); font-size: var(--astra-font-control); }
.gateway-key-warning { display: flex; align-items: center; gap: 7px; margin: 0; padding: 10px 12px; color: var(--astra-warning); border: 1px solid rgba(233, 149, 63, .28); border-radius: 9px; background: var(--astra-warning-soft); font-size: var(--astra-font-helper); }
</style>