<template>
  <section class="gateway-section">
    <header class="gateway-section__head">
      <div><h3>Gateway Key</h3><p>Key 以 agw_ 前缀生成，库中只存不可逆摘要；原文仅在创建后显示一次。</p></div>
      <div class="gateway-section__actions">
        <el-button :loading="loading" :disabled="loading" @click="load"><RefreshCw v-if="!loading" :size="14" />刷新</el-button>
        <el-button v-if="canKey" type="primary" @click="openCreate"><Plus :size="15" />新建 Key</el-button>
      </div>
    </header>

    <p v-if="error" class="gateway-alert"><TriangleAlert :size="15" />{{ error }}<el-button type="danger" link @click="load">重试</el-button></p>

    <div class="gateway-card">
      <el-table :data="keys" stripe empty-text="暂无 Gateway Key。">
        <el-table-column label="名称" min-width="170">
          <template #default="{ row }"><strong>{{ row.name }}</strong><small>{{ row.id }}</small></template>
        </el-table-column>
        <el-table-column label="前缀" min-width="120"><template #default="{ row }"><span class="gateway-mono">{{ row.key_prefix }}…</span></template></el-table-column>
        <el-table-column label="归属" min-width="130"><template #default="{ row }">{{ row.owner_id || '—' }}</template></el-table-column>
        <el-table-column label="允许模型" min-width="200"><template #default="{ row }">{{ row.allowed_models.length ? row.allowed_models.join('、') : '全部' }}</template></el-table-column>
        <el-table-column label="并发" width="90" align="right"><template #default="{ row }">{{ row.max_concurrency || '不限' }}</template></el-table-column>
        <el-table-column label="额度（时 / 日）" min-width="150" align="right"><template #default="{ row }">{{ limitText(row.hourly_token_limit) }} / {{ limitText(row.daily_token_limit) }}</template></el-table-column>
        <el-table-column label="有效期" min-width="150"><template #default="{ row }">{{ row.expires_at ? formatDateTime(row.expires_at) : '长期' }}</template></el-table-column>
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag v-if="row.revoked_at" type="danger" effect="light">已吊销</el-tag>
            <el-tag v-else :type="row.enabled ? 'success' : 'info'" effect="light">{{ row.enabled ? '启用' : '停用' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="最近使用" min-width="130"><template #default="{ row }">{{ formatRelativeTime(row.last_used_at) }}</template></el-table-column>
        <el-table-column v-if="canKey" label="操作" width="100" fixed="right">
          <template #default="{ row }">
            <el-button text circle title="编辑" @click="openEdit(row)"><Pencil :size="14" /></el-button>
            <el-button type="danger" text circle title="吊销" :disabled="Boolean(row.revoked_at)" @click="revoke(row)"><Ban :size="14" /></el-button>
          </template>
        </el-table-column>
      </el-table>
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
        <label>名称<el-input v-model="form.name" required /></label>
        <div class="gateway-form__grid">
          <label>归属 ID<el-input v-model="form.owner_id" placeholder="可选" /></label>
          <label>有效至<el-input v-model="form.expires_at" type="datetime-local" /></label>
        </div>
        <label>允许模型（留空为全部，逗号或换行分隔）<el-input v-model="form.allowed_models" type="textarea" :rows="2" resize="vertical" /></label>
        <div class="gateway-form__grid">
          <label>最大并发（0 不限）<el-input-number v-model="form.max_concurrency" :min="0" controls-position="right" /></label>
          <label v-if="form.id" class="gateway-toggle"><span>启用</span><el-switch v-model="form.enabled" /></label>
        </div>
        <div class="gateway-form__grid">
          <label>每小时 Token 限额<el-input-number v-model="form.hourly" :min="0" controls-position="right" placeholder="不限" /></label>
          <label>每日 Token 限额<el-input-number v-model="form.daily" :min="0" controls-position="right" placeholder="不限" /></label>
        </div>
      </form>
      <template #footer>
        <el-button :disabled="saving" @click="editorOpen = false">取消</el-button>
        <el-button type="primary" native-type="submit" form="gateway-key-form" :loading="saving" :disabled="saving">保存</el-button>
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
        <el-button type="primary" @click="closePlaintext">我已保存</el-button>
      </template>
    </el-dialog>
  </section>
</template>

<script setup lang="ts">
import { Ban, Pencil, Plus, RefreshCw, TriangleAlert } from 'lucide-vue-next'
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
  max_concurrency: 0,
  hourly: null as number | null,
  daily: null as number | null,
  expires_at: '',
  enabled: true,
})

function limitText(value: number | null): string {
  if (value === null || value === undefined) return '不限'
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`
  if (value >= 1_000) return `${(value / 1_000).toFixed(0)}K`
  return String(value)
}

function intOrNull(value: number | null): number | null {
  if (value === null || value === undefined) return null
  return Number.isFinite(value) ? Math.trunc(value) : null
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
  Object.assign(form, { id: '', name: '', owner_id: '', allowed_models: '', max_concurrency: 0, hourly: null, daily: null, expires_at: '', enabled: true })
  editorOpen.value = true
}

function openEdit(key: GatewayKey) {
  Object.assign(form, {
    id: key.id,
    name: key.name,
    owner_id: key.owner_id ?? '',
    allowed_models: key.allowed_models.join('\n'),
    max_concurrency: key.max_concurrency,
    hourly: key.hourly_token_limit ?? null,
    daily: key.daily_token_limit ?? null,
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