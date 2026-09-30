<template>
  <section class="gateway-self" data-testid="gateway-self">
    <GatewayHeaderActions>
      <ElRadioGroup
        v-if="connected"
        v-model="statsWindow"
        aria-label="统计窗口"
        data-testid="gateway-self-window"
      >
        <ElRadioButton v-for="item in windows" :key="item.id" :value="item.id">{{ item.label }}</ElRadioButton>
      </ElRadioGroup>
      <ElButton
        v-if="connected"
        :loading="loading"
        :icon="RefreshCw"
        data-testid="gateway-self-refresh"
        @click="refresh"
      >刷新</ElButton>
      <ElButton v-if="connected" :icon="LogOut" data-testid="gateway-self-clear" @click="disconnect">退出去用量</ElButton>
    </GatewayHeaderActions>

    <ElAlert
      v-if="authError"
      type="warning"
      show-icon
      :closable="false"
      :title="authError"
      data-testid="gateway-self-auth-error"
    />

    <ElCard v-if="!connected" shadow="never" class="gateway-self__connect" data-testid="gateway-self-connect">
      <ElForm label-position="top" data-testid="gateway-self-form" @submit.prevent="connect">
        <ElFormItem label="Gateway Key（agw_ 开头）">
          <ElInput
            v-model="input"
            type="password"
            autocomplete="off"
            spellcheck="false"
            placeholder="粘贴你自己的 Gateway Key"
            data-testid="gateway-self-key-input"
          />
        </ElFormItem>
        <ElButton
          native-type="submit"
          type="primary"
          :loading="loading"
          data-testid="gateway-self-submit"
        >查看用量</ElButton>
        <ElText type="info" class="gateway-self__note">
          Key 只写入当前会话的 sessionStorage，不随页面构建产物分发；退出去用量后立即清除。
        </ElText>
      </ElForm>
    </ElCard>

    <template v-else>
      <ElAlert
        v-if="error"
        type="error"
        show-icon
        :closable="false"
        :title="error"
        data-testid="gateway-self-error"
      >
        <ElButton type="primary" data-testid="gateway-self-retry" @click="refresh">重试</ElButton>
      </ElAlert>

      <section class="gateway-self__metrics" aria-label="自身用量指标">
        <ElCard v-for="metric in metricCards" :key="metric.id" shadow="never" :data-testid="`gateway-self-metric-${metric.id}`">
          <ElStatistic :title="metric.label" :value="metric.value as number" />
          <p class="gateway-self__metric-hint">{{ metric.hint }}</p>
        </ElCard>
      </section>

      <ElCard shadow="never" class="gateway-self__trend" data-testid="gateway-self-trend">
        <template #header>
          <div class="gateway-self__card-head">
            <div>
              <h4>Token 趋势</h4>
              <ElText type="info">{{ windowLabel }}</ElText>
            </div>
            <span class="gateway-self__legend"><i />输入<i class="gateway-self__legend--output" />输出</span>
          </div>
        </template>
        <GatewayTrendChart v-if="stats" :buckets="stats.trend" mode="tokens" />
        <ElEmpty v-else :image-size="52" :description="loading ? '加载中…' : '暂无数据'" />
      </ElCard>

      <ElCard shadow="never">
        <template #header>
          <div class="gateway-self__card-head">
            <div>
              <h4>调用记录</h4>
              <ElText type="info">只包含该 Key 自身的调用元数据与测量值</ElText>
            </div>
          </div>
        </template>

        <ElTable
          v-loading="loading"
          :data="page.items"
          row-key="id"
          max-height="calc(100vh - 330px)"
          element-loading-text="正在加载调用记录"
          data-testid="gateway-self-table"
        >
          <ElTableColumn label="时间" width="116">
            <template #default="{ row }"><span class="gateway-self__num">{{ formatDateTime(row.started_at) }}</span></template>
          </ElTableColumn>
          <ElTableColumn label="模型" min-width="140" show-overflow-tooltip>
            <template #default="{ row }">{{ row.model ?? '—' }}</template>
          </ElTableColumn>
          <ElTableColumn label="节点" min-width="130" show-overflow-tooltip>
            <template #default="{ row }"><span class="gateway-self__mono">{{ row.node_id ?? '—' }}</span></template>
          </ElTableColumn>
          <ElTableColumn label="状态" min-width="150">
            <template #default="{ row }">
              <ElTag v-if="row.error_code" type="danger" :title="row.error_code">{{ row.error_code }}</ElTag>
              <ElTag v-else :type="row.status_code && row.status_code < 400 ? 'success' : 'warning'">{{ row.status_code ?? '—' }}</ElTag>
            </template>
          </ElTableColumn>
          <ElTableColumn label="流式" width="90">
            <template #default="{ row }">{{ row.streaming ? 'SSE' : '普通' }}</template>
          </ElTableColumn>
          <ElTableColumn label="Token（入 / 出 / 总）" width="140">
            <template #default="{ row }"><span class="gateway-self__num">{{ tokenText(row as GatewayRequestLog) }}</span></template>
          </ElTableColumn>
          <ElTableColumn label="TTFT" width="100">
            <template #default="{ row }"><span class="gateway-self__num">{{ latencyText(row.ttft_ms) }}</span></template>
          </ElTableColumn>
          <ElTableColumn label="总时长" width="100">
            <template #default="{ row }"><span class="gateway-self__num">{{ latencyText(row.duration_ms) }}</span></template>
          </ElTableColumn>
          <template #empty>
            <ElEmpty v-if="!loading" :image-size="64" description="暂无调用记录。" />
          </template>
        </ElTable>

        <footer class="gateway-self__footer">
          <ElText type="info" data-testid="gateway-self-total">共 {{ page.total }} 条 · 第 {{ page.page }} 页</ElText>
          <div class="gateway-self__paging">
            <ElSelect v-model="pageSize" class="gateway-self__size" aria-label="每页条数" :disabled="loading">
              <ElOption v-for="size in pageSizeOptions" :key="size" :value="size" :label="`每页 ${size}`" />
            </ElSelect>
            <ElPagination
              :current-page="page.page"
              :page-size="page.page_size"
              :total="page.total"
              layout="prev, pager, next"
              :disabled="loading"
              aria-label="调用记录分页"
              data-testid="gateway-self-pagination"
              @current-change="go"
            />
          </div>
        </footer>
      </ElCard>
    </template>
  </section>
</template>

<script setup lang="ts">
import { LogOut, RefreshCw } from 'lucide-vue-next'
import { computed, onMounted, ref, watch } from 'vue'
import {
  ElAlert,
  ElButton,
  ElCard,
  ElEmpty,
  ElForm,
  ElFormItem,
  ElInput,
  ElOption,
  ElPagination,
  ElRadioButton,
  ElRadioGroup,
  ElSelect,
  ElSpace,
  ElStatistic,
  ElTable,
  ElTableColumn,
  ElTag,
  ElText,
  vLoading,
} from 'element-plus'
import {
  clearSelfKey,
  gatewayApi,
  GatewayApiError,
  getSelfKey,
  setSelfKey,
  type GatewayRequestLog,
  type GatewayRequestPage,
  type GatewayScopeStats,
  type GatewayStatsWindow,
} from '@/api/gateway'
import { formatTokens } from '@/utils/format'
import { errorMessage, formatDateTime, formatPercent } from '@/utils/gateway'
import GatewayTrendChart from '@/views/gateway/GatewayTrendChart.vue'
import GatewayHeaderActions from '@/views/gateway/GatewayHeaderActions.vue'

const windows: Array<{ id: GatewayStatsWindow; label: string }> = [
  { id: 'hour', label: '本小时' },
  { id: 'today', label: '今日' },
  { id: '7d', label: '近 7 天' },
  { id: '30d', label: '近 30 天' },
]
const pageSizeOptions = [20, 50, 100]
// Key 原文只留在 @/api/gateway 的会话存储里，组件只持有布尔连接态，
// 避免它进入模板、统计、日志或任何可回显的位置。
const connected = ref(Boolean(getSelfKey()))
const input = ref('')
const statsWindow = ref<GatewayStatsWindow>('today')
const stats = ref<GatewayScopeStats | null>(null)
const page = ref<GatewayRequestPage>({ items: [], total: 0, page: 1, page_size: 50 })
const pageSize = ref(50)
const loading = ref(false)
const error = ref('')
const authError = ref('')

const windowLabel = computed(() => windows.find((item) => item.id === statsWindow.value)?.label ?? '')

const metricCards = computed(() => {
  const current = stats.value
  return [
    { id: 'requests', label: '请求数', value: current?.requests ?? '—', hint: '窗口内你的调用总量' },
    { id: 'success-rate', label: '成功率', value: formatPercent(current?.success_rate), hint: '2xx/3xx 且未被中断' },
    { id: 'tokens', label: '总 Token', value: current ? formatTokens(current.total_tokens) : '—', hint: '输入 + 输出' },
    { id: 'unknown', label: '未知用量', value: current?.unknown_usage_requests ?? '—', hint: '下游未返回 usage' },
    { id: 'active', label: '当前并发', value: current?.active ?? '—', hint: '你正在进行的请求' },
    { id: 'window', label: '窗口', value: windowLabel.value, hint: '自然小时 / 自然日' },
  ]
})

function tokenText(row: GatewayRequestLog): string {
  if (!row.usage_known) return 'unknown'
  return `${row.input_tokens ?? 0} / ${row.output_tokens ?? 0} / ${row.total_tokens ?? 0}`
}

function latencyText(value: number | null): string {
  return value === null || value === undefined ? '—' : `${value} ms`
}

function resetResult(): void {
  stats.value = null
  page.value = { items: [], total: 0, page: 1, page_size: pageSize.value }
}

function fail(reason: unknown, withStats: boolean): void {
  // 自助用量用的是 Gateway Key 自己，401 只作废该 Key，不影响控制面会话。
  if (reason instanceof GatewayApiError && reason.status === 401) {
    disconnect()
    authError.value = 'Gateway Key 无效或已失效，请重新输入。'
    return
  }
  if (withStats) stats.value = null
  page.value = { items: [], total: 0, page: 1, page_size: pageSize.value }
  error.value = errorMessage(reason, '用量加载失败，请确认 Key 有效')
}

async function refresh(): Promise<void> {
  if (!connected.value) return
  loading.value = true
  error.value = ''
  try {
    // 统计与调用记录一起更新、一起清空，避免半新半旧的用量视图。
    const [statsValue, requestValue] = await Promise.all([
      gatewayApi.selfStats(statsWindow.value),
      gatewayApi.selfRequests({ page: page.value.page, page_size: pageSize.value }),
    ])
    stats.value = statsValue
    page.value = requestValue
  } catch (reason) {
    fail(reason, true)
  } finally {
    loading.value = false
  }
}

async function loadRequests(target: number): Promise<void> {
  loading.value = true
  try {
    page.value = await gatewayApi.selfRequests({ page: target, page_size: pageSize.value })
  } catch (reason) {
    fail(reason, false)
  } finally {
    loading.value = false
  }
}

function connect(): void {
  const value = input.value.trim()
  if (!value) {
    authError.value = '请输入 Gateway Key'
    return
  }
  setSelfKey(value)
  input.value = ''
  connected.value = true
  authError.value = ''
  void refresh()
}

function disconnect(): void {
  clearSelfKey()
  connected.value = false
  input.value = ''
  error.value = ''
  resetResult()
}

function go(target: number): void {
  void loadRequests(target)
}

watch(statsWindow, () => {
  if (connected.value) void refresh()
})
watch(pageSize, () => {
  if (connected.value) void loadRequests(1)
})

onMounted(() => {
  if (connected.value) void refresh()
})
</script>

<style scoped>
.gateway-self { display: grid; gap: 12px; }
.gateway-self__connect { max-width: 520px; }
.gateway-self__note { display: block; margin-top: 10px; }
.gateway-self__metrics { display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); gap: 12px; }
.gateway-self__metrics :deep(.el-statistic__head) { color: var(--astra-text-muted); font-size: var(--astra-font-control); }
.gateway-self__metrics :deep(.el-statistic__content) { color: var(--astra-text-primary); font-size: var(--astra-font-subtitle); font-weight: var(--astra-weight-bold); }
.gateway-self__metric-hint { margin: 4px 0 0; color: var(--astra-text-muted); font-size: var(--astra-font-helper); }
.gateway-self__card-head { display: flex; align-items: flex-start; gap: 12px; }
.gateway-self__card-head > div { margin-right: auto; }
.gateway-self__card-head h4 { margin: 0; color: var(--astra-text-primary); font-size: var(--astra-font-control); }
.gateway-self__legend { display: inline-flex; align-items: center; gap: 5px; color: var(--astra-text-muted); font-size: var(--astra-font-helper); }
.gateway-self__legend i { display: inline-block; width: 8px; height: 8px; border-radius: 2px; background: #3d8ff0; }
.gateway-self__legend .gateway-self__legend--output { background: #159d65; }
.gateway-self__mono { font-family: var(--astra-font-family); font-size: var(--astra-font-helper); }
.gateway-self__num { white-space: nowrap; font-size: var(--astra-font-helper); font-variant-numeric: tabular-nums; }
.gateway-self__footer { display: flex; align-items: center; justify-content: space-between; gap: 16px; padding-top: 12px; }
.gateway-self__paging { display: flex; align-items: center; gap: 10px; }
.gateway-self__size { width: 116px; }
@media (max-width: 1280px) { .gateway-self__metrics { grid-template-columns: repeat(3, minmax(0, 1fr)); } }
@media (max-width: 760px) { .gateway-self__metrics { grid-template-columns: repeat(2, minmax(0, 1fr)); } .gateway-self__footer { flex-direction: column; align-items: flex-start; } }
</style>
