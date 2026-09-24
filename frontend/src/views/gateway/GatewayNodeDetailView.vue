<template>
  <div class="page gateway-node-page" data-testid="gateway-node-detail">
    <GatewayGate>
      <div v-if="node" class="gateway-node">
        <nav class="detail-nav">
          <RouterLink to="/gateway?tab=nodes"><ArrowLeft :size="14" />节点列表</RouterLink>
          <strong>{{ node.name }}</strong>
        </nav>

        <header class="gateway-node__hero">
          <div class="gateway-node__identity">
            <small>{{ node.id }}</small>
            <h2>{{ node.name }}</h2>
            <div class="gateway-node__badges">
              <el-tag :type="tagType(healthTone(node.health_state))" effect="light">{{ healthStateLabel(node.health_state) }}</el-tag>
              <el-tag :type="tagType(schedulingTone(node.scheduling_state))" effect="light">{{ schedulingStateLabel(node.scheduling_state) }}</el-tag>
              <el-tag :type="node.config_state === 'ENABLED' ? 'success' : 'info'" effect="light">{{ configStateLabel(node.config_state) }}</el-tag>
              <span class="gateway-node__pool">{{ poolName(node.pool_id) }}</span>
            </div>
            <p class="gateway-node__url">{{ node.base_url }}</p>
          </div>
          <div class="gateway-node__actions">
            <el-button :loading="working" :disabled="working" @click="probe"><Activity v-if="!working" :size="14" />探测</el-button>
            <el-button v-if="node.scheduling_state === 'ACTIVE'" type="warning" plain :disabled="working" @click="drain"><Pause :size="14" />安全下线</el-button>
            <el-button v-else :disabled="working" @click="restore"><Play :size="14" />恢复调度</el-button>
            <el-button v-if="canManage" :disabled="working" @click="toggleConfig"><PowerOff v-if="node.config_state === 'ENABLED'" :size="14" /><Power v-else :size="14" />{{ node.config_state === 'ENABLED' ? '禁用' : '启用' }}</el-button>
            <el-button v-if="canManage" type="primary" @click="openEditor"><Pencil :size="14" />编辑</el-button>
          </div>
        </header>

        <p v-if="error" class="gateway-alert"><TriangleAlert :size="15" />{{ error }}<el-button type="danger" link @click="load">重试</el-button></p>

        <el-tabs v-model="tab" class="gateway-node-tabs" aria-label="节点详情导航">
          <el-tab-pane v-for="item in tabs" :key="item.id" :label="item.label" :name="item.id" />
        </el-tabs>

        <!-- 概览 -->
        <template v-if="tab === 'overview'">
          <div class="metrics-grid gateway-metrics">
            <AstraMetricCard label="窗口请求" :value="stats?.requests ?? '—'" :hint="windowLabel" :icon="Activity" />
            <AstraMetricCard label="成功率" :value="formatPercent(stats?.success_rate)" tone="success" hint="窗口内成功比例" :icon="CheckCircle2" />
            <AstraMetricCard label="当前并发" :value="stats?.active ?? '—'" hint="运行态租约" :icon="Waves" />
            <AstraMetricCard label="QPS" :value="stats ? stats.qps.toFixed(2) : '—'" tone="warning" hint="窗口平均" :icon="Gauge" />
            <AstraMetricCard label="总 Token" :value="stats ? formatTokens(stats.total_tokens) : '—'" hint="输入 + 输出" :icon="Coins" />
            <AstraMetricCard label="连续成功 / 失败" :value="`${node.success_streak} / ${node.failure_streak}`" :tone="node.failure_streak ? 'warning' : 'info'" hint="探测连击计数" :icon="RadioTower" />
          </div>
          <div class="gateway-detail-grid">
            <AstraPanel title="节点信息">
              <dl class="gateway-info-list">
                <div><dt>下游地址</dt><dd>{{ node.base_url }}</dd></div>
                <div><dt>认证方式</dt><dd>{{ authTypeLabel(node.auth_type) }} · {{ node.auth_header }}</dd></div>
                <div><dt>凭据</dt><dd>{{ node.has_api_key ? '已配置（不回显）' : '未配置' }}</dd></div>
                <div><dt>健康路径</dt><dd>{{ node.health_path || '继承默认' }}</dd></div>
                <div><dt>支持模型</dt><dd>{{ node.models.length ? node.models.join('、') : '未配置' }}</dd></div>
                <div><dt>最近探测</dt><dd>{{ formatDateTime(node.last_checked_at) }}</dd></div>
              </dl>
            </AstraPanel>
            <AstraPanel title="最近探测结果" flush>
              <p class="gateway-auth-line">
                <el-tag :type="tagType(authenticationTone(probeAuthentication))" effect="light">{{ authenticationLabel(probeAuthentication) }}</el-tag>
                <small>由真实模型调用状态推断，未新增独立认证探测</small>
              </p>
              <el-table :data="healthChecks.slice(0, 8)" stripe empty-text="暂无探测记录。">
                <el-table-column label="类型" min-width="110"><template #default="{ row }">{{ probeTypeLabel(row.probe_type) }}</template></el-table-column>
                <el-table-column label="结果" width="90"><template #default="{ row }"><el-tag :type="row.success ? 'success' : 'danger'" effect="light">{{ row.success ? '通过' : '失败' }}</el-tag></template></el-table-column>
                <el-table-column label="延迟" width="100" align="right"><template #default="{ row }">{{ row.latency_ms }} ms</template></el-table-column>
                <el-table-column label="时间" min-width="120"><template #default="{ row }">{{ formatRelativeTime(row.created_at) }}</template></el-table-column>
              </el-table>
            </AstraPanel>
          </div>
        </template>

        <!-- Token -->
        <template v-else-if="tab === 'tokens'">
          <div class="gateway-token-kpis">
            <div class="token-breakdown">
              <article><small>输入 Token</small><strong>{{ stats ? formatTokens(stats.input_tokens) : '—' }}</strong></article>
              <article><small>输出 Token</small><strong>{{ stats ? formatTokens(stats.output_tokens) : '—' }}</strong></article>
              <article><small>总 Token</small><strong>{{ stats ? formatTokens(stats.total_tokens) : '—' }}</strong></article>
            </div>
          </div>
          <AstraPanel title="Token 趋势" :subtitle="windowLabel">
            <template #action><el-radio-group :model-value="window" size="small" @change="setWindow">
              <el-radio-button v-for="item in windows" :key="item.id" :value="item.id">{{ item.label }}</el-radio-button>
            </el-radio-group></template>
            <GatewayTrendChart v-if="stats" :buckets="stats.trend" mode="tokens" tall />
            <div v-else class="gateway-placeholder">{{ loading ? '加载中…' : '暂无数据' }}</div>
          </AstraPanel>
        </template>

        <!-- 性能 -->
        <template v-else-if="tab === 'performance'">
          <AstraPanel title="性能指标" :subtitle="`${windowLabel} · 平均 / p50 / p95`">
            <template #action><el-radio-group :model-value="window" size="small" @change="setWindow">
              <el-radio-button v-for="item in windows" :key="item.id" :value="item.id">{{ item.label }}</el-radio-button>
            </el-radio-group></template>
            <dl class="performance-list gateway-latency">
              <div v-for="row in latencyRows" :key="row.label"><dt>{{ row.label }}</dt><dd>{{ row.value }}</dd></div>
            </dl>
            <div class="gateway-peak">
              <span>峰值并发 <b>{{ stats?.peak_concurrency ?? '—' }}</b></span>
              <span>QPS <b>{{ stats ? stats.qps.toFixed(2) : '—' }}</b></span>
              <span>失败 <b class="gateway-peak__bad">{{ stats?.errors ?? '—' }}</b></span>
            </div>
          </AstraPanel>
          <AstraPanel title="请求量趋势" :subtitle="windowLabel">
            <GatewayTrendChart v-if="stats" :buckets="stats.trend" mode="requests" />
          </AstraPanel>
        </template>

        <!-- 限制 -->
        <template v-else-if="tab === 'limits'">
          <div class="gateway-detail-grid">
            <AstraPanel title="并发与权重">
              <dl class="gateway-info-list">
                <div><dt>最大并发</dt><dd>{{ node.max_concurrency || '不限' }}</dd></div>
                <div><dt>有效权重</dt><dd>{{ node.weight }}</dd></div>
                <div><dt>调度状态</dt><dd>{{ schedulingStateLabel(node.scheduling_state) }}</dd></div>
                <div><dt>配置状态</dt><dd>{{ configStateLabel(node.config_state) }}</dd></div>
              </dl>
            </AstraPanel>
            <AstraPanel title="Token 额度">
              <dl class="gateway-info-list">
                <div><dt>额度策略</dt><dd>{{ quotaPolicyLabel(node.quota_policy) }}</dd></div>
                <div><dt>每小时限额</dt><dd>{{ node.hourly_token_limit ?? '不限' }} · 本小时已用 {{ hourTokens ? formatTokens(hourTokens.total_tokens) : '—' }}</dd></div>
                <div><dt>每日限额</dt><dd>{{ node.daily_token_limit ?? '不限' }} · 今日已用 {{ dayTokens ? formatTokens(dayTokens.total_tokens) : '—' }}</dd></div>
                <div><dt>未知用量（今日）</dt><dd>{{ dayTokens?.unknown_usage_requests ?? '—' }}</dd></div>
              </dl>
              <p class="gateway-note"><Timer :size="13" />额度基于已完成请求的实际 usage 原子计入，因并发可能产生有限超额。</p>
            </AstraPanel>
          </div>
        </template>

        <!-- 健康 -->
        <template v-else-if="tab === 'health'">
          <div class="gateway-detail-grid">
            <AstraPanel title="健康状态">
              <dl class="gateway-info-list">
                <div><dt>健康态</dt><dd><el-tag :type="tagType(healthTone(node.health_state))" effect="light">{{ healthStateLabel(node.health_state) }}</el-tag></dd></div>
                <div><dt>连续成功</dt><dd>{{ node.success_streak }}</dd></div>
                <div><dt>连续失败</dt><dd>{{ node.failure_streak }}</dd></div>
                <div><dt>最近探测</dt><dd>{{ formatDateTime(node.last_checked_at) }}</dd></div>
              </dl>
              <pre class="gateway-snapshot">{{ JSON.stringify(node.health_detail, null, 2) }}</pre>
            </AstraPanel>
            <AstraPanel title="探测历史" :subtitle="`最近 ${healthChecks.length} 条`" flush>
              <el-table :data="healthChecks" stripe empty-text="暂无探测记录。">
                <el-table-column label="类型" min-width="110"><template #default="{ row }">{{ probeTypeLabel(row.probe_type) }}</template></el-table-column>
                <el-table-column label="结果" width="90"><template #default="{ row }"><el-tag :type="row.success ? 'success' : 'danger'" effect="light">{{ row.success ? '通过' : '失败' }}</el-tag></template></el-table-column>
                <el-table-column label="延迟" width="100" align="right"><template #default="{ row }">{{ row.latency_ms }} ms</template></el-table-column>
                <el-table-column label="状态码" width="90" align="right"><template #default="{ row }">{{ row.status_code ?? '—' }}</template></el-table-column>
                <el-table-column label="错误" min-width="180"><template #default="{ row }"><span class="gateway-err" :title="row.error ?? ''">{{ row.error ?? '—' }}</span></template></el-table-column>
                <el-table-column label="时间" min-width="150"><template #default="{ row }">{{ formatDateTime(row.created_at) }}</template></el-table-column>
              </el-table>
            </AstraPanel>
          </div>
        </template>

        <!-- 日志 -->
        <template v-else-if="tab === 'logs'">
          <AstraPanel :title="`调用日志 · ${requests.total} 条`" flush>
            <template #action><el-button size="small" :loading="loading" :disabled="loading" @click="loadRequests">刷新</el-button></template>
            <el-table :data="requests.items" stripe empty-text="暂无调用记录。">
              <el-table-column label="时间" min-width="155"><template #default="{ row }">{{ formatDateTime(row.started_at) }}</template></el-table-column>
              <el-table-column label="Key / 模型" min-width="170"><template #default="{ row }"><strong>{{ row.key_id ? row.key_id.slice(0, 12) : '—' }}</strong><small>{{ row.model ?? '—' }}</small></template></el-table-column>
              <el-table-column label="状态" min-width="150"><template #default="{ row }"><el-tag v-if="row.error_code" type="danger" effect="light" :title="row.error_code">{{ row.error_code }}</el-tag><el-tag v-else :type="row.status_code && row.status_code < 400 ? 'success' : 'warning'" effect="light">{{ row.status_code ?? '—' }}</el-tag></template></el-table-column>
              <el-table-column label="流式" width="90"><template #default="{ row }">{{ row.streaming ? 'SSE' : '普通' }}</template></el-table-column>
              <el-table-column prop="retry_count" label="重试" width="75" />
              <el-table-column label="Token" min-width="170" align="right"><template #default="{ row }">{{ row.usage_known ? `${row.input_tokens ?? 0} / ${row.output_tokens ?? 0} / ${row.total_tokens ?? 0}` : 'unknown' }}</template></el-table-column>
              <el-table-column label="TTFT" width="100" align="right"><template #default="{ row }">{{ row.ttft_ms ?? '—' }} ms</template></el-table-column>
              <el-table-column label="总时长" width="110" align="right"><template #default="{ row }">{{ row.duration_ms ?? '—' }} ms</template></el-table-column>
            </el-table>
          </AstraPanel>
        </template>

        <!-- 配置 -->
        <template v-else>
          <AstraPanel title="节点配置" subtitle="配置态由管理员维护，健康态与运行态不由配置覆盖">
            <template #action><el-button v-if="canManage" type="primary" size="small" @click="openEditor"><Pencil :size="13" />编辑配置</el-button></template>
            <dl class="gateway-info-list gateway-config-list">
              <div><dt>名称</dt><dd>{{ node.name }}</dd></div>
              <div><dt>资源池</dt><dd>{{ poolName(node.pool_id) }}</dd></div>
              <div><dt>Base URL</dt><dd>{{ node.base_url }}</dd></div>
              <div><dt>认证</dt><dd>{{ authTypeLabel(node.auth_type) }} · {{ node.auth_header }}</dd></div>
              <div><dt>连接 / 请求超时</dt><dd>{{ node.connect_timeout_seconds ?? '默认' }} / {{ node.request_timeout_seconds ?? '默认' }} 秒</dd></div>
              <div><dt>健康路径</dt><dd>{{ node.health_path || '继承默认' }}</dd></div>
              <div><dt>探测间隔</dt><dd>{{ node.probe_interval_seconds ?? '继承默认' }} 秒</dd></div>
              <div><dt>支持模型</dt><dd>{{ node.models.length ? node.models.join('、') : '未配置' }}</dd></div>
              <div><dt>权重 / 并发</dt><dd>{{ node.weight }} / {{ node.max_concurrency || '不限' }}</dd></div>
              <div><dt>额度</dt><dd>{{ node.hourly_token_limit ?? '不限' }} / {{ node.daily_token_limit ?? '不限' }}（{{ quotaPolicyLabel(node.quota_policy) }}）</dd></div>
              <div><dt>排序</dt><dd>{{ node.sort_order }}</dd></div>
              <div><dt>创建 / 更新</dt><dd>{{ formatDateTime(node.created_at) }} / {{ formatDateTime(node.updated_at) }}</dd></div>
            </dl>
          </AstraPanel>
        </template>
      </div>
      <div v-else-if="loading" class="gateway-gate-loading"><LoaderCircle :size="18" class="spin" />正在加载节点…</div>
      <p v-else class="gateway-alert"><TriangleAlert :size="15" />{{ error || '节点不存在' }}<RouterLink to="/gateway?tab=nodes">返回列表</RouterLink></p>

      <GatewayNodeDrawer :open="editorOpen" :node="node" :pools="pools" @close="editorOpen = false" @saved="load" />
    </GatewayGate>
  </div>
</template>

<script setup lang="ts">
import {
  Activity,
  ArrowLeft,
  CheckCircle2,
  Coins,
  Gauge,
  LoaderCircle,
  Pause,
  Pencil,
  Play,
  Power,
  PowerOff,
  RadioTower,
  Timer,
  TriangleAlert,
  Waves,
} from 'lucide-vue-next'
import { computed, onMounted, ref, watch } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import {
  gatewayApi,
  GatewayApiError,
  type GatewayHealthCheck,
  type GatewayNode,
  type GatewayPool,
  type GatewayProbeType,
  type GatewayRequestPage,
  type GatewayScopeStats,
  type GatewayStatsWindow,
} from '@/api/gateway'
import AstraMetricCard from '@/components/astra/AstraMetricCard.vue'
import AstraPanel from '@/components/astra/AstraPanel.vue'
import { confirmDialog } from '@/composables/useConfirm'
import { notify } from '@/composables/useToast'
import { useGatewayAuth } from '@/composables/useGatewayAuth'
import { formatTokens } from '@/utils/format'
import {
  authTypeLabel,
  authenticationLabel,
  authenticationResult,
  authenticationTone,
  configStateLabel,
  errorMessage,
  formatDateTime,
  formatPercent,
  formatRelativeTime,
  healthStateLabel,
  healthTone,
  probeTypeLabel,
  quotaPolicyLabel,
  schedulingStateLabel,
  schedulingTone,
} from '@/utils/gateway'
import GatewayGate from '@/views/gateway/GatewayGate.vue'
import GatewayNodeDrawer from '@/views/gateway/GatewayNodeDrawer.vue'
import GatewayTrendChart from '@/views/gateway/GatewayTrendChart.vue'

const route = useRoute()
const { hasRole, disconnect } = useGatewayAuth()
const canManage = computed(() => hasRole('node'))
const nodeId = computed(() => String(route.params.id ?? ''))
const tabs = [
  { id: 'overview', label: '概览' },
  { id: 'tokens', label: 'Token' },
  { id: 'performance', label: '性能' },
  { id: 'limits', label: '限制' },
  { id: 'health', label: '健康' },
  { id: 'logs', label: '日志' },
  { id: 'config', label: '配置' },
]
const tab = ref('overview')
const window = ref<GatewayStatsWindow>('today')
const node = ref<GatewayNode | null>(null)
const pools = ref<GatewayPool[]>([])
const healthChecks = ref<GatewayHealthCheck[]>([])
const stats = ref<GatewayScopeStats | null>(null)
const hourTokens = ref<GatewayScopeStats | null>(null)
const dayTokens = ref<GatewayScopeStats | null>(null)
const requests = ref<GatewayRequestPage>({ items: [], total: 0, page: 1, page_size: 50 })
const loading = ref(false)
const working = ref(false)
const error = ref('')
const editorOpen = ref(false)
const allProbes: GatewayProbeType[] = ['NETWORK', 'SERVICE', 'MODEL', 'STREAM']
const windows: Array<{ id: GatewayStatsWindow; label: string }> = [
  { id: 'hour', label: '本小时' },
  { id: 'today', label: '今日' },
  { id: '7d', label: '近 7 天' },
  { id: '30d', label: '近 30 天' },
]
const windowLabel = computed(() => windows.find((item) => item.id === window.value)?.label ?? '')
const probeAuthentication = computed(() => authenticationResult(healthChecks.value))
function tagType(tone: string): 'success' | 'warning' | 'danger' | 'info' | 'primary' {
  if (tone === 'success' || tone === 'warning' || tone === 'danger' || tone === 'info') return tone
  return 'info'
}

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

function poolName(poolId: string | null): string {
  if (!poolId) return '未分配'
  return pools.value.find((pool) => pool.id === poolId)?.name ?? poolId
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    const [nodeValue, poolList, checks, requestPage, hours, days] = await Promise.all([
      gatewayApi.node(nodeId.value),
      gatewayApi.pools(),
      gatewayApi.healthChecks(nodeId.value, 100),
      gatewayApi.requests({ node_id: nodeId.value, page: 1, page_size: 50 }),
      gatewayApi.stats('node', 'hour', nodeId.value),
      gatewayApi.stats('node', 'today', nodeId.value),
    ])
    node.value = nodeValue
    pools.value = poolList
    healthChecks.value = checks
    requests.value = requestPage
    hourTokens.value = hours
    dayTokens.value = days
    await loadStats()
  } catch (reason) {
    if (reason instanceof GatewayApiError && reason.status === 401) { disconnect(); return }
    error.value = errorMessage(reason, '节点详情加载失败')
  } finally {
    loading.value = false
  }
}

async function loadStats() {
  try {
    stats.value = await gatewayApi.stats('node', window.value, nodeId.value)
  } catch (reason) {
    error.value = errorMessage(reason, '统计加载失败')
  }
}

async function loadRequests() {
  try {
    requests.value = await gatewayApi.requests({ node_id: nodeId.value, page: 1, page_size: 50 })
  } catch (reason) {
    notify(errorMessage(reason, '日志加载失败'), 'error')
  }
}

function setWindow(next: GatewayStatsWindow) {
  window.value = next
  void loadStats()
}

async function probe() {
  working.value = true
  try {
    const result = await gatewayApi.probeNode(nodeId.value, allProbes)
    const passed = result.checks.filter((check) => check.success).length
    notify(`探测完成：${passed}/${result.checks.length} 项通过`, passed === result.checks.length ? 'success' : 'info')
    await load()
  } catch (reason) {
    notify(errorMessage(reason, '探测失败'), 'error')
  } finally {
    working.value = false
  }
}

async function drain() {
  const confirmed = await confirmDialog({ title: '安全下线节点', message: '活跃请求会继续完成，新请求改走其它节点。', confirmLabel: '安全下线', danger: true })
  if (!confirmed) return
  working.value = true
  try {
    await gatewayApi.drainNode(nodeId.value)
    notify('节点已进入安全下线')
    await load()
  } catch (reason) {
    notify(errorMessage(reason, '下线失败'), 'error')
  } finally {
    working.value = false
  }
}

async function restore() {
  working.value = true
  try {
    await gatewayApi.activateNode(nodeId.value)
    notify('节点已恢复调度')
    await load()
  } catch (reason) {
    notify(errorMessage(reason, '恢复失败'), 'error')
  } finally {
    working.value = false
  }
}

async function toggleConfig() {
  if (!node.value) return
  const enable = node.value.config_state !== 'ENABLED'
  working.value = true
  try {
    await gatewayApi.updateNode(nodeId.value, { config_state: enable ? 'ENABLED' : 'DISABLED' })
    notify(enable ? '节点已启用' : '节点已禁用')
    await load()
  } catch (reason) {
    notify(errorMessage(reason, '状态更新失败'), 'error')
  } finally {
    working.value = false
  }
}

function openEditor() { editorOpen.value = true }

watch(nodeId, () => { void load() })
onMounted(load)
</script>

<style scoped>

.gateway-node { display: grid; gap: 15px; }
.gateway-node__hero { display: flex; align-items: flex-start; justify-content: space-between; gap: 18px; padding: 18px; border: 1px solid var(--astra-border); border-radius: 14px; background: var(--astra-bg-card); box-shadow: var(--astra-shadow-panel); }
.gateway-node__identity small { color: var(--astra-text-muted); font-size: var(--astra-font-helper); font-family: var(--astra-font-family); }
.gateway-node__identity h2 { margin: 4px 0 0; color: var(--astra-text-primary); }
.gateway-node__badges { display: flex; flex-wrap: wrap; align-items: center; gap: 7px; margin-top: 9px; }
.gateway-node__pool { padding: 3px 9px; color: var(--astra-primary-bright); border: 1px solid var(--astra-primary-border); border-radius: 999px; background: var(--astra-primary-soft); font-size: var(--astra-font-helper); }
.gateway-node__url { margin: 8px 0 0; color: var(--astra-text-muted); font-size: var(--astra-font-helper); font-family: var(--astra-font-family); }
.gateway-node__actions { display: flex; flex-wrap: wrap; gap: 8px; }
.gateway-metrics { grid-template-columns: repeat(6, minmax(0, 1fr)); margin-bottom: 0; }
.gateway-metrics :deep(.metric-card) { min-height: 118px; }
.gateway-detail-grid { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1.1fr); gap: 16px; align-items: start; }
.gateway-info-list { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0 18px; margin: 0; }
.gateway-config-list { grid-template-columns: repeat(2, minmax(0, 1fr)); }
.gateway-info-list div { display: flex; justify-content: space-between; gap: 10px; padding: 9px 0; border-bottom: 1px solid var(--astra-border); }
.gateway-info-list dt { color: var(--astra-text-muted); font-size: var(--astra-font-helper); }
.gateway-info-list dd { margin: 0; color: var(--astra-text-primary); font-size: var(--astra-font-helper); text-align: right; word-break: break-word; }
.gateway-latency { grid-template-columns: 1fr; margin: 0; }
.gateway-peak { display: flex; gap: 16px; margin-top: 12px; padding-top: 12px; border-top: 1px solid var(--astra-border); color: var(--astra-text-muted); font-size: var(--astra-font-helper); }
.gateway-peak b { color: var(--astra-text-primary); }
.gateway-peak__bad { color: var(--astra-danger); }
.gateway-token-kpis { display: grid; grid-template-columns: minmax(0, 420px); }
.gateway-placeholder { display: grid; place-items: center; height: 220px; color: var(--astra-text-muted); font-size: var(--astra-font-helper); }
.gateway-snapshot { max-height: 260px; margin: 12px 0 0; padding: 12px; overflow: auto; color: var(--astra-text-secondary); border: 1px solid var(--astra-border); border-radius: 9px; background: var(--astra-bg-base); font: var(--astra-font-helper)/1.5 var(--astra-font-family); white-space: pre-wrap; }
.gateway-auth-line { display: flex; align-items: center; gap: 8px; margin: 0; padding: 10px 12px; color: var(--astra-text-muted); border-bottom: 1px solid var(--astra-border); font-size: var(--astra-font-helper); }
.gateway-err { max-width: 220px; overflow: hidden; color: var(--astra-danger); font-size: var(--astra-font-helper); text-overflow: ellipsis; white-space: nowrap; }
.gateway-log-table { min-width: 900px; }
.gateway-log-table td > strong { display: block; color: var(--astra-text-primary); font-size: var(--astra-font-helper); }
.gateway-log-table td > small { display: block; color: var(--astra-text-muted); font-size: var(--astra-font-micro); }
.gateway-num, .gateway-time { white-space: nowrap; font-size: var(--astra-font-helper); font-variant-numeric: tabular-nums; }
.gateway-alert { display: flex; align-items: center; gap: 7px; margin: 0; padding: 10px 12px; color: var(--astra-danger); border: 1px solid rgba(228, 93, 106, .2); border-radius: 9px; background: var(--astra-danger-soft); font-size: var(--astra-font-helper); }
.gateway-alert a { margin-left: auto; color: inherit; text-decoration: underline; }
.gateway-gate-loading { display: flex; align-items: center; justify-content: center; gap: 9px; min-height: 40vh; color: var(--astra-text-muted); font-size: var(--astra-font-control); }
@media (max-width: 1280px) { .gateway-metrics { grid-template-columns: repeat(3, minmax(0, 1fr)); } .gateway-detail-grid { grid-template-columns: 1fr; } }
@media (max-width: 760px) { .gateway-node__hero { flex-direction: column; } .gateway-metrics { grid-template-columns: repeat(2, minmax(0, 1fr)); } .gateway-info-list { grid-template-columns: 1fr; } }

.gateway-node-tabs :deep(.el-tabs__content){display:none}
.gateway-node__actions :deep(.el-button){margin-left:0}
:deep(.el-table strong){display:block;color:var(--astra-text-primary);font-size:var(--astra-font-helper)}
:deep(.el-table small){display:block;color:var(--astra-text-muted);font-size:var(--astra-font-micro)}
</style>