<template>
  <section class="gateway-overview">
    <header class="gateway-overview__bar">
      <div class="gateway-overview__intro">
        <h3>API 中转总览</h3>
        <p>Token、QPS、延迟、节点健康与实例状态均直接来自后端观测契约。</p>
      </div>
      <el-radio-group v-model="statsWindow" size="small" aria-label="统计窗口">
        <el-radio-button v-for="item in windows" :key="item.id" :value="item.id">{{ item.label }}</el-radio-button>
      </el-radio-group>
      <el-button :loading="loading" :disabled="loading" @click="load"><RefreshCw v-if="!loading" :size="14" />刷新</el-button>
    </header>

    <p v-if="error" class="gateway-alert"><TriangleAlert :size="15" />{{ error }}<el-button type="danger" link @click="load">重试</el-button></p>

    <div class="metrics-grid gateway-metrics">
      <AstraMetricCard label="请求数" :value="stats?.requests ?? '—'" hint="窗口内完成的调用总量" :icon="Activity" />
      <AstraMetricCard label="成功率" :value="formatPercent(stats?.success_rate)" tone="success" hint="2xx/3xx 且未被中断" :icon="CheckCircle2" />
      <AstraMetricCard label="QPS" :value="stats ? stats.qps.toFixed(2) : '—'" tone="warning" hint="窗口平均每秒请求数" :icon="Gauge" />
      <AstraMetricCard label="当前并发" :value="stats?.active ?? '—'" hint="来自数据面运行态租约" :icon="Waves" />
      <AstraMetricCard label="总 Token" :value="stats ? formatTokens(stats.total_tokens) : '—'" hint="输入 + 输出，未知不估算" :icon="Coins" />
      <AstraMetricCard label="未知用量" :value="stats?.unknown_usage_requests ?? '—'" tone="warning" hint="下游未返回 usage 的请求数" :icon="CircleHelp" />
    </div>

    <div class="gateway-grid">
      <AstraPanel title="Token 趋势" :subtitle="windowLabel">
        <template #action><span class="gateway-legend"><i class="gateway-legend__input" />输入<i class="gateway-legend__output" />输出</span></template>
        <GatewayTrendChart v-if="stats" :buckets="stats.trend" mode="tokens" />
        <div v-else class="gateway-placeholder">{{ loading ? '加载中…' : '暂无数据' }}</div>
      </AstraPanel>

      <AstraPanel title="QPS 与延迟" subtitle="窗口内平均 / p50 / p95">
        <dl class="performance-list gateway-latency">
          <div v-for="row in latencyRows" :key="row.label"><dt>{{ row.label }}</dt><dd>{{ row.value }}</dd></div>
        </dl>
        <div class="gateway-peak">
          <span>峰值并发 <b>{{ stats?.peak_concurrency ?? '—' }}</b></span>
          <span>窗口请求 <b>{{ stats?.requests ?? '—' }}</b></span>
          <span>失败 <b class="gateway-peak__bad">{{ stats?.errors ?? '—' }}</b></span>
        </div>
      </AstraPanel>

      <AstraPanel title="节点健康分布" subtitle="健康态与调度态相互独立">
        <ul class="gateway-dist">
          <li v-for="item in healthRows" :key="item.label">
            <span class="status-badge" :data-tone="item.tone">{{ item.label }}</span>
            <div class="gateway-dist__bar"><i :style="{ width: `${barWidth(item.value, healthMax)}%` }" /></div>
            <b>{{ item.value }}</b>
          </li>
        </ul>
        <p class="gateway-note">调度：{{ schedulingSummary }}</p>
      </AstraPanel>

      <AstraPanel title="模型分布" subtitle="按节点支持模型统计">
        <ul v-if="modelRows.length" class="gateway-dist">
          <li v-for="item in modelRows" :key="item.label">
            <span class="gateway-dist__label" :title="item.label">{{ item.label }}</span>
            <div class="gateway-dist__bar"><i :style="{ width: `${barWidth(item.value, modelMax)}%` }" /></div>
            <b>{{ item.value }}</b>
          </li>
        </ul>
        <p v-else class="gateway-note">暂无节点配置支持模型。</p>
      </AstraPanel>
    </div>

    <AstraPanel title="节点" subtitle="点击进入节点详情进行完整操作" flush>
      <template #action><span class="gateway-note">共 {{ nodes.length }} 个节点</span></template>
      <GatewayNodeTable :nodes="nodes" :pools="pools" readonly />
    </AstraPanel>

    <AstraPanel title="Gateway 实例" subtitle="心跳过期即标记不可用，不从实例反推节点健康" flush>
      <el-table :data="instances" stripe empty-text="暂无实例心跳。">
        <el-table-column prop="instance_id" label="实例" min-width="180" class-name="gateway-mono" />
        <el-table-column label="状态" width="100"><template #default="{ row }"><el-tag :type="row.status === 'ACTIVE' ? 'success' : 'info'" effect="light">{{ row.status === 'ACTIVE' ? '在线' : '已过期' }}</el-tag></template></el-table-column>
        <el-table-column label="应用版本" min-width="120"><template #default="{ row }">{{ row.app_version ?? '—' }}</template></el-table-column>
        <el-table-column label="配置版本" min-width="120"><template #default="{ row }">{{ row.config_version ?? '—' }}</template></el-table-column>
        <el-table-column label="运行时长" min-width="110"><template #default="{ row }">{{ formatSeconds(row.uptime_seconds) }}</template></el-table-column>
        <el-table-column label="活跃" width="80"><template #default="{ row }">{{ row.active ?? '—' }}</template></el-table-column>
        <el-table-column label="请求 / 错误" min-width="120"><template #default="{ row }">{{ row.requests ?? '—' }} / {{ row.errors ?? '—' }}</template></el-table-column>
        <el-table-column label="CPU" width="90"><template #default="{ row }">{{ row.cpu_percent !== null && row.cpu_percent !== undefined ? `${row.cpu_percent.toFixed(1)}%` : '—' }}</template></el-table-column>
        <el-table-column label="内存" min-width="100"><template #default="{ row }">{{ formatBytes(row.memory_bytes) }}</template></el-table-column>
        <el-table-column label="心跳" min-width="120"><template #default="{ row }">{{ formatRelativeTime(row.updated_at) }}</template></el-table-column>
      </el-table>
    </AstraPanel>
  </section>
</template>

<script setup lang="ts">
import { Activity, CheckCircle2, CircleHelp, Coins, Gauge, RefreshCw, TriangleAlert, Waves } from 'lucide-vue-next'
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import {
  gatewayApi,
  GatewayApiError,
  type GatewayInstance,
  type GatewayNode,
  type GatewayPool,
  type GatewayScopeStats,
  type GatewayStatsWindow,
} from '@/api/gateway'
import AstraMetricCard from '@/components/astra/AstraMetricCard.vue'
import AstraPanel from '@/components/astra/AstraPanel.vue'
import { useGatewayAuth } from '@/composables/useGatewayAuth'
import { errorMessage, formatBytes, formatPercent, formatRelativeTime, formatSeconds } from '@/utils/gateway'
import { formatTokens } from '@/utils/format'
import GatewayNodeTable from '@/views/gateway/GatewayNodeTable.vue'
import GatewayTrendChart from '@/views/gateway/GatewayTrendChart.vue'

const { disconnect } = useGatewayAuth()
const windows: Array<{ id: GatewayStatsWindow; label: string }> = [
  { id: 'hour', label: '本小时' },
  { id: 'today', label: '今日' },
  { id: '7d', label: '近 7 天' },
  { id: '30d', label: '近 30 天' },
]
const statsWindow = ref<GatewayStatsWindow>('today')
const stats = ref<GatewayScopeStats | null>(null)
const nodes = ref<GatewayNode[]>([])
const pools = ref<GatewayPool[]>([])
const instances = ref<GatewayInstance[]>([])
const loading = ref(false)
const error = ref('')
let timer: ReturnType<typeof setInterval> | undefined

const windowLabel = computed(() => windows.find((item) => item.id === statsWindow.value)?.label ?? '')

const latencyRows = computed(() => {
  const current = stats.value
  if (!current) return [] as Array<{ label: string; value: string }>
  const line = (label: string, value: { avg: number | null; p50: number | null; p95: number | null }, unit = 'ms') =>
    ({ label, value: value.avg === null ? '—' : `${value.avg.toFixed(0)} / ${value.p50?.toFixed(0) ?? '—'} / ${value.p95?.toFixed(0) ?? '—'} ${unit}` })
  return [
    line('连接', current.connect_ms),
    line('首字节 (TTFB)', current.ttfb_ms),
    line('首 Token (TTFT)', current.ttft_ms),
    line('总时长', current.duration_ms),
    line('输出 TPS', current.output_tps, 'tok/s'),
  ]
})

const healthRows = computed(() => {
  const states: Array<{ state: string; label: string; tone: 'success' | 'warning' | 'danger' | 'info' | 'neutral' }> = [
    { state: 'HEALTHY', label: '健康', tone: 'success' },
    { state: 'DEGRADED', label: '降级', tone: 'warning' },
    { state: 'CHECKING', label: '探测中', tone: 'info' },
    { state: 'UNHEALTHY', label: '异常', tone: 'danger' },
    { state: 'UNKNOWN', label: '未探测', tone: 'neutral' },
  ]
  return states.map((item) => ({
    label: item.label,
    tone: item.tone,
    value: nodes.value.filter((node) => node.health_state === item.state).length,
  }))
})

const healthMax = computed(() => Math.max(1, ...healthRows.value.map((item) => item.value)))
const schedulingSummary = computed(() => {
  const counts = { ACTIVE: 0, DRAINING: 0, BLOCKED: 0 }
  for (const node of nodes.value) {
    if (node.scheduling_state in counts) counts[node.scheduling_state as keyof typeof counts] += 1
  }
  return `调度中 ${counts.ACTIVE} · 安全下线 ${counts.DRAINING} · 已阻止 ${counts.BLOCKED}`
})

const modelRows = computed(() => {
  const counter = new Map<string, number>()
  for (const node of nodes.value) {
    for (const model of node.models ?? []) counter.set(model, (counter.get(model) ?? 0) + 1)
  }
  return [...counter.entries()]
    .map(([label, value]) => ({ label, value }))
    .sort((a, b) => b.value - a.value)
    .slice(0, 6)
})
const modelMax = computed(() => Math.max(1, ...modelRows.value.map((item) => item.value)))

function barWidth(value: number, max: number): number {
  return value ? Math.max(8, Math.round((value / max) * 100)) : 0
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    const [statsValue, nodeList, poolList, instanceList] = await Promise.all([
      gatewayApi.stats('overview', statsWindow.value),
      gatewayApi.nodes(),
      gatewayApi.pools(),
      gatewayApi.instances(),
    ])
    stats.value = statsValue
    nodes.value = nodeList
    pools.value = poolList
    instances.value = instanceList
  } catch (reason) {
    if (reason instanceof GatewayApiError && reason.status === 401) { disconnect(); return }
    error.value = errorMessage(reason, '总览加载失败')
  } finally {
    loading.value = false
  }
}

watch(statsWindow, load)
onMounted(() => {
  void load()
  timer = globalThis.setInterval(() => { if (!document.hidden) void load() }, 30_000)
})
onBeforeUnmount(() => { if (timer !== undefined) globalThis.clearInterval(timer) })
</script>

<style scoped>
.gateway-overview { display: grid; gap: 16px; }
.gateway-overview__bar { display: flex; align-items: center; gap: 14px; }
.gateway-overview__intro { margin-right: auto; }
.gateway-overview__intro h3 { margin: 0; color: var(--astra-text-primary); }
.gateway-overview__intro p { margin: 4px 0 0; color: var(--astra-text-muted); font-size: var(--astra-font-helper); }
.gateway-window-switch, .gateway-range { display: flex; gap: 3px; padding: 3px; border: 1px solid var(--astra-border); border-radius: 8px; background: #fff; }
.gateway-window-switch button { padding: 5px 10px; color: var(--astra-text-muted); border: 0; border-radius: 6px; background: transparent; font-size: var(--astra-font-helper); cursor: pointer; }
.gateway-window-switch button.active { color: var(--astra-primary-bright); background: var(--astra-primary-soft); }
.gateway-metrics { grid-template-columns: repeat(6, minmax(0, 1fr)); margin-bottom: 0; }
.gateway-metrics :deep(.metric-card) { min-height: 120px; }
.gateway-grid { display: grid; grid-template-columns: minmax(0, 1.5fr) minmax(300px, 1fr); gap: 16px; }
.gateway-grid > :nth-child(3), .gateway-grid > :nth-child(4) { min-height: 220px; }
.gateway-legend { display: inline-flex; align-items: center; gap: 5px; color: var(--astra-text-muted); font-size: var(--astra-font-helper); }
.gateway-legend i { display: inline-block; width: 8px; height: 8px; margin-left: 8px; border-radius: 2px; }
.gateway-legend i:first-child { margin-left: 0; }
.gateway-legend__input { background: #3d8ff0; }
.gateway-legend__output { background: #159d65; }
.gateway-placeholder { display: grid; place-items: center; height: 200px; color: var(--astra-text-muted); font-size: var(--astra-font-helper); }
.gateway-latency { grid-template-columns: 1fr; margin: 0; }
.gateway-peak { display: flex; gap: 16px; margin-top: 12px; padding-top: 12px; border-top: 1px solid var(--astra-border); color: var(--astra-text-muted); font-size: var(--astra-font-helper); }
.gateway-peak b { color: var(--astra-text-primary); font-variant-numeric: tabular-nums; }
.gateway-peak__bad { color: var(--astra-danger); }
.gateway-dist { display: grid; gap: 9px; margin: 0; padding: 0; list-style: none; }
.gateway-dist li { display: grid; grid-template-columns: minmax(90px, auto) minmax(60px, 1fr) 30px; align-items: center; gap: 10px; font-size: var(--astra-font-helper); }
.gateway-dist__label { overflow: hidden; color: var(--astra-text-secondary); text-overflow: ellipsis; white-space: nowrap; }
.gateway-dist__bar { height: 8px; overflow: hidden; border-radius: 999px; background: var(--astra-bg-elevated); }
.gateway-dist__bar i { display: block; height: 100%; border-radius: 999px; background: linear-gradient(90deg, #24c47d, #0d9e61); }
.gateway-dist b { color: var(--astra-text-primary); text-align: right; font-variant-numeric: tabular-nums; }
.gateway-note { margin: 10px 0 0; color: var(--astra-text-muted); font-size: var(--astra-font-helper); }
.gateway-alert { display: flex; align-items: center; gap: 7px; margin: 0; padding: 10px 12px; color: var(--astra-danger); border: 1px solid rgba(228, 93, 106, .2); border-radius: 9px; background: var(--astra-danger-soft); font-size: var(--astra-font-helper); }
.gateway-alert button { margin-left: auto; color: inherit; border: 0; background: transparent; text-decoration: underline; cursor: pointer; }
.gateway-instance-table { min-width: 760px; }
.gateway-mono { font-family: var(--astra-font-family); font-size: var(--astra-font-helper); }
.gateway-time { white-space: nowrap; font-size: var(--astra-font-helper); }
@media (max-width: 1280px) { .gateway-metrics { grid-template-columns: repeat(3, minmax(0, 1fr)); } .gateway-grid { grid-template-columns: 1fr; } }
@media (max-width: 760px) { .gateway-overview__bar { flex-wrap: wrap; } .gateway-metrics { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
</style>