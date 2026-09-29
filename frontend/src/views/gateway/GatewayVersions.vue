<template>
  <section class="gateway-versions" data-testid="gateway-versions">
    <header class="gateway-versions__bar">
      <div class="gateway-versions__intro">
        <h3>配置草稿与版本</h3>
        <ElText type="info">发布前校验全部引用，生成不可变快照；回滚会以历史快照生成新版本。</ElText>
      </div>
      <ElSpace :size="8">
        <ElButton :loading="loading" :icon="RefreshCw" data-testid="gateway-versions-refresh" @click="load">刷新</ElButton>
        <ElButton v-if="canPublish" :loading="reconciling" :icon="GitMerge" data-testid="gateway-versions-reconcile" @click="reconcile">发布对账</ElButton>
      </ElSpace>
    </header>

    <ElAlert v-if="error" type="error" show-icon :closable="false" :title="error" data-testid="gateway-versions-error">
      <ElButton type="primary" data-testid="gateway-versions-retry" @click="load">重试</ElButton>
    </ElAlert>

    <div class="gateway-versions__grid">
      <ElCard shadow="never" data-testid="gateway-draft-card">
        <template #header>
          <div class="gateway-versions__card-head">
            <div class="gateway-versions__card-title">
              <h4>草稿校验</h4>
              <ElText type="info">{{ draftSubtitle }}</ElText>
            </div>
          </div>
        </template>

        <div v-if="draft" class="gateway-draft">
          <ElDescriptions :column="3" border data-testid="gateway-draft-counts">
            <ElDescriptionsItem v-for="(value, key) in draft.counts" :key="key" :label="countLabel(String(key))">
              {{ value }}
            </ElDescriptionsItem>
          </ElDescriptions>

          <template v-if="draft.errors.length">
            <ElAlert
              type="error"
              show-icon
              :closable="false"
              :title="`校验未通过：发现 ${draft.errors.length} 项错误，修复后才可发布`"
              data-testid="gateway-draft-fail"
            />
            <ElTable :data="draft.errors" data-testid="gateway-draft-errors">
              <ElTableColumn label="错误码" prop="code" width="140" />
              <ElTableColumn label="说明" prop="message" min-width="200" show-overflow-tooltip />
              <ElTableColumn label="资源" width="170" show-overflow-tooltip>
                <template #default="{ row }">{{ row.resource_type ?? '—' }} / {{ row.resource_id ?? '—' }}</template>
              </ElTableColumn>
            </ElTable>
          </template>

          <ElAlert v-if="draft.warnings.length" type="warning" show-icon :closable="false" data-testid="gateway-draft-warnings">
            <template #title>
              <div v-for="(item, index) in draft.warnings" :key="index">{{ item }}</div>
            </template>
          </ElAlert>

          <ElAlert
            v-if="draft.valid && !draft.warnings.length"
            type="success"
            show-icon
            :closable="false"
            title="草稿与当前引用一致，可安全发布。"
            data-testid="gateway-draft-ok"
          />

          <div v-if="canPublish" class="gateway-publish">
            <ElInput v-model="note" placeholder="发布说明（可选）" data-testid="gateway-publish-note" />
            <ElButton
              type="primary"
              :icon="Rocket"
              :loading="publishing"
              :disabled="!draft.valid"
              data-testid="gateway-publish"
              @click="publish"
            >发布新版本</ElButton>
          </div>
          <ElText v-else type="info" data-testid="gateway-publish-locked">当前凭据缺少 publish 角色，只能查看。</ElText>
        </div>
        <ElEmpty v-else :image-size="64" :description="loading ? '加载中…' : '暂无草稿数据'" />
      </ElCard>

      <ElCard shadow="never" data-testid="gateway-version-history-card">
        <template #header>
          <div class="gateway-versions__card-head">
            <div class="gateway-versions__card-title">
              <h4>版本历史</h4>
              <ElText type="info">共 {{ versions.length }} 个版本</ElText>
            </div>
          </div>
        </template>

        <ElTable
          v-loading="loading"
          :data="versions"
          row-key="id"
          element-loading-text="正在加载版本历史"
          data-testid="gateway-versions-table"
        >
          <ElTableColumn label="版本" width="80">
            <template #default="{ row }"><span class="gateway-mono">v{{ row.version }}</span></template>
          </ElTableColumn>
          <ElTableColumn label="状态" width="96">
            <template #default="{ row }">
              <ElTag :type="tagType(versionTone(row.status))">{{ versionStatusLabel(row.status) }}</ElTag>
            </template>
          </ElTableColumn>
          <ElTableColumn label="说明" min-width="160" show-overflow-tooltip>
            <template #default="{ row }">{{ row.note || '—' }}</template>
          </ElTableColumn>
          <ElTableColumn label="来源" width="80">
            <template #default="{ row }">{{ row.source_version ? `v${row.source_version}` : '—' }}</template>
          </ElTableColumn>
          <ElTableColumn label="发布人" prop="published_by" width="110" show-overflow-tooltip />
          <ElTableColumn label="发布时间" width="150">
            <template #default="{ row }">{{ formatDateTime(row.published_at) }}</template>
          </ElTableColumn>
          <ElTableColumn label="操作" width="88" fixed="right">
            <template #default="{ row }">
              <ElSpace :size="4">
                <ElTooltip content="查看快照" placement="top">
                  <ElButton circle type="primary" :icon="Eye" :aria-label="`查看 v${row.version} 快照`" @click="openDetail(row.version)" />
                </ElTooltip>
                <ElTooltip v-if="canPublish && row.status !== 'CURRENT'" content="回滚到此版本（以历史快照生成新版本）" placement="top">
                  <ElButton
                    circle
                    type="danger"
                    :icon="RotateCcw"
                    :aria-label="`回滚到 v${row.version}`"
                    :disabled="rolling"
                    @click="rollback(row as GatewayConfigVersion)"
                  />
                </ElTooltip>
              </ElSpace>
            </template>
          </ElTableColumn>
          <template #empty>
            <ElEmpty v-if="!loading" :image-size="64" description="尚无发布版本。" />
          </template>
        </ElTable>
      </ElCard>
    </div>

    <ElDialog
      v-model="detailOpen"
      class="gateway-version-snapshot"
      data-testid="gateway-version-detail"
      :title="detail ? `版本 v${detail.version} 快照` : '版本快照'"
      width="min(720px, 92%)"
    >
      <ElText type="info">已脱敏：不含节点密文与 Key 摘要</ElText>
      <ElDescriptions v-if="detail" :column="4" border class="gateway-snapshot__meta">
        <ElDescriptionsItem label="状态">
          <ElTag :type="tagType(versionTone(detail.status))">{{ versionStatusLabel(detail.status) }}</ElTag>
        </ElDescriptionsItem>
        <ElDescriptionsItem label="来源">{{ detail.source_version ? `v${detail.source_version}` : '—' }}</ElDescriptionsItem>
        <ElDescriptionsItem label="发布人">{{ detail.published_by }}</ElDescriptionsItem>
        <ElDescriptionsItem label="发布时间">{{ formatDateTime(detail.published_at) }}</ElDescriptionsItem>
      </ElDescriptions>
      <pre class="gateway-snapshot__json">{{ detail ? JSON.stringify(detail.snapshot, null, 2) : '' }}</pre>
    </ElDialog>
  </section>
</template>

<script setup lang="ts">
import { Eye, GitMerge, RefreshCw, Rocket, RotateCcw } from 'lucide-vue-next'
import { computed, onMounted, ref } from 'vue'
import {
  ElAlert,
  ElButton,
  ElCard,
  ElDescriptions,
  ElDescriptionsItem,
  ElDialog,
  ElEmpty,
  ElInput,
  ElSpace,
  ElTable,
  ElTableColumn,
  ElTag,
  ElText,
  ElTooltip,
  vLoading,
} from 'element-plus'
import {
  gatewayApi,
  GatewayApiError,
  type GatewayConfigVersion,
  type GatewayConfigVersionDetail,
  type GatewayDraftValidation,
} from '@/api/gateway'
import { confirmDialog } from '@/composables/useConfirm'
import { notify } from '@/composables/useToast'
import { useGatewayAuth } from '@/composables/useGatewayAuth'
import {
  errorMessage,
  formatDateTime,
  type GatewayTone,
  versionStatusLabel,
  versionTone,
} from '@/utils/gateway'

const { hasRole, disconnect } = useGatewayAuth()
const canPublish = computed(() => hasRole('publish'))
const draft = ref<GatewayDraftValidation | null>(null)
const versions = ref<GatewayConfigVersion[]>([])
const loading = ref(false)
const error = ref('')
const note = ref('')
const publishing = ref(false)
const reconciling = ref(false)
const rolling = ref(false)
const detailOpen = ref(false)
const detail = ref<GatewayConfigVersionDetail | null>(null)

const countLabels: Record<string, string> = { pools: '资源池', nodes: '节点', routes: '路由', active_routes: '启用路由', keys: 'Key' }

const draftSubtitle = computed(() => {
  if (!draft.value) return ''
  return draft.value.valid ? '校验通过，可发布' : `发现 ${draft.value.errors.length} 项错误`
})

function countLabel(key: string): string {
  return countLabels[key] ?? key
}

function tagType(tone: GatewayTone): 'success' | 'warning' | 'danger' | 'info' {
  if (tone === 'success') return 'success'
  if (tone === 'warning') return 'warning'
  if (tone === 'danger') return 'danger'
  return 'info'
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
  const confirmed = await confirmDialog({
    title: '回滚配置',
    message: `确认以 v${version.version} 的内容生成新版本？进行中的请求继续使用原快照。`,
    confirmLabel: '回滚',
    danger: true,
  })
  if (!confirmed) return
  rolling.value = true
  try {
    await gatewayApi.rollback(version.version)
    notify(`已从 v${version.version} 生成新版本`)
    await load()
  } catch (reason) {
    notify(errorMessage(reason, '回滚失败'), 'error')
  } finally {
    rolling.value = false
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
.gateway-versions { display: grid; gap: 12px; }
.gateway-versions__bar { display: flex; align-items: center; gap: 12px; }
.gateway-versions__intro { margin-right: auto; }
.gateway-versions__intro h3 { margin: 0; color: var(--astra-text-primary); }
.gateway-versions__grid { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1.2fr); gap: 12px; align-items: start; }
.gateway-versions__card-head { display: flex; align-items: center; gap: 12px; }
.gateway-versions__card-title { display: grid; gap: 2px; margin-right: auto; }
.gateway-versions__card-title h4 { margin: 0; color: var(--astra-text-primary); }
.gateway-draft { display: grid; gap: 12px; }
.gateway-publish { display: flex; gap: 8px; }
.gateway-mono { font-family: var(--astra-font-family); font-size: var(--astra-font-helper); }
.gateway-snapshot__meta { margin-top: 12px; }
.gateway-snapshot__json { max-height: 50vh; margin: 12px 0 0; padding: 12px; overflow: auto; color: var(--astra-text-secondary); border: 1px solid var(--astra-border); border-radius: 9px; background: var(--astra-bg-base); font: var(--astra-font-helper)/1.5 var(--astra-font-family); white-space: pre-wrap; }
@media (max-width: 1100px) { .gateway-versions__grid { grid-template-columns: 1fr; } }
</style>
