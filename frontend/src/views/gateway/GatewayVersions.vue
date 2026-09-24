<template>
  <section class="gateway-section">
    <header class="gateway-section__head">
      <div><h3>配置草稿与版本</h3><p>发布前校验全部引用，生成不可变快照；回滚会以历史快照生成新版本。</p></div>
      <div class="gateway-section__actions">
        <el-button :loading="loading" :disabled="loading" @click="load"><RefreshCw v-if="!loading" :size="14" />刷新</el-button>
        <el-button v-if="canPublish" :loading="reconciling" :disabled="reconciling" @click="reconcile"><GitMerge v-if="!reconciling" :size="14" />发布对账</el-button>
      </div>
    </header>

    <p v-if="error" class="gateway-alert"><TriangleAlert :size="15" />{{ error }}<el-button type="danger" link @click="load">重试</el-button></p>

    <div class="gateway-two-col">
      <AstraPanel title="草稿校验" :subtitle="draft ? (draft.valid ? '校验通过，可发布' : `发现 ${draft.errors.length} 项错误`) : ''">
        <div v-if="draft" class="gateway-draft">
          <div class="gateway-draft__counts">
            <span v-for="(value, key) in draft.counts" :key="key"><small>{{ countLabel(String(key)) }}</small><b>{{ value }}</b></span>
          </div>
          <ul v-if="draft.errors.length" class="gateway-draft__list gateway-draft__list--error">
            <li v-for="item in draft.errors" :key="`${item.code}-${item.resource_id}`"><XCircle :size="13" />[{{ item.code }}] {{ item.message }}<em>{{ item.resource_type }} / {{ item.resource_id }}</em></li>
          </ul>
          <ul v-if="draft.warnings.length" class="gateway-draft__list gateway-draft__list--warn">
            <li v-for="(item, index) in draft.warnings" :key="index"><TriangleAlert :size="13" />{{ item }}</li>
          </ul>
          <p v-if="draft.valid && !draft.warnings.length" class="gateway-note"><CheckCircle2 :size="14" class="ok" />草稿与当前引用一致，可安全发布。</p>
          <div v-if="canPublish" class="gateway-publish">
            <el-input v-model="note" placeholder="发布说明（可选）" />
            <el-button type="primary" :loading="publishing" :disabled="publishing || !draft.valid" @click="publish"><Rocket v-if="!publishing" :size="14" />发布新版本</el-button>
          </div>
          <p v-else class="gateway-note">当前凭据缺少 publish 角色，只能查看。</p>
        </div>
        <div v-else class="gateway-placeholder">{{ loading ? '加载中…' : '暂无草稿数据' }}</div>
      </AstraPanel>

      <AstraPanel title="版本历史" :subtitle="`共 ${versions.length} 个版本`" flush>
        <el-table :data="versions" stripe empty-text="尚无发布版本。">
          <el-table-column label="版本" width="90"><template #default="{ row }"><span class="gateway-mono">v{{ row.version }}</span></template></el-table-column>
          <el-table-column label="状态" width="110"><template #default="{ row }"><el-tag :type="versionTagType(versionTone(row.status))" effect="light">{{ versionStatusLabel(row.status) }}</el-tag></template></el-table-column>
          <el-table-column label="说明" min-width="180"><template #default="{ row }"><span class="gateway-version-note" :title="row.note">{{ row.note || '—' }}</span></template></el-table-column>
          <el-table-column label="来源" width="90"><template #default="{ row }">{{ row.source_version ? `v${row.source_version}` : '—' }}</template></el-table-column>
          <el-table-column prop="published_by" label="发布人" min-width="110" />
          <el-table-column label="发布时间" min-width="155"><template #default="{ row }">{{ formatDateTime(row.published_at) }}</template></el-table-column>
          <el-table-column label="操作" width="100" fixed="right">
            <template #default="{ row }"><el-button text circle title="查看快照" @click="openDetail(row.version)"><Eye :size="14" /></el-button><el-button v-if="canPublish && row.status !== 'CURRENT'" text circle title="回滚到此版本" @click="rollback(row)"><RotateCcw :size="14" /></el-button></template>
          </el-table-column>
        </el-table>
      </AstraPanel>
    </div>

    <el-dialog :model-value="detailOpen" :title="detail ? `版本 v${detail.version} 快照` : '版本快照'" width="min(720px,100%)" data-testid="gateway-version-detail" @close="detailOpen = false"
      :close-on-click-modal="false"
      :close-on-press-escape="false"
      :show-close="true"
      append-to-body
      lock-scroll
      destroy-on-close
    >
      <p class="astra-dialog-subtitle">已脱敏：不含节点密文与 Key 摘要</p>
      <pre class="gateway-snapshot">{{ detail ? JSON.stringify(detail.snapshot, null, 2) : '' }}</pre>
    </el-dialog>
  </section>
</template>

<script setup lang="ts">
import { CheckCircle2, Eye, GitMerge, RefreshCw, Rocket, RotateCcw, TriangleAlert, XCircle } from 'lucide-vue-next'
import { computed, onMounted, ref } from 'vue'
import {
  gatewayApi,
  GatewayApiError,
  type GatewayConfigVersion,
  type GatewayConfigVersionDetail,
  type GatewayDraftValidation,
} from '@/api/gateway'
import AstraPanel from '@/components/astra/AstraPanel.vue'
import { confirmDialog } from '@/composables/useConfirm'
import { notify } from '@/composables/useToast'
import { useGatewayAuth } from '@/composables/useGatewayAuth'
import { errorMessage, formatDateTime, versionStatusLabel, versionTone } from '@/utils/gateway'

const { hasRole, disconnect } = useGatewayAuth()
const canPublish = computed(() => hasRole('publish'))
const draft = ref<GatewayDraftValidation | null>(null)
const versions = ref<GatewayConfigVersion[]>([])
const loading = ref(false)
const error = ref('')
const note = ref('')
const publishing = ref(false)
const reconciling = ref(false)
const detailOpen = ref(false)
const detail = ref<GatewayConfigVersionDetail | null>(null)

const countLabels: Record<string, string> = { pools: '资源池', nodes: '节点', routes: '路由', active_routes: '启用路由', keys: 'Key' }

function countLabel(key: string): string {
  return countLabels[key] ?? key
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    const [draftValue, versionList] = await Promise.all([gatewayApi.draftValidation(), gatewayApi.versions()])
    draft.value = draftValue
    versions.value = versionList
  } catch (reason) {
    if (reason instanceof GatewayApiError && reason.status === 401) { disconnect(); return }
    error.value = errorMessage(reason, '配置版本加载失败')
  } finally {
    loading.value = false
  }
}

async function publish() {
  publishing.value = true
  try {
    await gatewayApi.publish(note.value.trim())
    note.value = ''
    notify('配置已发布')
    await load()
  } catch (reason) {
    notify(errorMessage(reason, '发布失败'), 'error')
  } finally {
    publishing.value = false
  }
}

async function rollback(version: GatewayConfigVersion) {
  const confirmed = await confirmDialog({ title: '回滚配置', message: `确认以 v${version.version} 的内容生成新版本？进行中的请求继续使用原快照。`, confirmLabel: '回滚', danger: true })
  if (!confirmed) return
  try {
    await gatewayApi.rollback(version.version)
    notify(`已从 v${version.version} 生成新版本`)
    await load()
  } catch (reason) {
    notify(errorMessage(reason, '回滚失败'), 'error')
  }
}

async function reconcile() {
  reconciling.value = true
  try {
    const result = await gatewayApi.reconcile()
    notify(result.changed ? `已收敛 ${result.changed} 个未决发布` : '没有需要收敛的发布')
    await load()
  } catch (reason) {
    notify(errorMessage(reason, '对账失败'), 'error')
  } finally {
    reconciling.value = false
  }
}

async function openDetail(version: number) {
  detail.value = null
  detailOpen.value = true
  try {
    detail.value = await gatewayApi.version(version)
  } catch (reason) {
    notify(errorMessage(reason, '快照加载失败'), 'error')
    detailOpen.value = false
  }
}

function versionTagType(tone: string): 'success' | 'warning' | 'danger' | 'info' | 'primary' {
  if (tone === 'success' || tone === 'warning' || tone === 'danger' || tone === 'info') return tone
  return 'info'
}

onMounted(load)
</script>

<style scoped>
.gateway-two-col { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1.15fr); gap: 16px; align-items: start; }
.gateway-draft { display: grid; gap: 12px; }
.gateway-draft__counts { display: flex; flex-wrap: wrap; gap: 8px; }
.gateway-draft__counts span { display: grid; min-width: 74px; padding: 8px 10px; border: 1px solid var(--astra-border); border-radius: 8px; background: var(--astra-bg-base); }
.gateway-draft__counts small { color: var(--astra-text-muted); font-size: var(--astra-font-helper); }
.gateway-draft__counts b { margin-top: 2px; color: var(--astra-text-primary); font-size: var(--astra-font-size-18); font-variant-numeric: tabular-nums; }
.gateway-draft__list { display: grid; gap: 5px; margin: 0; padding: 0; list-style: none; font-size: var(--astra-font-helper); }
.gateway-draft__list li { display: flex; align-items: center; gap: 6px; }
.gateway-draft__list em { margin-left: auto; color: var(--astra-text-muted); font-style: normal; }
.gateway-draft__list--error { color: var(--astra-danger); }
.gateway-draft__list--warn { color: var(--astra-warning); }
.gateway-publish { display: flex; gap: 8px; }
.gateway-publish input { flex: 1; min-height: var(--astra-control-height); padding: 0 11px; color: var(--astra-text-primary); border: 1px solid var(--astra-border); border-radius: 8px; background: var(--astra-bg-base); }
.gateway-note { display: flex; align-items: center; gap: 6px; margin: 0; color: var(--astra-text-muted); font-size: var(--astra-font-helper); }
.gateway-note .ok { color: var(--astra-success); }
.gateway-version-table { min-width: 620px; }
.gateway-version-note { max-width: 220px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.gateway-mono { font-family: var(--astra-font-family); font-size: var(--astra-font-helper); }
.gateway-time { white-space: nowrap; font-size: var(--astra-font-helper); }
.gateway-snapshot { max-height: 60vh; margin: 0; padding: 12px; overflow: auto; color: var(--astra-text-secondary); border: 1px solid var(--astra-border); border-radius: 9px; background: var(--astra-bg-base); font: var(--astra-font-helper)/1.5 var(--astra-font-family); white-space: pre-wrap; }
@media (max-width: 1000px) { .gateway-two-col { grid-template-columns: 1fr; } }
</style>