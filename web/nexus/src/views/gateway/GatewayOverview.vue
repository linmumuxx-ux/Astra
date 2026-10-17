<template>
  <section ref="root" class="gateway-overview" data-testid="gateway-overview">
    <GatewayHeaderActions>
      <ElRadioGroup v-model="trendWindow" data-testid="gateway-window-switch">
        <ElRadioButton value="1h">近 1 小时</ElRadioButton>
        <ElRadioButton value="15m">近 15 分钟</ElRadioButton>
      </ElRadioGroup>
      <ElButton :loading="loading" :icon="RefreshCw" data-testid="gateway-overview-refresh" @click="load(false)">刷新</ElButton>
    </GatewayHeaderActions>

    <ElAlert v-if="error" type="error" show-icon :closable="false" :title="error" data-testid="gateway-overview-error">
      <ElButton type="primary" data-testid="gateway-overview-retry" @click="load(false)">重试</ElButton>
    </ElAlert>

    <section
      class="gateway-overview__verdict"
      :data-status="summary?.status ?? 'unknown'"
      data-testid="gateway-health-bar"
    >
      <div>
        <p class="gateway-overview__eyebrow">服务健康</p>
        <h3 data-testid="gateway-health-status">{{ statusLabel }}</h3>
        <p class="gateway-overview__impact" data-testid="gateway-health-impact">{{ impactText }}</p>
        <p v-if="reasonText" class="gateway-overview__reasons">{{ reasonText }}</p>
      </div>
      <ElButton type="primary" plain data-testid="gateway-show-abnormal" @click="showAbnormal">查看异常</ElButton>
    </section>

    <section class="gateway-overview__metrics" aria-label="核心指标">
      <ElCard v-for="metric in primaryCards" :key="metric.id" shadow="never" :data-testid="`gateway-metric-${metric.id}`">
        <p class="gateway-overview__metric-label">{{ metric.label }}</p>
        <p class="gateway-overview__metric-value">{{ metric.value }}</p>
        <p class="gateway-overview__metric-hint">{{ metric.hint }}</p>
      </ElCard>
    </section>

    <section class="gateway-overview__metrics gateway-overview__metrics--secondary" aria-label="辅助指标">
      <ElCard v-for="metric in secondaryCards" :key="metric.id" shadow="never" :data-testid="`gateway-metric-${metric.id}`">
        <p class="gateway-overview__metric-label">{{ metric.label }}</p>
        <p class="gateway-overview__metric-value gateway-overview__metric-value--secondary">{{ metric.value }}</p>
        <p class="gateway-overview__metric-hint">{{ metric.hint }}</p>
      </ElCard>
    </section>

    <div class="gateway-overview__main">
      <ElCard shadow="never" data-testid="gateway-overview-nodes">
        <template #header>
          <div class="gateway-overview__card-header">
            <div>
              <h4>节点与资源池</h4>
              <ElText>异常在前。健康节点默认收起。指标与上方卡片同一窗口。</ElText>
            </div>
            <ElCheckbox v-model="abnormalOnly" data-testid="gateway-abnormal-only">只看异常</ElCheckbox>
          </div>
        </template>
        <ElTable :data="visibleRows" row-key="node_id" :empty-text="tableEmpty">
          <ElTableColumn label="节点" min-width="140">
            <template #default="{ row }">
              <RouterLink class="gateway-overview__node" :to="`/gateway/nodes/${row.node_id}`">{{ row.name }}</RouterLink>
              <span class="gateway-overview__sub">{{ row.pool_name ?? '未分配' }}</span>
            </template>
          </ElTableColumn>
          <ElTableColumn label="健康" width="88">
            <template #default="{ row }"><ElTag :type="healthTag(row.health)">{{ row.health_label }}</ElTag></template>
          </ElTableColumn>
          <ElTableColumn label="调度" width="100">
            <template #default="{ row }"><ElTag :type="schedulingTag(row.scheduling)">{{ row.scheduling_label }}</ElTag></template>
          </ElTableColumn>
          <ElTableColumn label="负载" min-width="130">
            <template #default="{ row }">{{ loadText(row as GatewayNodeMetric) }}</template>
          </ElTableColumn>
          <ElTableColumn label="QPS" width="88">
            <template #default="{ row }">{{ numberText(row.qps, 2) }}</template>
          </ElTableColumn>
          <ElTableColumn label="错误率" width="96">
            <template #default="{ row }">{{ percentText(row.error_rate) }}</template>
          </ElTableColumn>
          <ElTableColumn label="TTFT P95" width="110">
            <template #default="{ row }">{{ row.ttft_p95_ms === null ? '暂无数据' : `${Math.round(row.ttft_p95_ms)} ms` }}</template>
          </ElTableColumn>
          <ElTableColumn label="日志" width="72">
            <template #default="{ row }">
              <ElButton link type="primary" @click="openNodeLogs(row as GatewayNodeMetric)">查看</ElButton>
            </template>
          </ElTableColumn>
        </ElTable>
        <div v-if="!abnormalOnly && healthyRows.length" class="gateway-overview__collapse">
          <ElButton text type="primary" data-testid="gateway-toggle-healthy" @click="showHealthy = !showHealthy">
            {{ showHealthy ? '收起' : '展开' }}健康节点 {{ healthyRows.length }}
          </ElButton>
        </div>
      </ElCard>

      <ElCard shadow="never" class="gateway-overview__events" data-testid="gateway-overview-events">
        <template #header>
          <div class="gateway-overview__card-header">
            <div><h4>最近事件</h4><ElText>运行态与配置审计。点击按对象和时间打开调用日志。</ElText></div>
          </div>
        </template>
        <ul v-if="events.length" class="gateway-overview__event-list">
          <li v-for="event in events" :key="event.id">
            <button type="button" @click="openEventLogs(event)">
              <ElTag size="small" :type="event.source === 'config' ? 'info' : 'warning'">{{ event.source === 'config' ? '配置' : '运行' }}</ElTag>
              <span>{{ event.summary }}</span>
              <time>{{ formatDateTime(event.created_at) }}</time>
            </button>
          </li>
        </ul>
        <ElEmpty v-else :image-size="52" description="暂无事件" />
      </ElCard>
    </div>

    <ElCard shadow="never" data-testid="gateway-overview-trend">
      <template #header>
        <div class="gateway-overview__card-header">
          <div>
            <h4>TTFT P95 趋势</h4>
            <ElText>分桶内单独计算 P95。整段标题值是窗口内全部样本的 P95。</ElText>
          </div>
          <div class="gateway-overview__trend-tools">
            <ElSelect v-model="groupBy" class="gateway-overview__group" aria-label="趋势分组">
              <ElOption value="none" label="全部" />
              <ElOption value="model" label="按模型" />
              <ElOption value="node" label="按节点" />
            </ElSelect>
            <ElSelect v-if="seriesOptions.length > 1" v-model="seriesKey" class="gateway-overview__group" aria-label="趋势序列">
              <ElOption v-for="item in seriesOptions" :key="item.key" :value="item.key" :label="item.label" />
            </ElSelect>
          </div>
        </div>
      </template>
      <ElAlert
        v-if="trendError"
        type="warning"
        show-icon
        :closable="false"
        :title="trendError"
        data-testid="gateway-trend-error"
      />
      <p v-if="trendStale" class="gateway-overview__trend-stale" data-testid="gateway-trend-stale">{{ trendStale }}</p>
      <p class="gateway-overview__trend-headline">窗口 TTFT P95：{{ headlineTtft }} · 输出 TPS P95：{{ headlineTps }}</p>
      <GatewayTrendChart v-if="trendPoints" :points="trendPoints" mode="value" value-name="TTFT P95" />
      <ElEmpty v-else :image-size="52" description="暂无数据" />
    </ElCard>
  </section>
</template>

<script setup lang="ts">
import { RefreshCw } from 'lucide-vue-next'
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { RouterLink, useRouter } from 'vue-router'
import {
  ElAlert,
  ElButton,
  ElCard,
  ElCheckbox,
  ElEmpty,
  ElOption,
  ElRadioButton,
  ElRadioGroup,
  ElSelect,
  ElTable,
  ElTableColumn,
  ElTag,
  ElText,
} from 'element-plus'
import {
  gatewayApi,
  type GatewayHealthSummary,
  type GatewayNodeMetric,
  type GatewayOpsEvent,
  type GatewayTrend,
} from '@/api/gateway'
import { errorMessage, formatDateTime } from '@/utils/gateway'
import GatewayHeaderActions from '@/views/gateway/GatewayHeaderActions.vue'
import GatewayTrendChart from '@/views/gateway/GatewayTrendChart.vue'

const router = useRouter()
const root = ref<HTMLElement | null>(null)
const summary = ref<GatewayHealthSummary | null>(null)
const rows = ref<GatewayNodeMetric[]>([])
const events = ref<GatewayOpsEvent[]>([])
const trend = ref<GatewayTrend | null>(null)
const trendError = ref('')
const trendUpdatedAt = ref<string | null>(null)
const loading = ref(false)
const error = ref('')
const abnormalOnly = ref(false)
const showHealthy = ref(false)
const trendWindow = ref<'1h' | '15m'>('1h')
const groupBy = ref<'none' | 'model' | 'node'>('none')
const seriesKey = ref('all')
let timer = 0

const statusLabel = computed(() => {
  const status = summary.value?.status
  if (status === 'normal') return '正常'
  if (status === 'degraded') return '降级'
  if (status === 'down') return '不可用'
  return '未知'
})
const impactText = computed(() => summary.value?.impact_summary || '暂无影响范围')
const reasonText = computed(() => (summary.value?.reasons ?? []).join('；'))
const metrics = computed(() => summary.value?.metrics ?? null)
const abnormalRows = computed(() => rows.value.filter((row) => row.abnormal))
const healthyRows = computed(() => rows.value.filter((row) => !row.abnormal))
const tableEmpty = computed(() => {
  if (!rows.value.length) return '暂无节点。'
  if (abnormalOnly.value) return '没有异常节点。'
  return '没有异常节点，健康节点已收起。'
})
const visibleRows = computed(() => {
  if (abnormalOnly.value) return abnormalRows.value
  return showHealthy.value ? [...abnormalRows.value, ...healthyRows.value] : abnormalRows.value
})
const seriesOptions = computed(() => trend.value?.series ?? [])
const activeSeries = computed(() => seriesOptions.value.find((item) => item.key === seriesKey.value) ?? seriesOptions.value[0])
const trendPoints = computed(() => {
  const points = activeSeries.value?.points ?? []
  if (!points.some((point) => point.ttft_p95_ms !== null || point.requests > 0)) return null
  return points.map((point) => ({ bucket_start: point.bucket_start, value: point.ttft_p95_ms }))
})
const headlineTtft = computed(() => (trend.value?.ttft_p95_ms == null ? '暂无数据' : `${Math.round(trend.value.ttft_p95_ms)} ms`))
const headlineTps = computed(() => (trend.value?.output_tps_p95 == null ? '暂无数据' : trend.value.output_tps_p95.toFixed(1)))

const primaryCards = computed(() => {
  const current = metrics.value
  return [
    { id: 'qps', label: '当前 QPS', value: numberText(current?.qps ?? null, 2), hint: '滚动 1 分钟开始的请求 / 60 秒' },
    {
      id: 'error-rate',
      label: '错误率',
      value: percentText(current?.error_rate ?? null),
      hint: current?.error_rate_applies
        ? `近 5 分钟最终失败 / 已完成 · 样本 ${current.error_samples}`
        : `近 5 分钟样本 ${current?.error_samples ?? 0}，未达到健康判断样本`,
    },
    {
      id: 'ttft',
      label: 'TTFT P95',
      value: current?.ttft_p95_ms == null ? '暂无数据' : `${Math.round(current.ttft_p95_ms)} ms`,
      hint: current?.output_tps_p95 == null ? '输出 TPS P95 暂无数据' : `输出 TPS P95 ${current.output_tps_p95.toFixed(1)}`,
    },
    { id: 'capacity', label: '容量占用', value: capacityText(current), hint: capacityHint(current) },
  ]
})
const secondaryCards = computed(() => {
  const current = metrics.value
  return [
    { id: 'tokens', label: 'Token 吞吐', value: current?.token_throughput == null ? '暂无数据' : `${current.token_throughput.toFixed(2)} /s`, hint: '近 5 分钟已知 total token / 300 秒' },
    { id: 'retry', label: '重试率', value: percentText(current?.retry_rate ?? null), hint: '额外上游尝试次数 / 已完成请求' },
    { id: '429', label: '上游 429', value: percentText(current?.upstream_429_rate ?? null), hint: '上游返回 429 的占比，不含网关本地拒绝' },
    { id: 'stream', label: '流中断率', value: percentText(current?.stream_interrupt_rate ?? null), hint: '流式请求中的中断占比' },
    { id: 'usage', label: '未知用量', value: percentText(current?.unknown_usage_share ?? null), hint: '未返回 usage 的已完成请求占比' },
    {
      id: 'latency',
      label: '连接 / 首字节 P95',
      value: current?.connect_p95_ms == null && current?.ttfb_p95_ms == null
        ? '暂无数据'
        : `${ms(current?.connect_p95_ms)} / ${ms(current?.ttfb_p95_ms)}`,
      hint: current?.duration_p95_ms == null ? '总时长 P95 暂无数据' : `总时长 P95 ${Math.round(current.duration_p95_ms)} ms`,
    },
  ]
})

function numberText(value: number | null | undefined, digits: number): string {
  if (value === null || value === undefined) return '暂无数据'
  return value.toFixed(digits)
}
function percentText(value: number | null | undefined): string {
  if (value === null || value === undefined) return '暂无数据'
  return `${(value * 100).toFixed(2)}%`
}
function ms(value: number | null | undefined): string {
  return value == null ? '—' : `${Math.round(value)} ms`
}
function capacityText(current: GatewayHealthSummary['metrics'] | null): string {
  if (!current || current.capacity_occupancy === null) {
    if (current && current.active !== null && current.capacity_limit === null) return '不限'
    return '暂无数据'
  }
  return percentText(current.capacity_occupancy)
}
function capacityHint(current: GatewayHealthSummary['metrics'] | null): string {
  if (!current || current.active === null) return '并发采集失败'
  const limit = current.capacity_limit === null ? '不限' : String(current.capacity_limit)
  const queue = current.queue === null ? '无队列' : `排队 ${current.queue}`
  const peak = current.peak_concurrency === null ? '' : ` · 5 分钟峰值 ${current.peak_concurrency}`
  return `并发 ${current.active} / ${limit} · ${queue}${peak}`
}
function loadText(row: GatewayNodeMetric): string {
  if (row.active === null) return '暂无数据'
  const share = row.occupancy === null ? '不限' : percentText(row.occupancy)
  const queue = row.queue === null ? '无队列' : `排队 ${row.queue}`
  return `${share} · ${row.active}${row.capacity_limit ? `/${row.capacity_limit}` : ''} · ${queue}`
}
function healthTag(value: string): 'success' | 'danger' | 'info' {
  if (value === 'healthy') return 'success'
  if (value === 'unhealthy') return 'danger'
  return 'info'
}
function schedulingTag(value: string): 'success' | 'danger' | 'warning' | 'info' {
  if (value === 'available') return 'success'
  if (value === 'circuit') return 'danger'
  if (value === 'limited' || value === 'half_open') return 'warning'
  return 'info'
}
function trendWindowText(value: string): string {
  return value === '15m' ? '15 分钟' : '1 小时'
}
const trendStale = computed(() => {
  if (!trend.value || !trendUpdatedAt.value) return ''
  const mismatch = trend.value.window !== trendWindow.value
  if (!mismatch && !trendError.value) return ''
  return `图表仍是近 ${trendWindowText(trend.value.window)}，更新于 ${formatDateTime(trendUpdatedAt.value)}`
})
function showAbnormal() {
  abnormalOnly.value = true
  showHealthy.value = false
}
function openNodeLogs(row: GatewayNodeMetric) {
  const end = new Date()
  const start = new Date(end.getTime() - 5 * 60 * 1000)
  void router.push({
    path: '/gateway/logs',
    query: { node_id: row.node_id, from: start.toISOString(), to: end.toISOString() },
  })
}
function openEventLogs(event: GatewayOpsEvent) {
  const at = new Date(event.created_at).getTime()
  const start = new Date(at - 5 * 60 * 1000)
  const end = new Date(at + 5 * 60 * 1000)
  void router.push({
    path: '/gateway/logs',
    query: {
      node_id: event.node_id ?? undefined,
      model: event.model ?? undefined,
      pool_id: event.pool_id ?? undefined,
      key_id: event.key_id ?? undefined,
      from: start.toISOString(),
      to: end.toISOString(),
    },
  })
}

function emptyMetrics(): GatewayHealthSummary['metrics'] {
  return {
    qps: null,
    qps_requests: 0,
    error_rate: null,
    error_samples: 0,
    error_failures: 0,
    error_rate_applies: false,
    retry_rate: null,
    upstream_429_rate: null,
    stream_interrupt_rate: null,
    ttft_p95_ms: null,
    output_tps_p95: null,
    connect_p95_ms: null,
    ttfb_p95_ms: null,
    duration_p95_ms: null,
    unknown_usage_share: null,
    token_throughput: null,
    known_total_tokens: null,
    active: null,
    capacity_limit: null,
    capacity_occupancy: null,
    peak_concurrency: null,
    queue: null,
  }
}

function unavailableHealth(reason: string): GatewayHealthSummary {
  const now = new Date().toISOString()
  return {
    status: 'unknown',
    stale: true,
    reasons: [reason],
    impact: [],
    impact_summary: '健康摘要不可用',
    window: { qps_seconds: 60, error_seconds: 300, start: now, end: now },
    generated_at: now,
    metrics: emptyMetrics(),
    ignored_pools: [],
  }
}

function isAbort(reason: unknown): boolean {
  return reason instanceof Error && reason.name === 'AbortError'
}

let loadSeq = 0
let activeLoad: AbortController | null = null

async function load(silent: boolean) {
  const seq = ++loadSeq
  activeLoad?.abort()
  const controller = new AbortController()
  activeLoad = controller
  if (!silent) loading.value = true
  const signal = controller.signal
  const stale = () => seq !== loadSeq || signal.aborted
  try {
    try {
      const health = await gatewayApi.healthSummary(signal)
      if (stale()) return
      summary.value = health
      error.value = ''
    } catch (reason) {
      if (stale() || isAbort(reason)) return
      summary.value = unavailableHealth('健康摘要加载失败')
      error.value = errorMessage(reason, '健康摘要加载失败')
    }
    if (stale()) return
    const [nodeRows, eventRows, trendValue] = await Promise.allSettled([
      gatewayApi.nodeMetrics(signal),
      gatewayApi.opsEvents(40, signal),
      gatewayApi.trends(trendWindow.value, groupBy.value, signal),
    ])
    if (stale()) return
    if (nodeRows.status === 'fulfilled') rows.value = nodeRows.value
    if (eventRows.status === 'fulfilled') events.value = eventRows.value
    if (trendValue.status === 'fulfilled') {
      trend.value = trendValue.value
      trendUpdatedAt.value = new Date().toISOString()
      trendError.value = ''
      if (!trendValue.value.series.some((item) => item.key === seriesKey.value)) seriesKey.value = 'all'
    } else if (!isAbort(trendValue.reason)) {
      trendError.value = errorMessage(trendValue.reason, '趋势加载失败')
    }
  } finally {
    if (seq === loadSeq) loading.value = false
  }
}

watch([trendWindow, groupBy], () => { void load(true) })
onMounted(() => {
  void load(false)
  timer = window.setInterval(() => { void load(true) }, 30_000)
})
onBeforeUnmount(() => {
  window.clearInterval(timer)
  loadSeq += 1
  activeLoad?.abort()
})
</script>

<style scoped>
.gateway-overview { display: grid; gap: 12px; }
.gateway-overview__verdict {
  display: flex; align-items: center; justify-content: space-between; gap: 16px;
  padding: 14px 16px; border: 1px solid var(--astra-border); border-radius: 12px; background: var(--astra-bg-panel);
}
.gateway-overview__verdict[data-status='normal'] { border-color: #8fceb0; background: #f3fbf6; }
.gateway-overview__verdict[data-status='degraded'] { border-color: #e2c27a; background: #fff8ea; }
.gateway-overview__verdict[data-status='down'] { border-color: #e7a8ae; background: #fff5f6; }
.gateway-overview__verdict[data-status='unknown'] { border-color: #c5d4ce; background: #f6f8f7; }
.gateway-overview__eyebrow { margin: 0; color: var(--astra-text-secondary); font-size: var(--astra-font-helper); }
.gateway-overview__verdict h3 { margin: 2px 0; color: var(--astra-text-primary); font-size: 22px; }
.gateway-overview__impact, .gateway-overview__reasons { margin: 0; color: var(--astra-text-secondary); }
.gateway-overview__reasons { margin-top: 4px; }
.gateway-overview__metrics { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; }
.gateway-overview__metrics--secondary { grid-template-columns: repeat(6, minmax(0, 1fr)); }
.gateway-overview__metric-label { margin: 0; color: var(--astra-text-secondary); font-size: var(--astra-font-control); }
.gateway-overview__metric-value { margin: 6px 0 0; color: var(--astra-text-primary); font-size: var(--astra-font-subtitle); font-weight: var(--astra-weight-bold); font-variant-numeric: tabular-nums; }
.gateway-overview__metric-value--secondary { font-size: var(--astra-font-control); }
.gateway-overview__metric-hint { margin: 4px 0 0; color: var(--astra-text-secondary); font-size: var(--astra-font-helper); }
.gateway-overview__main { display: grid; grid-template-columns: minmax(0, 1.6fr) minmax(280px, 0.8fr); gap: 12px; align-items: start; }
.gateway-overview__card-header { display: flex; align-items: flex-start; gap: 12px; }
.gateway-overview__card-header > div { margin-right: auto; }
.gateway-overview__card-header h4 { margin: 0; color: var(--astra-text-primary); font-size: var(--astra-font-control); }
.gateway-overview__node { color: var(--astra-primary-bright); font-weight: var(--astra-weight-bold); text-decoration: none; }
.gateway-overview__sub { display: block; color: var(--astra-text-secondary); font-size: var(--astra-font-helper); }
.gateway-overview__collapse { padding-top: 8px; }
.gateway-overview__event-list { display: grid; gap: 8px; margin: 0; padding: 0; list-style: none; }
.gateway-overview__event-list button {
  display: grid; grid-template-columns: auto minmax(0, 1fr); gap: 6px 8px; width: 100%;
  padding: 8px; border: 0; border-radius: 8px; background: transparent; color: var(--astra-text-primary); text-align: left; cursor: pointer;
}
.gateway-overview__event-list button:hover { background: var(--astra-bg-elevated); }
.gateway-overview__event-list time { grid-column: 2; color: var(--astra-text-secondary); font-size: var(--astra-font-helper); }
.gateway-overview__trend-tools { display: flex; gap: 8px; }
.gateway-overview__group { width: 120px; }
.gateway-overview__trend-headline { margin: 0 0 8px; color: var(--astra-text-secondary); }
@media (max-width: 1280px) {
  .gateway-overview__metrics, .gateway-overview__metrics--secondary { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .gateway-overview__main { grid-template-columns: 1fr; }
}
@media (max-width: 760px) {
  .gateway-overview__verdict, .gateway-overview__metrics, .gateway-overview__metrics--secondary { grid-template-columns: 1fr; }
  .gateway-overview__verdict { align-items: flex-start; flex-direction: column; }
}
</style>
