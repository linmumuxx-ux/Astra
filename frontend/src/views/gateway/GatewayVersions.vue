<template>
  <section class="gateway-section">
    <header class="gateway-section__head">
      <div><h3>配置草稿与版本</h3><p>发布前校验全部引用，生成不可变快照；回滚会以历史快照生成新版本。</p></div>
      <div class="gateway-section__actions">
        <button type="button" class="button" :disabled="loading" @click="load"><RefreshCw :size="14" :class="{ spin: loading }" />刷新</button>
        <button v-if="canPublish" type="button" class="button" :disabled="reconciling" @click="reconcile"><GitMerge :size="14" />发布对账</button>
      </div>
    </header>

    <p v-if="error" class="gateway-alert"><TriangleAlert :size="15" />{{ error }}<button type="button" @click="load">重试</button></p>

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
            <input v-model="note" placeholder="发布说明（可选）" />
            <button type="button" class="button button--primary" :disabled="publishing || !draft.valid" @click="publish"><Rocket :size="14" />{{ publishing ? '发布中…' : '发布新版本' }}</button>
          </div>
          <p v-else class="gateway-note">当前凭据缺少 publish 角色，只能查看。</p>
        </div>
        <div v-else class="gateway-placeholder">{{ loading ? '加载中…' : '暂无草稿数据' }}</div>
      </AstraPanel>

      <AstraPanel title="版本历史" :subtitle="`共 ${versions.length} 个版本`" flush>
        <div class="table-wrap">
          <table class="gateway-version-table">
            <thead><tr><th>版本</th><th>状态</th><th>说明</th><th>来源</th><th>发布人</th><th>发布时间</th><th class="gateway-col-actions">操作</th></tr></thead>
            <tbody>
              <tr v-for="version in versions" :key="version.id">
                <td class="gateway-mono">v{{ version.version }}</td>
                <td><span class="status-badge" :data-tone="versionTone(version.status)">{{ versionStatusLabel(version.status) }}</span></td>
                <td class="gateway-version-note" :title="version.note">{{ version.note || '—' }}</td>
                <td>{{ version.source_version ? `v${version.source_version}` : '—' }}</td>
                <td>{{ version.published_by }}</td>
                <td class="gateway-time">{{ formatDateTime(version.published_at) }}</td>
                <td class="gateway-col-actions">
                  <div class="gateway-row-actions">
                    <button class="gateway-icon-btn" type="button" title="查看快照" @click="openDetail(version.version)"><Eye :size="14" /></button>
                    <button v-if="canPublish && version.status !== 'CURRENT'" class="gateway-icon-btn" type="button" title="回滚到此版本" @click="rollback(version)"><RotateCcw :size="14" /></button>
                  </div>
                </td>
              </tr>
              <tr v-if="!versions.length"><td colspan="7" class="empty-cell">尚无发布版本。</td></tr>
            </tbody>
          </table>
        </div>
      </AstraPanel>
    </div>

    <AstraDialog :open="detailOpen" :title="detail ? `版本 v${detail.version} 快照` : '版本快照'" subtitle="已脱敏：不含节点密文与 Key 摘要" :busy="false" width="min(720px,100%)" testid="gateway-version-detail" @close="detailOpen = false">
      <pre class="gateway-snapshot">{{ detail ? JSON.stringify(detail.snapshot, null, 2) : '' }}</pre>
    </AstraDialog>
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
import AstraDialog from '@/components/astra/AstraDialog.vue'
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