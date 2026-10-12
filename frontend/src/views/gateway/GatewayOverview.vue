<template>
  <section class="gateway-overview" data-testid="gateway-overview">
    <GatewayHeaderActions>
      <ElRadioGroup v-model="statsWindow" data-testid="gateway-window-switch">
        <ElRadioButton v-for="item in windows" :key="item.id" :value="item.id">{{ item.label }}</ElRadioButton>
      </ElRadioGroup>
      <ElButton :loading="loading" :icon="RefreshCw" data-testid="gateway-overview-refresh" @click="load">刷新</ElButton>
    </GatewayHeaderActions>

    <ElAlert v-if="error" type="error" show-icon :closable="false" :title="error" data-testid="gateway-overview-error">
      <ElButton type="primary" data-testid="gateway-overview-retry" @click="load">重试</ElButton>
    </ElAlert>

    <section class="gateway-overview__metrics" aria-label="核心指标">
      <ElCard v-for="metric in metricCards" :key="metric.id" shadow="never" :data-testid="`gateway-metric-${metric.id}`">
        <ElStatistic :title="metric.label" :value="metric.value as number" />
        <p class="gateway-overview__metric-hint">{{ metric.hint }}</p>
      </ElCard>
    </section>

    <div class="gateway-overview__grid">
      <ElCard shadow="never" class="gateway-overview__trend-card" data-testid="gateway-overview-trend">
        <template #header>
          <div class="gateway-overview__card-header">
            <div><h4>Token 趋势</h4><ElText type="info">{{ windowLabel }}</ElText></div>
            <span class="gateway-overview__legend"><i />输入<i class="gateway-overview__legend--output" />输出</span>
          </div>
        </template>
        <GatewayTrendChart v-if="stats" :buckets="stats.trend" mode="tokens" />
        <ElEmpty v-else :image-size="52" :description="loading ? '加载中…' : '暂无数据'" />
      </ElCard>

      <ElCard shadow="never">
        <template #header>
          <div class="gateway-overview__card-header"><div><h4>QPS 与延迟</h4><ElText type="info">窗口内平均 / p50 / p95</ElText></div></div>
        </template>
        <ElDescriptions :column="1">
          <ElDescriptionsItem v-for="row in latencyRows" :key="row.label" :label="row.label">{{ row.value }}</ElDescriptionsItem>
        </ElDescriptions>
        <div class="gateway-overview__peak">
          <span>峰值并发 <b>{{ stats?.peak_concurrency ?? '—' }}</b></span>
          <span>窗口请求 <b>{{ stats?.requests ?? '—' }}</b></span>
          <span>失败 <b class="gateway-overview__peak--bad">{{ stats?.errors ?? '—' }}</b></span>
        </div>
      </ElCard>

      <ElCard shadow="never" data-testid="gateway-overview-health">
        <template #header>
          <div class="gateway-overview__card-header"><div><h4>节点健康分布</h4><ElText type="info">健康态与调度态相互独立</ElText></div></div>
        </template>
        <ul class="gateway-overview__dist">
          <li v-for="item in healthRows" :key="item.label">
            <ElTag :type="item.tag">{{ item.label }}</ElTag>
            <div class="gateway-overview__dist-bar"><i :style="{ width: `${barWidth(item.value, healthMax)}%` }" /></div>
            <b>{{ item.value }}</b>
          </li>
        </ul>
        <ElText class="gateway-overview__note">{{ schedulingSummary }}</ElText>
      </ElCard>

      <ElCard shadow="never">
        <template #header>
          <div class="gateway-overview__card-header"><div><h4>模型分布</h4><ElText type="info">按节点支持模型统计</ElText></div></div>
        </template>
        <ul v-if="modelRows.length" class="gateway-overview__dist">
          <li v-for="item in modelRows" :key="item.label">
            <span class="gateway-overview__dist-label" :title="item.label">{{ item.label }}</span>
            <div class="gateway-overview__dist-bar"><i :style="{ width: `${barWidth(item.value, modelMax)}%` }" /></div>
            <b>{{ item.value }}</b>
          </li>
        </ul>
        <ElEmpty v-else :image-size="52" description="暂无节点配置支持模型" />
      </ElCard>
    </div>

    <ElCard shadow="never" data-testid="gateway-overview-nodes-entry">
      <template #header>
        <div class="gateway-overview__card-header">
          <div><h4>节点</h4><ElText type="info">节点的增删改与健康操作在「下游节点」页完成</ElText></div>
          <RouterLink class="gateway-overview__entry" to="/gateway/nodes" data-testid="gateway-nodes-entry">进入节点列表 <ArrowUpRight :size="13" /></RouterLink>
        </div>
      </template>
      <ElDescriptions :column="4">
        <ElDescriptionsItem label="节点总数">{{ nodes.length }}</ElDescriptionsItem>
        <ElDescriptionsItem label="健康">{{ healthyCount }}</ElDescriptionsItem>
        <ElDescriptionsItem label="调度中">{{ schedulingCounts.ACTIVE }}</ElDescriptionsItem>
        <ElDescriptionsItem label="已阻止">{{ schedulingCounts.BLOCKED }}</ElDescriptionsItem>
      </ElDescriptions>
    </ElCard>

    <ElCard shadow="never" data-testid="gateway-overview-instances">
      <template #header>
        <div class="gateway-overview__card-header"><div><h4>Gateway 实例</h4><ElText type="info">心跳过期即标记不可用，不从实例反推节点健康</ElText></div></div>
      </template>
      <ElTable :data="instances" empty-text="暂无实例心跳。">
        <ElTableColumn label="实例" prop="instance_id" min-width="150"><template #default="{ row }"><span class="gateway-overview__mono">{{ row.instance_id }}</span></template></ElTableColumn>
        <ElTableColumn label="状态" width="86"><template #default="{ row }"><ElTag :type="row.status === 'ACTIVE' ? 'success' : 'info'">{{ row.status === 'ACTIVE' ? '在线' : '已过期' }}</ElTag></template></ElTableColumn>
        <ElTableColumn label="应用版本" min-width="100"><template #default="{ row }"><span class="gateway-overview__mono">{{ row.app_version ?? '—' }}</span></template></ElTableColumn>
        <ElTableColumn label="运行时长" width="90"><template #default="{ row }">{{ formatSeconds(row.uptime_seconds) }}</template></ElTableColumn>
        <ElTableColumn label="活跃" width="64"><template #default="{ row }">{{ row.active ?? '—' }}</template></ElTableColumn>
        <ElTableColumn label="请求 / 错误" width="100"><template #default="{ row }">{{ row.requests ?? '—' }} / {{ row.errors ?? '—' }}</template></ElTableColumn>
        <ElTableColumn label="CPU" width="76"><template #default="{ row }">{{ row.cpu_percent !== null && row.cpu_percent !== undefined ? `${row.cpu_percent.toFixed(1)}%` : '—' }}</template></ElTableColumn>
        <ElTableColumn label="内存" width="86"><template #default="{ row }">{{ formatBytes(row.memory_bytes) }}</template></ElTableColumn>
        <ElTableColumn label="心跳" width="110"><template #default="{ row }">{{ formatRelativeTime(row.updated_at) }}</template></ElTableColumn>
      </ElTable>
    </ElCard>
  </section>
</template>

<script setup lang="ts">
import { ArrowUpRight, RefreshCw } from 'lucide-vue-next'
import { computed, onMounted, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import {
  ElAlert,
  ElButton,
  ElCard,
  ElDescriptions,
  ElDescriptionsItem,
  ElEmpty,
  ElRadioGroup,
  ElRadioButton,
  ElStatistic,
  ElTable,
  ElTableColumn,
  ElTag,
  ElText,
} from 'element-plus'
import {
  gatewayApi,
  type GatewayInstance,
  type GatewayNode,
  type GatewayScopeStats,
  type GatewayStatsWindow,
} from '@/api/gateway'
import { errorMessage, formatBytes, formatPercent, formatRelativeTime, formatSeconds } from '@/utils/gateway'
import { formatTokens } from '@/utils/format'
import GatewayTrendChart from '@/views/gateway/GatewayTrendChart.vue'
import GatewayHeaderActions from '@/views/gateway/GatewayHeaderActions.vue'

const windows: Array<{ id: GatewayStatsWindow; label: string }> = [
  { id: 'hour', label: '本小时' },
  { id: 'today', label: '今日' },
  { id: '7d', label: '近 7 天' },
  { id: '30d', label: '近 30 天' },
]
const statsWindow = ref<GatewayStatsWindow>('today')
const stats = ref<GatewayScopeStats | null>(null)
const nodes = ref<GatewayNode[]>([])
const instances = ref<GatewayInstance[]>([])
const loading = ref(false)
const error = ref('')

const windowLabel = computed(() => windows.find((item) => item.id === statsWindow.value)?.label ?? '')

const metricCards = computed(() => {
  const current = stats.value
  return [
    { id: 'requests', label: '请求数', value: current?.requests ?? '—', hint: '窗口内完成的调用总量' },
    { id: 'success-rate', label: '成功率', value: formatPercent(current?.success_rate), hint: '2xx/3xx 且未被中断' },
    { id: 'qps', label: 'QPS', value: current ? current.qps.toFixed(2) : '—', hint: '窗口平均每秒请求数' },
    { id: 'active', label: '当前并发', value: current?.active ?? '—', hint: '来自数据面运行态租约' },
    { id: 'tokens', label: '总 Token', value: current ? formatTokens(current.total_tokens) : '—', hint: '输入 + 输出，未知不估算' },
    { id: 'unknown', label: '未知用量', value: current?.unknown_usage_requests ?? '—', hint: '下游未返回 usage 的请求数' },
  ]
})

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

type TagType = 'success' | 'warning' | 'danger' | 'info' | 'primary'
const healthStates: Array<{ state: string; label: string; tag: TagType }> = [
  { state: 'HEALTHY', label: '健康', tag: 'success' },
  { state: 'DEGRADED', label: '降级', tag: 'warning' },
  { state: 'CHECKING', label: '探测中', tag: 'info' },
  { state: 'UNHEALTHY', label: '异常', tag: 'danger' },
  { state: 'UNKNOWN', label: '未探测', tag: 'primary' },
]
const healthRows = computed(() =>
  healthStates.map((item) => ({
    ...item,
    value: nodes.value.filter((node) => node.health_state === item.state).length,
  })),
)
const healthyCount = computed(() => nodes.value.filter((node) => node.health_state === 'HEALTHY').length)
const healthMax = computed(() => Math.max(1, ...healthRows.value.map((item) => item.value)))
const schedulingCounts = computed(() => {
  const counts = { ACTIVE: 0, DRAINING: 0, BLOCKED: 0 }
  for (const node of nodes.value) {
    if (node.scheduling_state in counts) counts[node.scheduling_state as keyof typeof counts] += 1
  }
  return counts
})
const schedulingSummary = computed(() =>
  `调度：调度中 ${schedulingCounts.value.ACTIVE} · 安全下线 ${schedulingCounts.value.DRAINING} · 已阻止 ${schedulingCounts.value.BLOCKED}`,
)

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
    const [statsValue, nodeList, instanceList] = await Promise.all([
      gatewayApi.stats('overview', statsWindow.value),
      gatewayApi.nodes(),
      gatewayApi.instances(),
    ])
    stats.value = statsValue
    nodes.value = nodeList
    instances.value = instanceList
  } catch (reason) {
    error.value = errorMessage(reason, '总览加载失败')
  } finally {
    loading.value = false
  }
}

watch(statsWindow, load)
onMounted(() => { void load() })
</script>

<style scoped>
.gateway-overview { display: grid; gap: 12px; }
.gateway-overview__metrics { display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); gap: 12px; }
.gateway-overview__metrics :deep(.el-statistic__head) { color: var(--astra-text-muted); font-size: var(--astra-font-control); }
.gateway-overview__metrics :deep(.el-statistic__content) { color: var(--astra-text-primary); font-size: var(--astra-font-subtitle); font-weight: var(--astra-weight-bold); }
.gateway-overview__metric-hint { margin: 4px 0 0; color: var(--astra-text-muted); font-size: var(--astra-font-helper); }
.gateway-overview__grid { display: grid; grid-template-columns: minmax(0, 1.5fr) minmax(300px, 1fr); gap: 12px; }
.gateway-overview__card-header { display: flex; align-items: flex-start; gap: 12px; }
.gateway-overview__card-header > div { margin-right: auto; }
.gateway-overview__card-header h4 { margin: 0; color: var(--astra-text-primary); font-size: var(--astra-font-control); }
.gateway-overview__legend { display: inline-flex; align-items: center; gap: 5px; color: var(--astra-text-muted); font-size: var(--astra-font-helper); }
.gateway-overview__legend i { display: inline-block; width: 8px; height: 8px; border-radius: 2px; background: #3d8ff0; }
.gateway-overview__legend .gateway-overview__legend--output { background: #159d65; }
.gateway-overview__peak { display: flex; gap: 16px; margin-top: 10px; padding-top: 10px; border-top: 1px solid var(--astra-border); color: var(--astra-text-muted); font-size: var(--astra-font-helper); }
.gateway-overview__peak b { color: var(--astra-text-primary); font-variant-numeric: tabular-nums; }
.gateway-overview__peak--bad { color: var(--astra-danger); }
.gateway-overview__dist { display: grid; gap: 9px; margin: 0; padding: 0; list-style: none; }
.gateway-overview__dist li { display: grid; grid-template-columns: minmax(64px, auto) minmax(60px, 1fr) 30px; align-items: center; gap: 10px; font-size: var(--astra-font-helper); }
.gateway-overview__dist-label { overflow: hidden; color: var(--astra-text-secondary); text-overflow: ellipsis; white-space: nowrap; }
.gateway-overview__dist-bar { height: 8px; overflow: hidden; border-radius: 999px; background: var(--astra-bg-elevated); }
.gateway-overview__dist-bar i { display: block; height: 100%; border-radius: 999px; background: linear-gradient(90deg, #24c47d, #0d9e61); }
.gateway-overview__dist b { color: var(--astra-text-primary); text-align: right; font-variant-numeric: tabular-nums; }
.gateway-overview__note { display: block; margin-top: 10px; color: var(--astra-text-muted); }
.gateway-overview__entry { display: inline-flex; align-items: center; gap: 3px; color: var(--astra-primary-bright); font-size: var(--astra-font-helper); text-decoration: none; }
.gateway-overview__mono { font-family: var(--astra-font-family); font-size: var(--astra-font-helper); }
@media (max-width: 1280px) { .gateway-overview__metrics { grid-template-columns: repeat(3, minmax(0, 1fr)); } .gateway-overview__grid { grid-template-columns: 1fr; } }
@media (max-width: 760px) { .gateway-overview__metrics { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
</style>
